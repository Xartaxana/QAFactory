"""run_suite reads a test run's report through reporters.read_rows, and `--detail` reads any of them.

Before this change run_suite kept two private parsers beside the shared reader: `parse_trx`
capped ALL its rows at 500 (a failed row beyond the cap was lost), read an absent outcome as
`passed`, and `--detail` read only the JUnit copy of a run, so a .NET run's failure text was
unreachable. The summary shape is a contract (run blocks, the dashboard and the manifest join read
`totals`, `failed`, `results`, `skip_reasons`, `results_note`): the two GOLDEN fixtures below were
run through the OLD functions first and their output is pinned here key for key; the intended
differences are the checks of `intended_differences` and nowhere else.

B-407 B-report (the last four sections): the report format of an untyped run is chosen from the cure table
(`reporter_choice`: explicit, run.reporter, `command_formats`, the command's cure row, none), a guess that reads no
tests is said (`parse_gap`), and the words of a run with no report come from the command's cure row.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

import hooklib  # noqa: E402
import run_suite as RUN  # noqa: E402

TRX_NS = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"
LONG_MESSAGE = "an assertion message that goes on and on " * 5          # 205 characters
LONG_SKIP = "the stand is not available for this window " * 5            # 215 characters
PY = sys.executable


def failed_rows(*rows) -> list:
    return [{"test": test, "kind": kind, "why": why} for test, kind, why in rows]


def result_rows(*rows) -> list:
    return [{"test_id": test, "status": status, "reason": reason} for test, status, reason in rows]


# --- fixtures -----------------------------------------------------------------------------------

JUNIT_GOLDEN = f'''<?xml version="1.0" encoding="utf-8"?>
<testsuites>
<testsuite name="pytest" errors="2" failures="4" skipped="4" tests="12" time="1.25">
<testcase classname="tests.test_cart" name="test_total" time="0.01"><system-out>captured by a passing test</system-out></testcase>
<testcase classname="tests.test_cart" name="test_discount[10-percent]" time="0.02">
<failure message="AssertionError: wrong total&#10;assert 90 == 91">def test_discount():
&gt;       assert total(100, 10) == 91, "wrong total"
E       AssertionError: wrong total

tests/test_cart.py:12: AssertionError</failure><system-out>discount computed: 90</system-out></testcase>
<testcase classname="tests.test_cart" name="test_fixture_missing" time="0.00">
<error message="fixture 'db' not found">E       fixture 'db' not found</error></testcase>
<testcase classname="tests.test_cart" name="test_both" time="0.00">
<failure message="first">tests/test_cart.py:20: AssertionError</failure>
<error message="teardown broke">tests/conftest.py:5: RuntimeError</error></testcase>
<testcase classname="tests.test_cart" name="test_error_first" time="0.00">
<error message="setup broke">tests/conftest.py:9: RuntimeError</error>
<failure message="then asserted">tests/test_cart.py:40: AssertionError</failure></testcase>
<testcase classname="tests.test_cart" name="test_failure_body_only" time="0.00">
<failure>E   assert False
E   second line of the body</failure></testcase>
<testcase classname="tests.test_cart" name="test_failure_long" time="0.00">
<failure message="{LONG_MESSAGE}">tests/test_cart.py:50: AssertionError</failure></testcase>
<testcase classname="tests.test_cart" name="test_skip" time="0.00">
<skipped type="pytest.skip" message="needs the stand">tests/test_cart.py:30: needs the stand</skipped></testcase>
<testcase classname="tests.test_cart" name="test_skip_bare" time="0.00"><skipped/></testcase>
<testcase classname="tests.test_cart" name="test_skip_long" time="0.00">
<skipped type="pytest.skip" message="{LONG_SKIP}"/></testcase>
<testcase classname="tests.test_cart" name="test_skip_and_failure" time="0.00">
<failure message="boom">tests/test_cart.py:60: AssertionError</failure><skipped message="later"/></testcase>
<testcase classname="tests.test_cart" name="test_skip_again" time="0.00">
<skipped type="pytest.skip" message="needs the stand"/></testcase>
</testsuite>
<testsuite name="second" errors="0" failures="1" skipped="0" tests="2" time="0.5">
<testcase classname="tests.test_other" name="test_fine" time="0.1"/>
<testcase classname="tests.test_other" name="test_third" time="0.1"><failure message="x">tests/test_other.py:3: AssertionError</failure></testcase>
</testsuite>
</testsuites>
'''


def trx_result(test_name, outcome, message=None, stack=None, extra="") -> str:
    attr = f' outcome="{outcome}"' if outcome is not None else ""
    name = f' testName="{test_name}"' if test_name is not None else ""
    info = ""
    if message is not None or stack is not None:
        info = "<Output><ErrorInfo>"
        if message is not None:
            info += f"<Message>{message}</Message>"
        if stack is not None:
            info += f"<StackTrace>{stack}</StackTrace>"
        info += "</ErrorInfo></Output>"
    return f'    <UnitTestResult testId="id-{test_name}"{name}{attr}>{info}{extra}</UnitTestResult>'


def trx_doc(results: list, total: int, passed: int, failed: int, error: int, not_executed: int,
            inconclusive: int = 0) -> str:
    definitions = "\n".join(
        f'    <UnitTest name="{n}" id="id-Backend.Tests.CartTests.{n}"><TestMethod '
        f'className="Backend.Tests.CartTests" name="{n}"/></UnitTest>'
        for n in ("Saves", "Rejects_empty"))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<TestRun id="7c1d" name="ci@build-host" xmlns="{TRX_NS}">\n  <Results>\n'
            + "\n".join(results) + f'\n  </Results>\n  <TestDefinitions>\n{definitions}\n  </TestDefinitions>\n'
            f'  <ResultSummary outcome="Failed"><Counters total="{total}" executed="{total - not_executed}" '
            f'passed="{passed}" failed="{failed}" error="{error}" notExecuted="{not_executed}" '
            f'inconclusive="{inconclusive}"/></ResultSummary>\n</TestRun>\n')


STACK = ("   at Backend.Tests.CartTests.Rejects_empty() in C:\\clone\\backend\\Tests\\CartTests.cs:line 42\n"
         "   at System.RuntimeMethodHandle.InvokeMethod(Object target)")

TRX_GOLDEN = trx_doc([
    trx_result("Backend.Tests.CartTests.Saves", "Passed"),
    trx_result("Backend.Tests.CartTests.Rejects_empty", "Failed",
               "Assert.Equal() Failure\nExpected: 1\nActual:   0", STACK),
    trx_result("Backend.Tests.CartTests.Blank_first_lines", "Failed", "\n   \nFirst real line\nsecond", STACK),
    trx_result("Backend.Tests.CartTests.Long_message", "Failed", LONG_MESSAGE, STACK),
    trx_result("Backend.Tests.CartTests.Stack_only", "Failed", None, STACK),
    trx_result("Backend.Tests.CartTests.No_output", "Failed"),
    trx_result("Backend.Tests.CartTests.Setup_threw", "Error", "setup threw", STACK),
    trx_result("Backend.Tests.CartTests.Needs_stand", "NotExecuted", "Skipped: needs the stand\nsecond line", ""),
    trx_result("Backend.Tests.CartTests.Not_run", "NotExecuted"),
    trx_result("Backend.Tests.CartTests.Flaky_stand", "Inconclusive", "Inconclusive: flaky stand", ""),
    trx_result("Backend.Tests.CartTests.Lower", "passed"),
    trx_result('Backend.Tests.CartTests.Blank(value: &quot;&quot;)', "Passed"),
    trx_result('Backend.Tests.CartTests.Blank(value: &quot; &quot;)', "Passed"),
    trx_result(None, "Passed"),
], total=14, passed=5, failed=4, error=1, not_executed=2, inconclusive=1)

# What the OLD run_suite.parse_junitxml / parse_trx returned for the two documents above: the old
# functions were run on them BEFORE the change and the output is pasted here unedited (only the
# row helpers above spell it shorter). `totals` come from the report's counters, `results` is one
# row per test, `skip_reasons` is a tally of the first 80 characters of the reason.
JUNIT_BEFORE = {
    "totals": {"tests": 14, "failures": 5, "errors": 2, "skipped": 4, "time_s": 1.8, "passed": 3},
    "failed": failed_rows(
        ("tests.test_cart::test_discount[10-percent]", "failure", "AssertionError: wrong total"),
        ("tests.test_cart::test_fixture_missing", "error", "fixture 'db' not found"),
        ("tests.test_cart::test_both", "failure", "first"),
        ("tests.test_cart::test_both", "error", "teardown broke"),
        ("tests.test_cart::test_error_first", "failure", "then asserted"),
        ("tests.test_cart::test_error_first", "error", "setup broke"),
        ("tests.test_cart::test_failure_body_only", "failure", "E   assert False"),
        ("tests.test_cart::test_failure_long", "failure", LONG_MESSAGE[:160]),
        ("tests.test_cart::test_skip_and_failure", "failure", "boom"),
        ("tests.test_other::test_third", "failure", "x")),
    "results": result_rows(
        ("tests.test_cart::test_total", "passed", ""),
        ("tests.test_cart::test_discount[10-percent]", "failed", "AssertionError: wrong total"),
        ("tests.test_cart::test_fixture_missing", "error", "fixture 'db' not found"),
        ("tests.test_cart::test_both", "error", "teardown broke"),
        ("tests.test_cart::test_error_first", "error", "setup broke"),
        ("tests.test_cart::test_failure_body_only", "failed", "E   assert False"),
        ("tests.test_cart::test_failure_long", "failed", LONG_MESSAGE[:160]),
        ("tests.test_cart::test_skip", "skipped", "needs the stand"),
        ("tests.test_cart::test_skip_bare", "skipped", "(no reason)"),
        ("tests.test_cart::test_skip_long", "skipped", LONG_SKIP[:160]),
        ("tests.test_cart::test_skip_and_failure", "skipped", "later"),
        ("tests.test_cart::test_skip_again", "skipped", "needs the stand"),
        ("tests.test_other::test_fine", "passed", ""),
        ("tests.test_other::test_third", "failed", "x")),
    "skip_reasons": {"needs the stand": 2, "(no reason)": 1, LONG_SKIP[:80]: 1, "later": 1},
}

TRX_BEFORE = {
    "totals": {"tests": 14, "failures": 4, "errors": 1, "skipped": 3, "time_s": 0.0, "passed": 6},
    "failed": failed_rows(
        ("Backend.Tests.CartTests.Rejects_empty", "failed", "Assert.Equal() Failure"),
        ("Backend.Tests.CartTests.Blank_first_lines", "failed", "First real line"),
        ("Backend.Tests.CartTests.Long_message", "failed", LONG_MESSAGE[:160]),
        ("Backend.Tests.CartTests.Stack_only", "failed", ""),
        ("Backend.Tests.CartTests.No_output", "failed", ""),
        ("Backend.Tests.CartTests.Setup_threw", "error", "setup threw")),
    "results": result_rows(
        ("Backend.Tests.CartTests.Saves", "passed", ""),
        ("Backend.Tests.CartTests.Rejects_empty", "failed", "Assert.Equal() Failure"),
        ("Backend.Tests.CartTests.Blank_first_lines", "failed", "First real line"),
        ("Backend.Tests.CartTests.Long_message", "failed", LONG_MESSAGE[:160]),
        ("Backend.Tests.CartTests.Stack_only", "failed", ""),
        ("Backend.Tests.CartTests.No_output", "failed", ""),
        ("Backend.Tests.CartTests.Setup_threw", "error", "setup threw"),
        ("Backend.Tests.CartTests.Needs_stand", "skipped", "Skipped: needs the stand"),
        ("Backend.Tests.CartTests.Not_run", "skipped", ""),
        ("Backend.Tests.CartTests.Flaky_stand", "skipped", "Inconclusive: flaky stand"),
        ("Backend.Tests.CartTests.Lower", "passed", ""),
        ('Backend.Tests.CartTests.Blank(value: "")', "passed", ""),
        ('Backend.Tests.CartTests.Blank(value: " ")', "passed", ""),
        ("?", "passed", "")),
    "skip_reasons": {},
}

# The same facts as above, written the way the INTENDED differences need them (see
# intended_differences): a TRX with an absent outcome, the two outcomes that were no status at all,
# one outside every vocabulary; JUnit nested suites; the two "keep the old text" cases.
TRX_OUTCOMES = trx_doc([
    trx_result("N.absent", None),
    trx_result("N.timeout", "Timeout", "timed out after 60s", ""),
    trx_result("N.aborted", "Aborted", "run aborted", ""),
    trx_result("N.pending", "Pending"),
    trx_result("N.passed", "Passed"),
], total=5, passed=1, failed=0, error=0, not_executed=0)

NESTED_JUNIT = ('<testsuites><testsuite name="outer" tests="2" failures="1" errors="0" skipped="0" time="0.2">'
                '<testsuite name="inner" tests="1" failures="1" errors="0" skipped="0" time="0.1">'
                '<testcase classname="a" name="t1"><failure message="inner broke">tb</failure></testcase>'
                '</testsuite><testcase classname="a" name="t2"/></testsuite></testsuites>')

JUNIT_BLANK_MESSAGE = ('<testsuite tests="1" failures="1" errors="0" skipped="0">'
                       '<testcase classname="w" name="blank_message"><failure message="   ">'
                       'body line one\nbody line two</failure></testcase></testsuite>')

TRX_INNER = trx_doc([
    '    <UnitTestResult testId="o-1" testName="Ordered.WithOwnMessage" outcome="Failed">'
    '<Output><ErrorInfo><Message>One or more inner tests failed</Message></ErrorInfo></Output>'
    '<InnerResults>' + trx_result("Ordered.WithOwnMessage.Step", "Failed", "step broke", "") +
    '</InnerResults></UnitTestResult>',
    '    <UnitTestResult testId="o-2" testName="Ordered.NoOwnMessage" outcome="Failed">'
    '<InnerResults>' + trx_result("Ordered.NoOwnMessage.Step", "Failed", "inner boom", "") +
    '</InnerResults></UnitTestResult>',
], total=4, passed=0, failed=4, error=0, not_executed=0)


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def many(count: int, kind: str, extras: list) -> str:
    """`count` passed tests followed by `extras` (rows already spelled for `kind`)."""
    if kind == "junit":
        cases = [f'<testcase classname="suite" name="pass-{i}"/>' for i in range(count)]
        return ('<testsuite tests="%d" failures="0" errors="0" skipped="0">' % (count + len(extras))
                + "".join(cases + extras) + "</testsuite>")
    rows = [trx_result(f"Suite.Pass_{i}", "Passed") for i in range(count)]
    return trx_doc(rows + extras, total=count + len(extras), passed=count, failed=0, error=0, not_executed=0)


# --- item 1: the goldens ------------------------------------------------------------------------

def goldens(tmp: Path) -> None:
    check_eq("JUNIT golden: the new parse_junitxml returns the old summary, key for key",
             RUN.parse_junitxml(write(tmp, "golden.junit.xml", JUNIT_GOLDEN)), JUNIT_BEFORE)
    check_eq("TRX golden: the new parse_trx returns the old summary, key for key",
             RUN.parse_trx(write(tmp, "golden.trx", TRX_GOLDEN)), TRX_BEFORE)
    # The shape the mine tests' fake pytest writes: a bare <testsuite> root, no <testsuites>.
    bare = RUN.parse_junitxml(write(tmp, "bare.xml", (
        '<testsuite tests="2" failures="1" errors="0" skipped="0">'
        '<testcase classname="tests.test_a" name="test_green"/>'
        '<testcase classname="tests.test_a" name="test_red"><failure message="AssertionError: boom">'
        'trace of test_red</failure></testcase></testsuite>')))
    check_eq("a bare <testsuite> root gives the old summary", bare, {
        "totals": {"tests": 2, "failures": 1, "errors": 0, "skipped": 0, "time_s": 0.0, "passed": 1},
        "failed": failed_rows(("tests.test_a::test_red", "failure", "AssertionError: boom")),
        "results": result_rows(("tests.test_a::test_green", "passed", ""),
                               ("tests.test_a::test_red", "failed", "AssertionError: boom")),
        "skip_reasons": {}})


# --- the intended differences -------------------------------------------------------------------

def intended_differences(tmp: Path) -> None:
    got = RUN.parse_trx(write(tmp, "outcomes.trx", TRX_OUTCOMES))
    by_name = {r["test_id"]: r for r in got["results"]}
    # (a) a result with NO outcome is not_run (it was `passed`: an unknown reported as a fact)
    check_eq("(a) an absent TRX outcome is not_run, not passed", by_name["N.absent"]["status"], "not_run")
    check_eq("(a) an outcome outside every vocabulary is not_run, not the raw word",
             by_name["N.pending"]["status"], "not_run")
    check_eq("(a) a real Passed stays passed", by_name["N.passed"]["status"], "passed")
    # (b) Timeout / Aborted are error, and an error is a failed row of the summary
    check_eq("(b) Timeout is error", by_name["N.timeout"]["status"], "error")
    check_eq("(b) Aborted is error", by_name["N.aborted"]["status"], "error")
    check_eq("(b) both are in `failed`, with their message",
             got["failed"], failed_rows(("N.timeout", "error", "timed out after 60s"),
                                        ("N.aborted", "error", "run aborted")))
    check_eq("(a, b) the totals are still the report's own counters", got["totals"],
             {"tests": 5, "failures": 0, "errors": 0, "skipped": 0, "time_s": 0.0, "passed": 5})

    # (c) a testcase of a nested suite is ONE row (the old reader listed it once per ancestor suite)
    nested = RUN.parse_junitxml(write(tmp, "nested.xml", NESTED_JUNIT))
    check_eq("(c) a nested testcase appears once in results", [r["test_id"] for r in nested["results"]],
             ["a::t1", "a::t2"])
    check_eq("(c) and once in failed", [f["test"] for f in nested["failed"]], ["a::t1"])
    check_eq("(c) the totals are what the rows say, not every <testsuite>'s counters added (that said 3 / 2 "
             "over two rows)",
             (nested["totals"]["tests"], nested["totals"]["failures"]), (2, 1))
    # the old reader's answer for this very file, for the record
    check_eq("(c) the old reader listed the nested testcase twice (control)",
             [r["test_id"] for r in OLD_NESTED["results"]], ["a::t1", "a::t2", "a::t1"])

    # (d) observed beyond the three listed: a testcase directly under <testsuites> is a row now
    loose = RUN.parse_junitxml(write(tmp, "loose.xml", '<testsuites><testcase classname="l" name="t"/></testsuites>'))
    check_eq("(d) a testcase outside any <testsuite> is read (it was dropped)",
             [r["test_id"] for r in loose["results"]], ["l::t"])


MIXED_JUNIT = ('<testsuites><testsuite name="a" tests="3" failures="1" errors="0" skipped="0" time="0.3">'
               '<testsuite name="b" tests="1" failures="0" errors="0" skipped="0" time="0.1">'
               '<testcase classname="m" name="inner_ok"/></testsuite>'
               '<testcase classname="m" name="direct_ok"/>'
               '<testcase classname="m" name="direct_red"><failure message="boom">tb</failure></testcase>'
               '</testsuite><testsuite name="c" tests="1" failures="0" errors="0" skipped="1" time="0.1">'
               '<testcase classname="m" name="other"><skipped message="later"/></testcase></testsuite></testsuites>')


def totals_match_rows(tmp: Path) -> None:
    """Totals and rows answer one question: a report cannot state a total its rows do not add up to.

    The old `parse_junitxml` added the counters of EVERY nested <testsuite> (a nested suite's
    testcases are counted again by its ancestors) while the rows were one per testcase, so one
    file said 3 tests / 2 failures over two rows. Rule (run_suite.parse_junitxml): the report's
    counters stand as written while their `tests` agree with the rows `reporters.read_rows`
    returns (every flat report); when they do not, the counts are the rows' own, by status.

    `strict` fixtures must agree by status as well; JUNIT_GOLDEN and the TRX goldens only on
    `tests` and on the sum, because their hand-written counters count a testcase that carries
    both a failure and an error twice (the counters are the report's, as the goldens pin)."""
    cases = (("flat bare <testsuite>", "flat.xml", '<testsuite tests="2" failures="1" errors="0" skipped="0">'
              '<testcase classname="f" name="ok"/><testcase classname="f" name="red"><failure message="x">t</failure>'
              '</testcase></testsuite>', RUN.parse_junitxml, True),
             ("flat <testsuites> with two suites", "flat2.xml",
              '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="1"><testcase classname="f" name="s">'
              '<skipped message="r"/></testcase></testsuite><testsuite tests="1" failures="0" errors="1" skipped="0">'
              '<testcase classname="f" name="e"><error message="e">t</error></testcase></testsuite></testsuites>',
              RUN.parse_junitxml, True),
             ("nested suites", "nested2.xml", NESTED_JUNIT, RUN.parse_junitxml, True),
             ("nested suites and direct testcases in one suite, plus a sibling suite", "mixed.xml", MIXED_JUNIT,
              RUN.parse_junitxml, True),
             ("a testcase outside any suite", "loose2.xml",
              '<testsuites><testcase classname="l" name="t"/></testsuites>', RUN.parse_junitxml, True),
             ("an empty <testsuites>", "empty1.xml", "<testsuites/>", RUN.parse_junitxml, True),
             ("an empty <testsuite>", "empty2.xml", '<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
              RUN.parse_junitxml, True),
             ("the JUnit golden", "golden2.xml", JUNIT_GOLDEN, RUN.parse_junitxml, False),
             ("the TRX golden", "golden2.trx", TRX_GOLDEN, RUN.parse_trx, False),
             ("the TRX outcomes", "outcomes2.trx", TRX_OUTCOMES, RUN.parse_trx, False))
    for label, name, text, parse, strict in cases:
        got = parse(write(tmp, name, text))
        totals, statuses = got["totals"], [r["status"] for r in got["results"]]
        check_eq(f"{label}: totals.tests is the number of rows", totals["tests"], len(statuses))
        check_eq(f"{label}: passed + failures + errors + skipped adds up to tests",
                 totals["passed"] + totals["failures"] + totals["errors"] + totals["skipped"], totals["tests"])
        if strict:
            check_eq(f"{label}: and each count is the rows' own",
                     (totals["failures"], totals["errors"], totals["skipped"], totals["passed"]),
                     (statuses.count("failed"), statuses.count("error"), statuses.count("skipped"),
                      statuses.count("passed")))
    check_eq("an empty <testsuites> is (0, 0) with no rows",
             (RUN.parse_junitxml(tmp / "empty1.xml")["totals"]["tests"],
              RUN.parse_junitxml(tmp / "empty1.xml")["results"]), (0, []))
    mixed = RUN.parse_junitxml(tmp / "mixed.xml")["totals"]
    check_eq("mixed nested and direct testcases: counted once per testcase",
             (mixed["tests"], mixed["failures"], mixed["skipped"], mixed["passed"]), (4, 1, 1, 2))
    check_eq("a flat report keeps its counters as written (the golden's 5 failures, over 4 failed rows)",
             RUN.parse_junitxml(tmp / "golden2.xml")["totals"], JUNIT_BEFORE["totals"])


# The old parse_junitxml on NESTED_JUNIT (captured before the change): the testcase of the inner
# suite was listed once for `outer` and once more for `inner`.
OLD_NESTED = {"results": result_rows(("a::t1", "failed", "inner broke"), ("a::t2", "passed", ""),
                                     ("a::t1", "failed", "inner broke"))}


def keep_old_text(tmp: Path) -> None:
    """The two cases where the OLD summary text differs from what the row gives; both are decided.
    A JUnit failure with a whitespace-only message takes its reason from the body (the old text was
    empty). A TRX parent with no message of its own has an empty reason (the old text was the first
    inner message) because every inner result is a row of its own in `failed`, `results` and
    `--detail`, with that very message: nothing is lost, and the inner row says it where it
    happened."""
    blank = RUN.parse_junitxml(write(tmp, "blank.xml", JUNIT_BLANK_MESSAGE))
    check_eq("whitespace-only JUnit message: the why is the body's first line (the old text was empty)",
             blank["failed"], failed_rows(("w::blank_message", "failure", "body line one")))
    inner = RUN.parse_trx(write(tmp, "inner.trx", TRX_INNER))
    why = {f["test"]: f["why"] for f in inner["failed"]}
    check_eq("TRX parent with its own message: the old and the new text agree",
             why["Ordered.WithOwnMessage"], "One or more inner tests failed")
    check_eq("TRX parent with no message of its own: its reason is empty", why["Ordered.NoOwnMessage"], "")
    check_eq("and the inner result is a row of its own in `failed`, carrying the message the old parent text had",
             why["Ordered.NoOwnMessage.Step"], "inner boom")
    check_eq("every inner result is a failed row, parent first", [f["test"] for f in inner["failed"]],
             ["Ordered.WithOwnMessage", "Ordered.WithOwnMessage.Step", "Ordered.NoOwnMessage",
              "Ordered.NoOwnMessage.Step"])
    reasons = {r["test_id"]: r["reason"] for r in inner["results"]}
    check_eq("and in `results`, with the same reason", reasons["Ordered.NoOwnMessage.Step"], "inner boom")


# --- item 2: the row cap ------------------------------------------------------------------------

def caps(tmp: Path) -> None:
    cap = RUN.RESULT_ROWS_CAP
    check_eq("the cap is 500 passed rows", cap, 500)
    junit_fail = '<testcase classname="suite" name="fail-last"><failure message="late failure">tb</failure></testcase>'
    trx_fail = trx_result("Suite.Fail_last", "Failed", "late failure", "")
    for kind, parse, fail, ident in (("junit", RUN.parse_junitxml, junit_fail, "suite::fail-last"),
                                     ("trx", RUN.parse_trx, trx_fail, "Suite.Fail_last")):
        suffix = ".xml" if kind == "junit" else ".trx"
        at = parse(write(tmp, f"at-{kind}{suffix}", many(cap, kind, [fail])))
        check_eq(f"{kind} AT the cap: all {cap} passed rows and the failed one are listed", len(at["results"]), cap + 1)
        check("and there is no note", "results_note" not in at)
        check_eq(f"{kind} AT the cap: the failed row is in `failed`", [f["test"] for f in at["failed"]], [ident])
        beyond = parse(write(tmp, f"beyond-{kind}{suffix}", many(cap + 1, kind, [fail])))
        check_eq(f"{kind} BEYOND the cap: {cap} passed rows and the failed one", len(beyond["results"]), cap + 1)
        check_eq(f"{kind} BEYOND the cap: the failed row is listed",
                 [r["status"] for r in beyond["results"]].count("failed"), 1)
        check_eq(f"{kind} BEYOND the cap: exactly {cap} passed rows are listed",
                 [r["status"] for r in beyond["results"]].count("passed"), cap)
        check_eq(f"{kind} BEYOND the cap: the note says how many passed rows are not listed",
                 beyond.get("results_note"),
                 "1 passed rows beyond the 500-row cap are counted in totals, not listed")
        check_eq(f"{kind} BEYOND the cap: the failed row is in `failed`", [f["test"] for f in beyond["failed"]], [ident])
    # every kind of not-passed row is listed, whatever the cap: skipped and error too
    junit_other = ['<testcase classname="suite" name="skip-last"><skipped message="needs the stand"/></testcase>',
                   '<testcase classname="suite" name="err-last"><error message="setup broke">tb</error></testcase>']
    trx_other = [trx_result("Suite.Skip_last", "NotExecuted", "Skipped: needs the stand", ""),
                 trx_result("Suite.Err_last", "Error", "setup broke", ""),
                 trx_result("Suite.Absent_last", None)]
    big_junit = RUN.parse_junitxml(write(tmp, "big.xml", many(cap + 100, "junit", junit_other)))
    big_trx = RUN.parse_trx(write(tmp, "big.trx", many(cap + 100, "trx", trx_other)))
    check_eq("JUNIT 600 passed + skipped + error: the two are listed",
             sorted(r["status"] for r in big_junit["results"] if r["status"] != "passed"), ["error", "skipped"])
    check_eq("TRX 600 passed + skipped + error + not_run: all three are listed",
             sorted(r["status"] for r in big_trx["results"] if r["status"] != "passed"),
             ["error", "not_run", "skipped"])
    check_eq("TRX 600 passed: the note counts only passed rows",
             big_trx.get("results_note"), "100 passed rows beyond the 500-row cap are counted in totals, not listed")
    check_eq("JUNIT 600 passed: the same note", big_junit.get("results_note"),
             "100 passed rows beyond the 500-row cap are counted in totals, not listed")


# --- item 3: --detail ---------------------------------------------------------------------------

ROOT = None


LAST_ERR = ""      # what the last `call` wrote to stderr (RUN REPORT GAP lines live there)


def call(*argv) -> tuple:
    """run_suite.main() in this process: (exit code, stdout)."""
    global LAST_ERR
    hooklib._PROJECT_ROOT_CACHE = None
    out, err = io.StringIO(), io.StringIO()
    old_argv, old_cwd = sys.argv, os.getcwd()
    sys.argv = ["run_suite.py", *[str(a) for a in argv]]
    os.chdir(ROOT)
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                RUN.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    LAST_ERR = err.getvalue()
    return code, out.getvalue()


def answer(text: str) -> dict:
    lines = [line for line in text.strip().splitlines() if line.startswith("{")]
    return json.loads(lines[-1]) if lines else {}


TASK = "DET-1"


def evidence() -> Path:
    path = ROOT / "qa-factory" / "artifacts" / TASK / "evidence"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rel(name: str) -> str:
    return str(Path("qa-factory") / "artifacts" / TASK / "evidence" / name)


def stored_run(label: str, ts: str, *, junit=None, trx=None, summary=None, mtime=None) -> None:
    """One stored run of `label`: its report copies, its summary and its log, like run() leaves them."""
    ev = evidence()
    stem = f"{label}-{ts}"
    for suffix, text in ((".junit.xml", junit), (".trx", trx)):
        if text is not None:
            path = write(ev, stem + suffix, text)
            if mtime:
                os.utime(path, (mtime, mtime))
    if summary is not None:
        write(ev, stem + ".json", json.dumps(summary))
    write(ev, stem + ".log", "log\n")


def first(got: dict) -> dict:
    return (got.get("matches") or [{}])[0]


def detail(label: str, test: str) -> tuple:
    code, out = call("--task", TASK, "--label", label, "--detail", test)
    return code, answer(out)


def detail_cases() -> None:
    stored_run("junit-run", "20260101-000001", junit=JUNIT_GOLDEN,
               summary={"reporter": "pytest", "exit_code": 1})
    stored_run("trx-run", "20260101-000001", trx=TRX_GOLDEN, summary={"reporter": "trx", "exit_code": 1})

    # --- a JUnit run: the output is what it always was ---------------------------------------
    code, got = detail("junit-run", "test_discount")
    check_eq("JUNIT --detail exits 0", code, 0)
    check_eq("JUNIT --detail: the answer is unchanged, key for key", got, {
        "status": "ok", "junitxml": rel("junit-run-20260101-000001.junit.xml"),
        "log": rel("junit-run-20260101-000001.log"),
        "matches": [{"test": "tests.test_cart::test_discount[10-percent]", "kind": "failure",
                     "message": "AssertionError: wrong total\nassert 90 == 91",
                     "text": 'def test_discount():\n>       assert total(100, 10) == 91, "wrong total"\n'
                             "E       AssertionError: wrong total\n\ntests/test_cart.py:12: AssertionError",
                     "system_out_tail": "discount computed: 90"}],
        "more_matches": 0})
    code, got = detail("junit-run", "test_both")
    check_eq("JUNIT --detail: a testcase with a failure and an error gives both, failure first",
             [(m["kind"], m["message"]) for m in got["matches"]], [("failure", "first"), ("error", "teardown broke")])
    code, got = detail("junit-run", "test_error_first")
    check_eq("JUNIT --detail: failure first even when the error comes first in the document",
             [(m["kind"], m["message"]) for m in got["matches"]],
             [("failure", "then asserted"), ("error", "setup broke")])
    code, got = detail("junit-run", "test_total")
    check_eq("JUNIT --detail of a passing test is not_found, exit 2", (code, got["status"]), (2, "not_found"))
    check_eq("and lists the failed names, a skipped testcase with a failure included", got["failed"], [
        "tests.test_cart::test_discount[10-percent]", "tests.test_cart::test_fixture_missing",
        "tests.test_cart::test_both", "tests.test_cart::test_error_first",
        "tests.test_cart::test_failure_body_only", "tests.test_cart::test_failure_long",
        "tests.test_cart::test_skip_and_failure", "tests.test_other::test_third"])
    check_eq("not_found names the junitxml, as before", got["junitxml"], rel("junit-run-20260101-000001.junit.xml"))
    check("a JUnit answer carries no `reporter` and no note", "reporter" not in got and "reporter_note" not in got)

    # --- a TRX run: its rows are visible ----------------------------------------------------------
    code, got = detail("trx-run", "Rejects_empty")
    check_eq("TRX --detail exits 0", code, 0)
    check_eq("TRX --detail: the answer", got, {
        "status": "ok", "trx": rel("trx-run-20260101-000001.trx"), "reporter": "trx",
        "log": rel("trx-run-20260101-000001.log"),
        "matches": [{"test": "Backend.Tests.CartTests.Rejects_empty", "kind": "failure",
                     "message": "Assert.Equal() Failure\nExpected: 1\nActual:   0", "text": STACK.strip()}],
        "more_matches": 0})
    code, got = detail("trx-run", "Setup_threw")
    check_eq("TRX --detail: an Error result is kind error", first(got).get("kind"), "error")
    code, got = detail("trx-run", "No_output")
    check_eq("TRX --detail: a failed result with no ErrorInfo is still an answer, with nothing to quote",
             (code, got.get("matches")), (0, [{"test": "Backend.Tests.CartTests.No_output", "kind": "failure",
                                          "message": "", "text": ""}]))
    stored_run("inner-run", "20260101-000001", trx=TRX_INNER, summary={"reporter": "trx"})
    code, got = detail("inner-run", "Ordered.NoOwnMessage")
    check_eq("TRX --detail: the parent with no message and its inner result are both shown, the inner one with its message",
             (code, [(m["test"], m["message"]) for m in got.get("matches", [])]),
             (0, [("Ordered.NoOwnMessage", ""), ("Ordered.NoOwnMessage.Step", "inner boom")]))
    code, got = detail("trx-run", "Saves")
    check_eq("TRX --detail of a passing test is not_found, exit 2", (code, got["status"]), (2, "not_found"))
    check_eq("and lists the failed and error names", got.get("failed"), [
        "Backend.Tests.CartTests.Rejects_empty", "Backend.Tests.CartTests.Blank_first_lines",
        "Backend.Tests.CartTests.Long_message", "Backend.Tests.CartTests.Stack_only",
        "Backend.Tests.CartTests.No_output", "Backend.Tests.CartTests.Setup_threw"])
    code, got = detail("trx-run", "Needs_stand")
    check_eq("a skipped TRX result is not a failure to show", (code, got["status"]), (2, "not_found"))

    # --- no report at all --------------------------------------------------------------------
    stored_run("crashed", "20260101-000001", summary={"reporter": "trx", "exit_code": 1,
                                                       "execution_status": "broken_run", "error_head": ["ERROR: x"]})
    code, got = detail("crashed", "anything")
    check_eq("no stored report: exit 2", code, 2)
    check("the answer says so under `no_report`", bool(got.get("no_report")) and "report" in got["no_report"])
    check_eq("the old `no_junitxml` key is kept with the same value", got.get("no_junitxml"), got.get("no_report"))
    check_eq("and the old status spelling is kept", got.get("status"), "no_junitxml")
    check_eq("the cause the summary recorded still comes with it", (got.get("execution_status"), got.get("error_head")),
             ("broken_run", ["ERROR: x"]))
    code, got = detail("never-ran", "anything")
    check_eq("a label with nothing stored at all says the same", (code, bool(got.get("no_report")),
                                                                  got.get("no_junitxml") == got.get("no_report")),
             (2, True, True))

    # --- a summary with no `reporter` field: inferred from the file, and said ----------------------
    stored_run("old-junit", "20260101-000001", junit=JUNIT_GOLDEN, summary={"exit_code": 1})
    stored_run("old-trx", "20260101-000001", trx=TRX_GOLDEN, summary={"exit_code": 1})
    code, got = detail("old-junit", "test_third")
    check_eq("no reporter field, a .junit.xml copy: read as junit-xml", (code, first(got).get("message")), (0, "x"))
    check_in("and the answer says the reporter was inferred", "inferred", got.get("reporter_note", ""))
    check_in("naming what it was inferred from", "no reporter field", got.get("reporter_note", ""))
    code, got = detail("old-trx", "Rejects_empty")
    check_eq("no reporter field, a .trx copy: read as trx", (code, got.get("trx"), got.get("reporter")),
             (0, rel("old-trx-20260101-000001.trx"), "trx"))
    check_in("and says so", "inferred", got.get("reporter_note", ""))
    stored_run("no-summary", "20260101-000001", trx=TRX_GOLDEN)
    code, got = detail("no-summary", "Rejects_empty")
    check_eq("no summary at all: the file still decides, and says so",
             (code, "inferred" in got.get("reporter_note", "")), (0, True))

    # --- both copies of one label: the summary's reporter decides --------------------------------------
    stored_run("both-trx", "20260101-000001", junit=JUNIT_GOLDEN, trx=TRX_GOLDEN,
               summary={"reporter": "trx"}, mtime=1_700_000_000)
    stored_run("both-junit", "20260101-000001", junit=JUNIT_GOLDEN, trx=TRX_GOLDEN,
               summary={"reporter": "junit-xml"}, mtime=1_700_000_000)
    # the copy the summary does NOT name is the NEWER one, so "latest wins" would pick it
    os.utime(evidence() / "both-trx-20260101-000001.junit.xml", (1_800_000_000, 1_800_000_000))
    os.utime(evidence() / "both-junit-20260101-000001.trx", (1_800_000_000, 1_800_000_000))
    code, got = detail("both-trx", "Rejects_empty")
    check_eq("both copies, summary says trx: the TRX is read", (code, got.get("trx")),
             (0, rel("both-trx-20260101-000001.trx")))
    check("and nothing is inferred", "reporter_note" not in got)
    code, got = detail("both-junit", "test_third")
    check_eq("both copies, summary says junit-xml: the JUnit is read", (code, got.get("junitxml")),
             (0, rel("both-junit-20260101-000001.junit.xml")))
    # the reporter the summary names has no stored copy: the file that exists is read, and it says so
    stored_run("mismatch", "20260101-000001", junit=JUNIT_GOLDEN, summary={"reporter": "trx"})
    code, got = detail("mismatch", "test_third")
    check_eq("a summary naming trx with only a JUnit copy: the copy is read as what it is", (code, "junitxml" in got),
             (0, True))
    check_in("and the mismatch is said", "no stored report", got.get("reporter_note", ""))
    # an unreadable copy is an answer, not a traceback
    stored_run("broken", "20260101-000001", trx="<TestRun><Results>", summary={"reporter": "trx"})
    code, got = detail("broken", "x")
    check_eq("a report that is not XML: status report_unreadable, exit 2", (code, got.get("status")),
             (2, "report_unreadable"))


# --- the whole chain: a TRX run through run(), then --detail ------------------------------------------

FAKE_DOTNET = r'''
import sys
from pathlib import Path
Path("out").mkdir(exist_ok=True)
Path("out/results.trx").write_text(open("source.trx", encoding="utf-8").read(), encoding="utf-8")
print("Failed!  - Failed: 1, Passed: 502, Total: 503")
sys.exit(1)
'''


def end_to_end() -> None:
    (ROOT / "source.trx").write_text(many(502, "trx", [trx_result("Suite.Fail_last", "Failed", "late failure", STACK)]),
                                     encoding="utf-8")
    (ROOT / "fake_dotnet.py").write_text(FAKE_DOTNET, encoding="utf-8")
    cfg_path = ROOT / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["run"] = {"reporter": "trx", "report_path": "out/results.trx"}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    code, out = call("--task", TASK, "--label", "dotnet", "--", PY, str(ROOT / "fake_dotnet.py"))
    summary = answer(out)
    check_eq("a TRX run ends with the command's exit code", code, 1)
    check_eq("its summary names the reporter", summary.get("reporter"), "trx")
    check("and the stored copy", str(summary.get("trx", "")).endswith(".trx"), str(summary.get("trx")))
    check_eq("the failed row is listed although 502 rows passed before it",
             [r["test_id"] for r in summary.get("results", []) if r["status"] == "failed"], ["Suite.Fail_last"])
    check_eq("the cap note counts the passed rows that are not listed",
             summary.get("results_note"), "2 passed rows beyond the 500-row cap are counted in totals, not listed")
    check_eq("the run's totals are the report's counters", (summary.get("totals") or {}).get("tests"), 503)
    code, got = detail("dotnet", "Fail_last")
    check_eq("--detail of that very run reads the stored TRX", (code, got.get("status"), got.get("reporter")),
             (0, "ok", "trx"))
    check_eq("and shows the failure", first(got).get("message"), "late failure")


# --- B-407 B-report: the format of an untyped run comes from the cure table, and a guess that reads nothing is said ----

FAKE_REPORT = r'''
import sys
from pathlib import Path
out, src = sys.argv[1], sys.argv[2]
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
print("it ran, and wrote its report")
'''
FAKE_NOTHING = 'print("it ran, and wrote no report")\n'
ONE_GREEN = '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="e" name="ok"/></testsuite>'
ZERO_TESTS = '<testsuite tests="0" failures="0" errors="0" skipped="0"/>'
BROKEN_XML = "<testsuite><testcase"
GAP_OPENING = "this command produces no report the factory can read (reporter: "
GAP_ENDING = "and set run.reporter and run.report_path in qa-factory/config.json so it is read every time."
GENERIC_CURE = "Make the command write a JUnit XML or TRX report"
INFERRED_GAP = ("the report format `junit-xml` was inferred from the cure row `karma` and reading it found no tests: "
                "set run.reporter in qa-factory/config.json to the format this command writes")


def set_run(**run) -> None:
    cfg_path = ROOT / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["run"] = run
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")


@contextlib.contextmanager
def cure_table(doc):
    """report_cures reads THIS table while the block runs: a dict (written as JSON), None (no such file) or a string
    (written as it is, for a file that is not JSON). The same patch point the rehearsal tests use (`cures_path`)."""
    path = ROOT / "cures-patched.json"
    if doc is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    original = RUN.report_cures.cures_path
    RUN.report_cures.cures_path = lambda: path
    try:
        yield
    finally:
        RUN.report_cures.cures_path = original


def shipped_table() -> dict:
    return json.loads(RUN.report_cures.cures_path().read_text(encoding="utf-8"))


def untyped_run(label: str, report=None, note: str = "") -> dict:
    """An untyped run (`--task/--label -- <command>`, so inference is the only chooser) of a command that writes
    `report` to out/r.xml (the file run.report_path names), or writes nothing; `note` is words in its argv, the
    way a real command carries `ng e2e` or `jest`."""
    tail = ["--note", note] if note else []
    if report is None:
        (ROOT / "fake_nothing.py").write_text(FAKE_NOTHING, encoding="utf-8")
        cmd = [PY, "fake_nothing.py", *tail]
    else:
        (ROOT / "src_report.xml").write_text(report, encoding="utf-8")
        cmd = [PY, "fake_report.py", "out/r.xml", "src_report.xml", *tail]
    (ROOT / "out" / "r.xml").unlink(missing_ok=True)
    return answer(call("--task", TASK, "--label", label, "--", *cmd)[1])


def choice_table() -> None:
    """K-P1: the adversarial table of E-B-report-3, and the order of the steps (E-B-report-2, -7)."""
    for argv, expected, why in (
            (["npx", "jest", "packages/pytest-bridge"], ("pytest", ""), "today's quirk, kept verbatim: `pytest` is the first entry"),
            (["dotnet", "test"], ("junit-xml", ""), "command_formats before the rows: never the dotnet row's trx"),
            (["vstest.console.exe", "x.dll", "/logger:junit"], ("junit-xml", ""), "via the word `junit`, step 3"),
            (["ng", "e2e"], ("junit-xml", "karma"), "only the karma row names `ng e2e`: step 4, the row is named"),
            (["make", "test"], ("none", ""), "no entry, no row"),
            (["poetry", "run", "pytest", "web/karma/tests"], ("pytest", ""), "a pytest command whose path says karma"),
            (["dotnet", "test", "--logger", "trx;LogFileName=r.trx"], ("trx", ""), "the trx entry comes before junit-xml"),
            (["vstest.console.exe", "x.dll"], ("trx", "dotnet"), "no format word: the dotnet row writes trx"),
            (["npx", "vitest", "run"], ("junit-xml", "vitest"), "a runner only a row knows"),
            (["npx", "playwright", "test"], ("junit-xml", "playwright"), "a runner only a row knows")):
        check_eq(f"K-P1: {' '.join(argv)} -> {expected} ({why})", RUN.reporter_choice(argv, {}, ""), expected)
    # amendment 6 (critic t-567): the pytest path is decided by is_pytest_command, never by data
    for argv in (["py.test", "tests/karma"], ["python", "-m", "py.test", "tests/jest_x"],
                 ["py.test", "--junitxml=r.xml"], ["py.test", "-q"]):
        check_eq(f"amendment 6: {' '.join(argv)} is pytest, whatever words its path carries",
                 RUN.reporter_choice(argv, {}, ""), ("pytest", ""))
    reordered = shipped_table()
    reordered["command_formats"] = list(reversed(reordered["command_formats"]))
    with cure_table(reordered):
        check_eq("amendment 6: a table with junit-xml first still leaves `pytest --junitxml=r.xml` pytest",
                 RUN.reporter_choice(["pytest", "--junitxml=r.xml"], {}, ""), ("pytest", ""))
        check_eq("... and a command that is not pytest follows the reordered table (the control: the table is read)",
                 RUN.reporter_choice(["npx", "jest", "packages/pytest-bridge"], {}, ""), ("junit-xml", ""))
    pytest_row = shipped_table()
    next(r for r in pytest_row["rows"] if r["id"] == "dotnet")["reporter_kind"] = "pytest"
    with cure_table(pytest_row):
        check_eq("a row saying `pytest` cannot switch the pytest path on for a command that is not pytest: "
                 "the row is ignored, nothing is inferred", RUN.reporter_choice(["vstest.console.exe", "x.dll"], {}, ""),
                 ("none", ""))
    check_eq("K-P1: resolve_reporter is the first of the pair", RUN.resolve_reporter(["ng", "e2e"], {}, ""), "junit-xml")
    # E-B-report-2: a declared reporter is never overridden, whatever the command says
    check_eq("E-B-report-2: an explicit reporter wins over a command only a row knows",
             RUN.reporter_choice(["ng", "e2e"], {"run": {"reporter": "junit-xml"}}, "trx"), ("trx", ""))
    check_eq("E-B-report-2: run.reporter wins over the rows, and nothing is inferred",
             RUN.reporter_choice(["ng", "e2e"], {"run": {"reporter": "trx"}}, ""), ("trx", ""))
    check_eq("E-B-report-2: a run.reporter outside the vocabulary is not a declaration: inference goes on",
             RUN.reporter_choice(["ng", "e2e"], {"run": {"reporter": "junit"}}, ""), ("junit-xml", "karma"))


def tables_of_other_shapes() -> None:
    """E-B-report-6 (TEMPORAL), both worlds, and the data shapes `command_formats` can arrive in."""
    old = shipped_table()
    check("the shipped table carries command_formats, in the order that matters",
          [e["kind"] for e in old["command_formats"]] == ["pytest", "trx", "junit-xml"], str(old.get("command_formats")))
    del old["command_formats"]
    with cure_table(old):
        for argv, expected, why in ((["dotnet", "test"], ("trx", "dotnet"), "step 3 contributes nothing: the row decides"),
                                    (["ng", "e2e"], ("junit-xml", "karma"), "step 4 still runs"),
                                    (["make", "test"], ("none", ""), "step 5 still runs")):
            check_eq(f"E-B-report-6, a table without the key: {' '.join(argv)} -> {expected} ({why})",
                     RUN.reporter_choice(argv, {}, ""), expected)
        for argv in (["pytest", "-q"], ["python", "-m", "pytest"], ["poetry", "run", "pytest"], ["py.test"]):
            check_eq(f"E-B-report-6, a table without the key: {' '.join(argv)} is still pytest (the gate is the predicate)",
                     RUN.reporter_choice(argv, {}, ""), ("pytest", ""))
        check_eq("E-B-report-6, a table without the key: run.reporter still wins",
                 RUN.reporter_choice(["make", "test"], {"run": {"reporter": "trx"}}, ""), ("trx", ""))
    for label, value in (("not a list", {"kind": "pytest"}), ("a list of non-entries", ["pytest", 3, None]),
                         ("an entry holding the empty word, which is in every command", [{"kind": "trx", "contains": [""]}]),
                         ("an entry of a kind nobody reads", [{"kind": "tap", "contains": ["make"]}])):
        broken = shipped_table()
        broken["command_formats"] = value
        with cure_table(broken):
            check_eq(f"a command_formats that is {label} contributes nothing and does not raise",
                     RUN.reporter_choice(["make", "test"], {}, ""), ("none", ""))
    # an unreadable table: the pytest gate decides, every other command says none
    for label, doc in (("the file is missing", None), ("the file is not JSON", "{ not json"),
                       ("the file has no rows list", {"command_formats": []})):
        with cure_table(doc):
            check_eq(f"E-B-report-6, unreadable ({label}): a pytest command is pytest",
                     RUN.reporter_choice(["poetry", "run", "pytest"], {}, ""), ("pytest", ""))
            check_eq(f"E-B-report-6, unreadable ({label}): `py.test`, which is_pytest_command knows, is pytest",
                     RUN.reporter_choice(["py.test", "-q"], {}, ""), ("pytest", ""))
            check_eq(f"E-B-report-6, unreadable ({label}): any other command is none, inferred from nothing",
                     (RUN.reporter_choice(["dotnet", "test"], {}, ""), RUN.reporter_choice(["ng", "e2e"], {}, "")),
                     (("none", ""), ("none", "")))
            check_eq(f"E-B-report-6, unreadable ({label}): a declaration still wins",
                     RUN.reporter_choice(["dotnet", "test"], {"run": {"reporter": "trx"}}, ""), ("trx", ""))


def inferred_runs() -> None:
    """K-P2 (B5b), E-B-report-1 and -5: whole runs through run_suite.main()."""
    (ROOT / "fake_report.py").write_text(FAKE_REPORT, encoding="utf-8")
    set_run(report_path="out/r.xml")
    zero = untyped_run("inf-zero", ZERO_TESTS, "ng e2e")
    check_eq("K-P2: an inferred format that reads zero tests, the summary names its row",
             (zero.get("reporter"), zero.get("reporter_inferred_from")), ("junit-xml", "karma"))
    check_eq("K-P2: ... and says what it guessed and the door (set run.reporter)", zero.get("parse_gap"), INFERRED_GAP)
    check_eq("K-P2: ... the status logic is untouched: zero tests is not_executed, never passed",
             zero.get("execution_status"), "not_executed")
    check_in("K-P2: ... and the gap is said on stderr like every RUN REPORT GAP", "RUN REPORT GAP: " + INFERRED_GAP, LAST_ERR)
    broken = untyped_run("inf-raise", BROKEN_XML, "ng e2e")
    check("K-P2: an inferred format that raises on its report: report_error is set",
          str(broken.get("report_error", "")).startswith("ParseError"), str(broken.get("report_error")))
    check_eq("K-P2: ... and the same gap is added", broken.get("parse_gap"), INFERRED_GAP)
    check_eq("K-P2: ... a misread is never passed", broken.get("execution_status") in ("passed", "failed"), False)
    green = untyped_run("inf-green", ONE_GREEN, "ng e2e")
    check_eq("an inferred format that reads its tests: named, passed, and no gap",
             (green.get("reporter_inferred_from"), green.get("execution_status"), "parse_gap" in green),
             ("karma", "passed", False))
    # a parse that FOUND tests and then failed on something else is not a misread (critic t-567, fix 4)
    import types
    real_hashlib = RUN.hashlib
    RUN.hashlib = types.SimpleNamespace(sha256=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("after the parse")))
    try:
        late = untyped_run("inf-late", ONE_GREEN, "ng e2e")
    finally:
        RUN.hashlib = real_hashlib
    check_eq("fix 4: a parse with tests > 0 and a later exception says the exception, and no 'found no tests' gap",
             (late.get("report_error"), (late.get("totals") or {}).get("tests"), "parse_gap" in late),
             ("RuntimeError: after the parse", 1, False))
    set_run(report_path="out/r.xml", reporter="junit-xml")
    declared = untyped_run("dec-zero", ZERO_TESTS, "ng e2e")
    check_eq("E-B-report-2: a declared reporter that reads zero tests is not an inference: no row named, no B5b gap",
             ("reporter_inferred_from" in declared, "parse_gap" in declared, declared.get("execution_status")),
             (False, False, "not_executed"))
    set_run(report_path="out/r.xml")
    listed = untyped_run("fmt-zero", ZERO_TESTS, "ng test")
    check_eq("a command_formats hit (`ng test`) is today's reading, not an inference: no row named, no B5b gap",
             (listed.get("reporter"), "reporter_inferred_from" in listed, "parse_gap" in listed),
             ("junit-xml", False, False))
    # E-B-report-6, a whole run on a table without the key: nothing about the table is reported as an error
    old = shipped_table()
    del old["command_formats"]
    with cure_table(old):
        old_run = untyped_run("old-table", ONE_GREEN, "ng e2e")
    check_eq("E-B-report-6: a run on a table without the key is read through the row, with no error about the table",
             (old_run.get("reporter_inferred_from"), old_run.get("execution_status"),
              [k for k in old_run if "error" in k]), ("karma", "passed", []))


def gap_words() -> None:
    """K-P3 (B6): the words of a run that left no report come from the command's cure row; E-B-report-5, the opening."""
    set_run(report_path="out/never-written.xml")
    row = untyped_run("gap-row", None, "ng e2e")
    karma = next(r for r in shipped_table()["rows"] if r["id"] == "karma")["words"]
    gap = row.get("parse_gap", "")
    check("E-B-report-5: the opening phrase is kept, with the reporter",
          gap.startswith(GAP_OPENING + "junit-xml). "), gap[:90])
    check_in("K-P3: the cure is the command's own row's words", karma + ", " + GAP_ENDING, gap)
    check("K-P3: and the ending closes the sentence", gap.endswith(GAP_ENDING), gap[-80:])
    check_in("the not_executed sentence stays", "A run with no report is recorded as not_executed however green its log is", gap)
    check_eq("E-B-report-5: the gap's presence is still the summary's doubt: no report was read, the status is not_executed",
             ("no_junitxml" in row, row.get("execution_status")), (True, "not_executed"))
    check_in("RUN REPORT GAP stays", "RUN REPORT GAP: " + GAP_OPENING, LAST_ERR)
    check("an inference that found no report to read says the missing report, not a misread",
          "was inferred" not in gap, gap)
    # the words come from the TABLE: change the row's words and the gap changes with it
    table = shipped_table()
    next(r for r in table["rows"] if r["id"] == "karma")["words"] = "karma: write the junit file somewhere the factory looks."
    with cure_table(table):
        custom = untyped_run("gap-custom", None, "ng e2e").get("parse_gap", "")
    check_in("K-P3: the table's words, nothing hard-coded, and a trailing full stop does not double",
             "karma: write the junit file somewhere the factory looks, " + GAP_ENDING, custom)
    generic = untyped_run("gap-generic", None).get("parse_gap", "")
    check_in("K-P3: no row names the command: the generic sentence", GENERIC_CURE + ", " + GAP_ENDING, generic)
    check_in("K-P3: ... opened by the same phrase, reporter none", GAP_OPENING + "none). ", generic)
    check("K-P3: and the old hard-coded words of three frameworks are gone",
          not any(word in generic + gap for word in ("LogFilePath", "jest-junit")), generic)
    # the cure words are decoration: an unreadable table gives the generic sentence and no error in the summary
    with cure_table(None):
        lost = untyped_run("gap-lost", None, "ng e2e")
    check_eq("E-B-report-6: an unreadable table: reporter none, the generic words, no report_error",
             (lost.get("reporter"), lost.get("parse_gap", "").endswith(GENERIC_CURE + ", " + GAP_ENDING),
              "report_error" in lost), ("none", True, False))


JOIN = " › "


def _row(classname: str, name: str, status: str = "passed", reason: str = "") -> dict:
    return {"test_id": f"{classname}::{name}", "status": status, "reason": reason}


def _block(rows: list, **contract) -> dict:
    """The run block of ONE instance whose contract has a `file` (a selection built from a file), over the report `rows`."""
    import run_suite
    base = {"report_test_id": "tests/cart.spec.ts::g" + JOIN + "adds one", "file": "tests/cart.spec.ts", "parameters": {},
            "classname_match": "file_suffix"}
    request = {"purpose": "initial", "selected_instance_ids": ["adds one"], "instance_contracts": {"adds one": {**base, **contract}},
               "runtime_provenance": {}, "execution": {}, "command": {}}
    return run_suite.build_run_block(request, {"results": rows, "execution_status": "passed"}, "job-1")


def ep1_37_file_selection_table() -> None:
    """EP1-37 p. 5, 6 (B-1, B-5): a contract with a `file` is matched by the ONE matcher (classname from the testDir, with `\\` on
    Windows, a name joined by the runner's join) and judged by the table over ALL its rows; an id that is not in the report is
    `not_run` with a CODE (`id_not_in_report`), never an error and never a pass. A contract without a `file` keeps its old text."""
    import red_sandbox
    name = "g" + JOIN + "adds one"
    one = lambda rows, **c: _block(rows, **c)["results"][0]    # noqa: E731
    got = one([_row("cart.spec.ts", name)])
    check_eq("testDir-relative classname: matched, passed", (got["status"], got["report_matched"]), ("passed", True))
    check_eq("Windows classname with a backslash: matched", one([_row("sub\\cart.spec.ts", name)], file="sub/cart.spec.ts")["status"], "passed")
    check_eq("a segment boundary: a neighbour's file is NOT this test",
             one([_row("cart.spec.ts", name)], file="tests/mycart.spec.ts")["reason_code"], "id_not_in_report")
    gone = one([_row("cart.spec.ts", "g" + JOIN + "adds on")])
    check_eq("an id not in the report: not_run, matched False, a code", (gone["status"], gone["report_matched"], gone["reason_code"]),
             ("not_run", False, "id_not_in_report"))
    check_in("and the nearest name when it is close", "nearest: cart.spec.ts::g" + JOIN + "adds on", gone["reason"])
    check_eq("two projects, a green and a red: failed (one green never closes a red)",
             one([_row("cart.spec.ts", name), _row("cart.spec.ts", name, "failed", "boom")])["status"], "failed")
    check_in("a failed row's name and reason", "boom", one([_row("cart.spec.ts", name, "failed", "boom")] * 2)["reason"])
    check_eq("an error and no failure: error", one([_row("cart.spec.ts", name), _row("cart.spec.ts", name, "error", "x")])["status"], "error")
    check_eq("all skipped", one([_row("cart.spec.ts", name, "skipped")] * 2)["status"], "skipped")
    mixed = one([_row("cart.spec.ts", name), _row("cart.spec.ts", name, "skipped")])
    check_eq("passed and skipped, no red: skipped with the count", (mixed["status"], mixed["reason"].startswith("1 of 2 rows skipped")), ("skipped", True))
    check_eq("rows of different files: ambiguous, not_run", one([_row("cart.spec.ts", name), _row("tests/cart.spec.ts", name)])["reason"],
             "report identity is ambiguous; multiple rows matched")
    # a pattern (a loop, an `each`): every row it fits, none is a code
    pattern = {"report_match": {"pattern": "g" + JOIN + "adds [a-z]+"}, "report_test_id": "tests/cart.spec.ts::g" + JOIN + "adds [${p}]"}
    rows = [_row("cart.spec.ts", "g" + JOIN + "adds a"), _row("cart.spec.ts", "g" + JOIN + "adds b", "failed", "red b")]
    check_eq("a pattern judges every row it fits", one(rows, **pattern)["status"], "failed")
    check_eq("a pattern that fits no row: id_not_in_report, never a green", one([_row("cart.spec.ts", "other")], **pattern)["reason_code"], "id_not_in_report")
    # two selected tests in two files that share a basename: the same row is nobody's
    request = {"purpose": "initial", "selected_instance_ids": ["a", "b"], "runtime_provenance": {}, "execution": {}, "command": {},
               "instance_contracts": {"a": {"file": "tests/a/x.spec.ts", "classname_match": "file_suffix", "report_test_id": "tests/a/x.spec.ts::t"},
                                      "b": {"file": "tests/b/x.spec.ts", "classname_match": "file_suffix", "report_test_id": "tests/b/x.spec.ts::t"}}}
    import run_suite
    both = run_suite.build_run_block(request, {"results": [_row("x.spec.ts", "t")], "execution_status": "passed"}, "j")["results"]
    check_eq("one row two files claim: not_run for both, not a green for either", [r["status"] for r in both], ["not_run", "not_run"])
    # E-1 (t-565): two instances of ONE file that claim one row: nobody's either (claims are keyed by instance, not by file)
    def same_file(a: dict, b: dict, rows: list) -> list:
        base = {"file": "tests/a.spec.ts", "classname_match": "file_suffix"}
        req = {"purpose": "initial", "selected_instance_ids": ["A", "B"], "runtime_provenance": {}, "execution": {}, "command": {},
               "instance_contracts": {"A": {**base, **a}, "B": {**base, **b}}}
        return run_suite.build_run_block(req, {"results": rows, "execution_status": "passed"}, "j")["results"]
    two_patterns = same_file({"report_match": {"pattern": "TC_1 .+"}, "report_test_id": "tests/a.spec.ts::TC_1 .+"},
                             {"report_match": {"pattern": "TC_1 fast .+"}, "report_test_id": "tests/a.spec.ts::TC_1 fast .+"},
                             [_row("a.spec.ts", "TC_1 fast one")])
    check_eq("E-1: two patterns of one file over one row: not_run for both", [r["status"] for r in two_patterns], ["not_run", "not_run"])
    pat_lit = same_file({"report_match": {"pattern": "TC_1 .+"}, "report_test_id": "tests/a.spec.ts::TC_1 .+"},
                        {"report_test_id": "tests/a.spec.ts::TC_1 special"}, [_row("a.spec.ts", "TC_1 special")])
    check_eq("E-1: a pattern and a literal of one file over the literal's row: not_run for both",
             [r["status"] for r in pat_lit], ["not_run", "not_run"])
    # a contract with NO file keeps the old text byte for byte
    old =_block([_row("cart.spec.ts", name)], file="", classname_match="")["results"][0]
    check_eq("no file: the old reading (exact id)", (old["status"], old["reason"]), ("not_run", "report row missing"))
    check("no file: no reason_code appears", "reason_code" not in old)
    check_eq("the statuses of the reporter are the five they were", __import__("reporters").STATUSES, ("passed", "failed", "error", "skipped", "not_run"))
    check("AR-13: the block and bind_row call the one matcher",
          "selection_rows" in Path(red_sandbox.__file__).read_text(encoding="utf-8").split("def bind_row")[1].split("def _frame_grammar")[0]
          and "selection_rows" in Path(__import__("run_suite").__file__).read_text(encoding="utf-8").split("def build_run_block")[1][:3000])
    # nearest: AT and beyond the ratio
    contract = {"report_test_id": "f::" + "a" * 10}
    check_eq("nearest: a ratio under 0.6 is no hint", red_sandbox.nearest_row([_row("f", "a" * 4 + "b" * 6)], contract), None)
    check_eq("nearest: a ratio over 0.6 is", red_sandbox.nearest_row([_row("f", "a" * 8 + "b" * 2)], contract), "f::" + "a" * 8 + "b" * 2)
    # bind_row, the probe's reader of the same contract
    row, note = red_sandbox.bind_row({"instance_id": "adds one"}, {"adds one": {"file": "tests/cart.spec.ts", "classname_match": "file_suffix",
                                      "report_test_id": "tests/cart.spec.ts::" + name}}, [_row("cart.spec.ts", name)], "junit-xml")
    check_eq("bind_row binds the testDir-relative row", (row is not None, note), (True, ""))
    row, note = red_sandbox.bind_row({"instance_id": "adds one"}, {"adds one": {"file": "tests/cart.spec.ts", "classname_match": "file_suffix",
                                      "report_test_id": "tests/cart.spec.ts::" + name}}, [_row("cart.spec.ts", "nope")], "junit-xml")
    check_eq("bind_row: no row keeps its text", row is None and "no row of the junit-xml report" in note, True)


def main() -> None:
    global ROOT
    ROOT = temp_project("qa-run-suite-reports-")
    use_project(ROOT)
    try:
        tmp = ROOT / "reports"
        tmp.mkdir()
        goldens(tmp)
        intended_differences(tmp)
        totals_match_rows(tmp)
        keep_old_text(tmp)
        caps(tmp)
        detail_cases()
        end_to_end()
        choice_table()
        tables_of_other_shapes()
        inferred_runs()
        gap_words()
        ep1_37_file_selection_table()
    finally:
        cleanup(ROOT)
    finish("test_run_suite_reports")


if __name__ == "__main__":
    main()
