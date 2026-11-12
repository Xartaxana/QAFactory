"""diff_scope.classify: did a change touch an executable line, or only what humans read?
The rubric a re-review turns on (QA-EXAMPLE: a comment-only fix should not re-run the
whole rubric+arch-check+suite). Exercises is_prose() and classify() directly — the pure
part of the module; git_diff() is a one-line subprocess wrapper around `git diff` and is
not re-tested here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diff_scope as S  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish  # noqa: E402

check("a blank line is prose", S.is_prose("   "))
check("a python comment is prose", S.is_prose("    # TC-001"))
check("a js comment is prose", S.is_prose("  // @case QA-1_TC_001"))
check("a docstring fence is prose", S.is_prose('    """'))
check("a docstring body on its own line is prose", S.is_prose('    "@case QA-1_TC_001"'))
check("an assert is not prose", not S.is_prose("    assert x == 1"))
check("a decorator is not prose", not S.is_prose("@pytest.mark.api"))
check("a function call is not prose", not S.is_prose("    charge(order)"))
check("a string ASSIGNMENT is not prose (it executes)", not S.is_prose('    name = "x"'))

MARKER_ONLY = (
    "diff --git a/tests/test_x.py b/tests/test_x.py\n"
    "index aaa..bbb 100644\n"
    "--- a/tests/test_x.py\n"
    "+++ b/tests/test_x.py\n"
    "@@ -4,0 +5,2 @@\n"
    '+    """@case QA-1_TC_001"""\n'
    "+\n"
)
check_eq("a marker/docstring-only diff classifies as comment-only", S.classify(MARKER_ONLY)[0], "comment-only")

REAL_CHANGE = MARKER_ONLY + "@@ -9,1 +11,1 @@\n-    assert x == 1\n+    assert x == 2\n"
scope, why = S.classify(REAL_CHANGE)
check_eq("one changed assertion among comment noise still classifies as code", scope, "code")
check("classify names the deciding executable line, not the comment noise",
      any("assert x == 2" in line for line in why))

check_eq("an empty diff is no-change", S.classify("")[0], "no-change")

MIXED = ("diff --git a/a.ts b/a.ts\n@@ -1,0 +2,2 @@\n"
         "+// renamed for clarity\n+  const timeout = 5000\n")
check_eq("a comment plus one real constant is code (the safe direction costs a run, not a ship)",
         S.classify(MIXED)[0], "code")

check_eq("changed_lines drops diff plumbing (headers, hunk markers) and keeps only +/- bodies",
         S.changed_lines("diff --git a/x b/x\nindex 1..2 100644\n@@ -1,1 +1,1 @@\n-old\n+new\n"),
         ["old", "new"])

# --- executable_sha: what can execute, by tokenize (D-0017, t-016 Amendments 3 and 5) -----------
# A receipt keeps its proof over a comment-only change of its test. Which change is comment-only is
# decided by Python's own tokenizer, never line by line (critic t-048: judged per line, `"alice",`
# in an assert's list was "prose" and a vacuous assert kept "the check is live").
BASE = ("import pytest\n\n\n@pytest.mark.api\ndef test_x(client):\n"
        '    """Check the limit."""\n    total = client.total()\n    assert total == 1\n')
SAME = S.executable_sha(BASE)
check_eq("a 64-hex sha256", (len(SAME), all(c in "0123456789abcdef" for c in SAME)), (64, True))
check_eq("a comment line added: the same code",
         S.executable_sha(BASE.replace("    total", "    # the client sums the lines\n    total")), SAME)
check_eq("a comment line edited: the same code",
         S.executable_sha(BASE.replace("    total", "    # the client sums the lines\n    total")),
         S.executable_sha(BASE.replace("    total", "    # the client adds the lines up\n    total")))
check_eq("a trailing comment on a code line: the same code (a COMMENT token)",
         S.executable_sha(BASE.replace("import pytest", "import pytest  # noqa")), SAME)
check_eq("a whole-line comment removed: the same code",
         S.executable_sha("# header\n" + BASE), SAME)
check_eq("blank lines added: the same code", S.executable_sha(BASE.replace("\n\n\n", "\n\n\n\n\n\n")), SAME)
check_eq("a docstring line edited: the same code",
         S.executable_sha(BASE.replace('"""Check the limit."""', '"""Check the limit, twice."""')), SAME)
check_eq("a docstring fence and a string-only line: the same code",
         S.executable_sha(BASE.replace('    """Check the limit."""', '    """\n    "@case QA-1_TC_001"\n    """')),
         SAME)
check("an assert changed: other code", S.executable_sha(BASE.replace("== 1", "== 2")) != SAME)
check("a decorator changed: other code", S.executable_sha(BASE.replace("mark.api", "mark.smoke")) != SAME)
check("a code line re-indented: other code (indentation is code in Python)",
      S.executable_sha(BASE.replace("    total =", "        total =")) != SAME)
check("a code line added: other code", S.executable_sha(BASE + "    assert total > 0\n") != SAME)
check_eq("CRLF against LF: the same code", S.executable_sha(BASE.replace("\n", "\r\n")), SAME)
check_eq("an empty file has a defined code sha (only the end marker)",
         (len(S.executable_sha("")), S.executable_tokens("")), (64, [(0, "")]))
check_eq("...equal to a file of comments and blank lines only", S.executable_sha("# a\n\n# b\n"), S.executable_sha(""))
# A multi-line docstring is ONE string token and a logical line of its own: editing its body is
# cosmetic. (Line by line its body line is not prose - which is why no gate reads is_prose.)
DOC = 'def test_y():\n    """Summary.\n\n    body words here\n    """\n    assert True\n'
check_eq("a bare docstring body line is not prose to the per-line REPORT", S.is_prose("    body words here"), False)
check_eq("...but the docstring is one STRING logical line: editing it is the same code",
         S.executable_sha(DOC.replace("body words here", "other words")), S.executable_sha(DOC))
check_eq("a trailing newline or none is the same code", S.executable_sha(BASE.rstrip("\n")), SAME)
check_eq("no code sha for what does not tokenize (the raw rule only)",
         (S.executable_sha("x = (\n    1,\n"), S.executable_sha("def f():\n    a = 1\n  b = 2\n")), ("", ""))
check_eq("no code sha for a file that is not .py", (S.executable_sha(BASE, "test_x.js"), S.executable_sha(BASE, "x.txt")),
         ("", ""))
check_eq("...a .py name is Python", S.executable_sha(BASE, "tests/test_x.py"), SAME)
check_eq("classify: not Python -> code", S.classify_texts(BASE, BASE + "# c\n", "a.ts")[0], "code")

# --- the adversarial battery (critic t-048): each AT the construct (a comment beside it: the same
# code) and BEYOND it (the value inside it changed: other code) --------------------------------------
BATTERY = {
    "a list element in an assert": ('def test_a(names):\n    assert names == [\n        "alice",\n        "bob",\n    ]\n',
                                    '"alice",', '"alicia",'),
    "a URL argument on its own line": ('def test_b(client):\n    response = client.get(\n'
                                       '        "https://api.example.invalid/v1/users",\n    )\n    assert response.ok\n',
                                       '/v1/users', '/v2/users'),
    "a dict entry value": ('def test_c(client):\n    payload = {\n        "role":\n            "admin",\n    }\n'
                           '    assert client.post(payload).ok\n', '"admin",', '"guest",'),
    "a // continuation": ('def test_d(total):\n    half = (total\n            // 2)\n    assert half == 5\n',
                          '// 2)', '// 3)'),
    "a backslash-continued expected string": ('def test_e(msg):\n    assert msg == "limit " \\\n        "reached"\n',
                                              '"reached"', '"passed"'),
    "an assert ending in a triple-quoted literal": ('def test_f(text):\n    assert text == """\nhello\n"""\n',
                                                    "hello", "goodbye"),
    "a star-unpack continuation": ('def test_g(base, extra):\n    items = [\n        *base,\n    ]\n'
                                   '    assert items\n', "*base,", "*extra,"),
}
for label, (src, old_bit, new_bit) in BATTERY.items():
    at = src.replace("def ", "# a comment beside it\ndef ", 1)
    check_eq(f"{label}: AT (a comment beside it) - the same code", S.executable_sha(at), S.executable_sha(src))
    beyond = src.replace(old_bit, new_bit)
    check(f"{label}: BEYOND (its value changed) - other code", S.executable_sha(beyond) != S.executable_sha(src))
    check_eq(f"{label}: ...and classify says code", S.classify_texts(src, beyond, "test_x.py")[0], "code")
# marker-shaped text inside a docstring is a STRING token: it never opens a marker
FAKE = ('def test_h(x):\n    """Example:\n    @pytest.mark.qa(\n        case="TC-1",\n    """\n'
        '    y = x + 1\n    assert y == 2\n')
check_eq("a marker-shaped docstring: editing the docstring is the same code",
         S.executable_sha(FAKE.replace("Example:", "For example:")), S.executable_sha(FAKE))
check("a marker-shaped docstring followed by a code change: other code",
      S.executable_sha(FAKE.replace("x + 1", "x + 2")) != S.executable_sha(FAKE))

# --- the factory's case markers are cosmetic (D-0019 item 3, t-016 Amendments 3-4) ---------------
# Their shapes come from references/case-markers.json, the file manifest_from_tests.py reads too.
import json  # noqa: E402
import subprocess  # noqa: E402

MARKERS = json.loads(S.MARKERS_FILE.read_text(encoding="utf-8"))
CASE, UNRESOLVED = MARKERS["pytest"]["case"], MARKERS["pytest"]["unresolved"]
check_eq("the marker names are the data file's, the ones manifest_from_tests reads",
         (CASE, UNRESOLVED), (__import__("manifest_from_tests").MARK_QA, __import__("manifest_from_tests").MARK_UNRESOLVED))
MARKED = BASE.replace("@pytest.mark.api\n", f'@pytest.mark.api\n@pytest.mark.{CASE}(case="TC-001", then=[1])\n')
check_eq("a case marker added: the same code", S.executable_sha(MARKED), SAME)
check_eq("...and comment-only", S.classify_texts(BASE, MARKED)[0], "comment-only")
EDITED = MARKED.replace("then=[1]", 'then=[1, 2], note="two reads"')
check_eq("a case marker edited: the same code", S.executable_sha(EDITED), SAME)
check_eq("...and comment-only", S.classify_texts(MARKED, EDITED)[0], "comment-only")
check_eq("a case marker removed: comment-only", S.classify_texts(MARKED, BASE)[0], "comment-only")
for label, args in (("calls code", "case=setup_db()"), ("names a variable", "case=CASE_ID"),
                    ("unpacks a mapping", "**shared"), ("builds a value", 'case="TC-" + str(1)')):
    CALLS = BASE.replace("@pytest.mark.api\n", f"@pytest.mark.api\n@pytest.mark.{CASE}({args})\n")
    check(f"marker arguments that {label} ({args}): other code", S.executable_sha(CALLS) != SAME)
check_eq("marker arguments that are literals (a list, a dict, a tuple, a negative number): the same code",
         S.executable_sha(BASE.replace("@pytest.mark.api\n", f'@pytest.mark.api\n@pytest.mark.{CASE}('
                                       'case="TC-1", then=[1, 2], note={"a": (1, -2)})\n')), SAME)
check("a case marker with code after it on the same logical line: other code",
      S.executable_sha(BASE.replace("@pytest.mark.api\n", f'@pytest.mark.api\n@pytest.mark.{CASE}(case="TC-1").x\n'))
      != SAME)
check("a marker not named in the data (another prefix) stays code",
      S.executable_sha(BASE.replace("@pytest.mark.api\n", '@pytest.mark.api\n@mark.qa(case="TC-1")\n')) != SAME)
check_eq("a single-line marker is prose line by line too (one predicate)",
         S.is_prose(f'@pytest.mark.{CASE}(case="TC-001")  # why'), True)
SKIPPED = BASE.replace("@pytest.mark.api\n", "@pytest.mark.api\n@pytest.mark.skip(reason=\"flaky\")\n")
check("@pytest.mark.skip added: other code", S.executable_sha(SKIPPED) != SAME)
check_eq("...and classify says code", S.classify_texts(BASE, SKIPPED)[0], "code")
for other in ("parametrize(\"x\", [1])", "xfail", "usefixtures(\"db\")", "api"):
    check(f"@pytest.mark.{other} is not a case marker", not S.is_prose(f"@pytest.mark.{other}"))
check("a name that only starts like a marker is not one", not S.is_prose(f"@pytest.mark.{CASE}_other(case=1)"))
MULTI = BASE.replace("@pytest.mark.api\n", f'@pytest.mark.api\n@pytest.mark.{UNRESOLVED}(\n'
                                           '    case="TC-002",\n    reason="impossible",\n'
                                           '    detail="no channel (reads the cache)")\n')
check_eq("a multi-line case marker: the same code", S.executable_sha(MULTI), SAME)
CONT = MULTI.replace('"impossible"', '"blocked-flow"')
check_eq("only a continuation line changed: classify says comment-only", S.classify_texts(MULTI, CONT)[0],
         "comment-only")
check_eq("...though the line alone is not prose (the file decides, not the line)",
         S.is_prose('    reason="blocked-flow",'), False)
CODE_AFTER = MULTI.replace('(reads the cache)")\n', '(reads the cache)"); total = 0\n')
check("code after the balancing ')' on the closing line: other code", S.executable_sha(CODE_AFTER) != SAME)
check_eq("...and classify says code", S.classify_texts(MULTI, CODE_AFTER)[0], "code")
OPEN = BASE + f'@pytest.mark.{CASE}(\n    case="TC-9",\nassert_everything()\n'
check("a marker that never closes gives its lines back as code", S.executable_sha(OPEN) != S.executable_sha(BASE))
check_eq("CRLF only: no-change", S.classify_texts(BASE, BASE.replace("\n", "\r\n"))[0], "no-change")

# --- the CLI decides a file by git show <rev>:<file> against the bytes on disk --------------------
from harness import cleanup, temp_dir  # noqa: E402

repo = temp_dir("qa-diff-scope-")
try:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(git + ["init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text(MULTI, encoding="utf-8")
    subprocess.run(git + ["add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(git + ["commit", "-q", "-m", "x"], cwd=repo, check=True, capture_output=True)
    (repo / "tests" / "test_x.py").write_text(CONT, encoding="utf-8")
    check_eq("CLI: a continuation line of a case marker edited since HEAD -> comment-only",
             S.file_scope("HEAD", "tests/test_x.py", repo)[0], "comment-only")
    (repo / "tests" / "test_x.py").write_text(CODE_AFTER, encoding="utf-8")
    check_eq("CLI: code after the closing ')' -> code", S.file_scope("HEAD", "tests/test_x.py", repo)[0], "code")
    scope, why = S.file_scope("no-such-rev", "tests/test_x.py", repo)
    check_eq("CLI: a revision git cannot show -> code (the safe direction)", scope, "code")
    check("...and says so", any("git cannot show no-such-rev:tests/test_x.py" in w for w in why), str(why))
    check_eq("CLI: a file git never held -> code", S.file_scope("HEAD", "tests/test_new.py", repo)[0], "code")
    (repo / "tests" / "test_x.py").unlink()
    check_eq("CLI: a file gone from disk -> code", S.file_scope("HEAD", "tests/test_x.py", repo)[0], "code")
finally:
    cleanup(repo)

finish("test_diff_scope")
