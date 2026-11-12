"""reporters.py — the one reader of a test run's machine-readable report.

Four private parsers read report rows before this module (two in run_suite, one in red_sandbox,
one in probe_by_code) and only one of them knew TRX, the .NET format. (`{report_path}` is bound
inside its token at each site, not here: the one-token rule is upstream's, pinned by
test_onboarding_probe.py.) The fixtures below are shaped like what `dotnet test --logger trx`
and pytest's `--junitxml` really write, and `test_id` is pinned against what run_suite's own
parsers produce today: run blocks join the manifest on it, so it is a contract, not a detail.
"""
import ast
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

import reporters as R  # noqa: E402
import run_suite as RUN  # noqa: E402

TRX_NS = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"
CLONE_WIN = "C:\\clone"
TEST_FILE = "backend/Tests/FeedbackTests.cs"


def trx(results: str, definitions: str = "", ns: bool = True) -> str:
    head = f' xmlns="{TRX_NS}"' if ns else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<TestRun id="7c1d" name="ci@build-host"{head}>\n'
            f'  <Results>\n{results}\n  </Results>\n'
            f'  <TestDefinitions>\n{definitions}\n  </TestDefinitions>\n'
            '  <ResultSummary outcome="Failed"><Counters total="2" executed="2" passed="1" '
            'failed="1" error="0" notExecuted="0" inconclusive="0"/></ResultSummary>\n'
            '</TestRun>\n')


def definition(test_id: str, class_name: str, name: str) -> str:
    return (f'    <UnitTest name="{name}" id="{test_id}"><Execution id="e-{test_id}"/>'
            f'<TestMethod codeBase="C:\\clone\\backend\\Tests\\bin\\Debug\\net8.0\\Tests.dll" '
            f'adapterTypeName="executor://xunit/VsTestRunner2/netcoreapp" className="{class_name}" '
            f'name="{name}"/></UnitTest>')


FRAME_CLONE = ("   at Backend.Tests.FeedbackTests.Rejects_empty() in "
               "C:\\clone\\backend\\Tests\\FeedbackTests.cs:line 42")


def failed_result(test_id: str, test_name: str, message: str, stack: str, outcome: str = "Failed") -> str:
    return (f'    <UnitTestResult executionId="e-{test_id}" testId="{test_id}" testName="{test_name}" '
            f'computerName="build-host" duration="00:00:00.0310000" outcome="{outcome}">'
            f'<Output><ErrorInfo><Message>{message}</Message><StackTrace>{stack}</StackTrace>'
            '</ErrorInfo></Output></UnitTestResult>')


def passed_result(test_id: str, test_name: str, outcome: str = "Passed") -> str:
    attr = f' outcome="{outcome}"' if outcome else ""
    return (f'    <UnitTestResult executionId="e-{test_id}" testId="{test_id}" testName="{test_name}" '
            f'duration="00:00:00.0020000"{attr}/>')


MAIN_TRX = trx(
    passed_result("t-1", "Backend.Tests.FeedbackTests.Saves_comment") + "\n" +
    failed_result("t-2", "Backend.Tests.FeedbackTests.Rejects_empty",
                  "Assert.Equal() Failure\nExpected: 1\nActual:   0", FRAME_CLONE + "\n"
                  "   at System.RuntimeMethodHandle.InvokeMethod(Object target, Void** arguments)"),
    definition("t-1", "Backend.Tests.FeedbackTests", "Saves_comment") + "\n" +
    definition("t-2", "Backend.Tests.FeedbackTests", "Rejects_empty"))


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


JUNIT ='''<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="2" skipped="1" tests="5" time="0.31">
<testcase classname="tests.test_cart" name="test_total" time="0.01"/>
<testcase classname="tests.test_cart" name="test_discount[10-percent]" time="0.02">
<failure message="AssertionError: wrong total&#10;assert 90 == 91">def test_discount():
&gt;       assert total(100, 10) == 91, "wrong total"
E       AssertionError: wrong total

tests/test_cart.py:12: AssertionError</failure></testcase>
<testcase classname="tests.test_cart" name="test_fixture_missing" time="0.00">
<error message="fixture 'db' not found">E       fixture 'db' not found</error></testcase>
<testcase classname="tests.test_cart" name="test_both" time="0.00">
<failure message="first">tests/test_cart.py:20: AssertionError</failure>
<error message="teardown broke">tests/conftest.py:5: RuntimeError</error></testcase>
<testcase classname="tests.test_cart" name="test_skip" time="0.00">
<skipped type="pytest.skip" message="needs the stand">tests/test_cart.py:30: needs the stand</skipped></testcase>
</testsuite></testsuites>
'''


def junit(root: Path) -> None:
    path = write(root, "report.junit.xml", JUNIT)
    for reporter in ("pytest", "junit-xml"):
        rows = R.read_rows(path, reporter)
        check_eq(f"{reporter}: five rows in document order", [r["test_id"] for r in rows],
                 ["tests.test_cart::test_total", "tests.test_cart::test_discount[10-percent]",
                  "tests.test_cart::test_fixture_missing", "tests.test_cart::test_both",
                  "tests.test_cart::test_skip"])
        check_eq(f"{reporter}: statuses", [r["status"] for r in rows],
                 ["passed", "failed", "error", "error", "skipped"])
    rows = R.read_rows(path, "pytest")
    passed, failed, errored, both, skipped = rows
    check_eq("passed: no problems", passed["problems"], [])
    check_eq("failure: one problem with kind, message and text", [p["kind"] for p in failed["problems"]], ["failure"])
    check_eq("failure: message is the attribute", failed["problems"][0]["message"],
             "AssertionError: wrong total\nassert 90 == 91")
    check("failure: text is the node body", failed["problems"][0]["text"].endswith("tests/test_cart.py:12: AssertionError"))
    check_eq("error: its own kind", [p["kind"] for p in errored["problems"]], ["error"])
    check_eq("error: message", errored["problems"][0]["message"], "fixture 'db' not found")
    check_eq("failure + error in one testcase: both kept, in document order",
             [(p["kind"], p["message"]) for p in both["problems"]],
             [("failure", "first"), ("error", "teardown broke")])
    check_eq("failure + error: the row status is run_suite's (error wins)", both["status"], "error")
    check_eq("skipped: one problem of kind skipped carrying the reason",
             [(p["kind"], p["message"]) for p in skipped["problems"]], [("skipped", "needs the stand")])
    check_eq("skipped: its text is the node body", skipped["problems"][0]["text"],
             "tests/test_cart.py:30: needs the stand")
    check("a JUnit row carries no TRX-only keys", "class_name" not in passed and "method_name" not in passed)
    legacy = [(r["test_id"], r["status"]) for r in RUN.parse_junitxml(path)["results"]]
    check_eq("test_id and status equal run_suite.parse_junitxml on the same file",
             [(r["test_id"], r["status"]) for r in rows], legacy)

    # Q1: error BEFORE failure in the document. The status is run_suite's (error outranks
    # failure whatever the order); problems keep the document order, so problems[0] is the error.
    flipped = write(root, "flipped.xml", '<testsuite><testcase classname="a" name="t">'
                    '<error message="setup broke">e-text</error><failure message="then asserted">f-text</failure>'
                    '</testcase></testsuite>')
    flipped_row = R.read_rows(flipped, "pytest")[0]
    check_eq("error + failure: status equals run_suite's", flipped_row["status"],
             RUN.parse_junitxml(flipped)["results"][0]["status"])
    check_eq("error + failure: status is error", flipped_row["status"], "error")
    check_eq("error + failure: problems[0] is the first element of the document, then the second",
             [(p["kind"], p["message"]) for p in flipped_row["problems"]],
             [("error", "setup broke"), ("failure", "then asserted")])

    # Q2: what run_suite derives for a skipped row must be reproducible from the row alone:
    # reason = skipped message[:160] or "(no reason)"; skip_reasons counts reason[:80].
    long_reason = "needs the stand " * 20
    skips = write(root, "skips.xml", f'''<testsuite>
<testcase classname="s" name="with_reason"><skipped message="needs the stand"/></testcase>
<testcase classname="s" name="no_reason"><skipped/></testcase>
<testcase classname="s" name="empty_message"><skipped message="">body only</skipped></testcase>
<testcase classname="s" name="blank_everything"><skipped message="  ">   </skipped></testcase>
<testcase classname="s" name="long"><skipped message="{long_reason}"/></testcase>
<testcase classname="s" name="fail_then_skip"><failure message="boom">x</failure><skipped message="later"/></testcase>
</testsuite>''')
    skip_rows = R.read_rows(skips, "junit-xml")
    check_eq("every skipped JUnit row is skipped", {r["status"] for r in skip_rows}, {"skipped"})
    check_eq("a skipped row with no reason has an empty problems list", skip_rows[1]["problems"], [])
    check_eq("a blank reason and blank body is no reason either", skip_rows[3]["problems"], [])
    check_eq("a skipped element with only a body keeps the body, message empty",
             [(p["kind"], p["message"], p["text"]) for p in skip_rows[2]["problems"]], [("skipped", "", "body only")])
    check_eq("a skipped element after a failure: both problems, document order",
             [p["kind"] for p in skip_rows[5]["problems"]], ["failure", "skipped"])

    def reason_of(row):
        for problem in row["problems"]:
            if problem["kind"] == "skipped":
                return problem["message"][:160] or "(no reason)"
        return "(no reason)"

    legacy_skips = RUN.parse_junitxml(skips)
    check_eq("run_suite's reason for every skipped row is reproduced from the row",
             [reason_of(r) for r in skip_rows], [r["reason"] for r in legacy_skips["results"]])
    from collections import Counter
    check_eq("run_suite's skip_reasons are reproduced from the rows",
             dict(Counter(reason_of(r)[:80] for r in skip_rows).most_common(12)), legacy_skips["skip_reasons"])
    nested = write(root, "nested.xml", '<testsuites><testsuite name="outer"><testsuite name="inner">'
                   '<testcase classname="a" name="t1"/></testsuite><testcase classname="a" name="t2"/>'
                   '</testsuite></testsuites>')
    check_eq("a testcase inside a nested suite is one row, not two",
             [r["test_id"] for r in R.read_rows(nested, "junit-xml")], ["a::t1", "a::t2"])
    single = write(root, "single.xml", '<testsuite name="s"><testcase classname="" name="bare"/></testsuite>')
    check_eq("a root <testsuite> and an empty classname give the bare name",
             [r["test_id"] for r in R.read_rows(single, "pytest")], ["bare"])
    empty = write(root, "empty.xml", '<testsuites><testsuite name="s" tests="0"/></testsuites>')
    check_eq("a report with no rows is []", R.read_rows(empty, "pytest"), [])
    dup = write(root, "dup.xml", '<testsuite><testcase classname="a" name="t"/><testcase classname="a" name="t">'
                '<failure message="x"/></testcase></testsuite>')
    check_eq("a duplicate test_id is not de-duplicated", [r["status"] for r in R.read_rows(dup, "pytest")],
             ["passed", "failed"])


def trx_rows(root: Path) -> None:
    path = write(root, "main.trx", MAIN_TRX)
    rows = R.read_rows(path, "trx")
    check_eq("TRX: a passed and a failed row, in document order",
             [(r["test_id"], r["status"]) for r in rows],
             [("Backend.Tests.FeedbackTests.Saves_comment", "passed"),
              ("Backend.Tests.FeedbackTests.Rejects_empty", "failed")])
    passed, failed = rows
    check_eq("TRX passed: no problems", passed["problems"], [])
    check_eq("TRX definitions give class_name and method_name",
             (failed["class_name"], failed["method_name"]), ("Backend.Tests.FeedbackTests", "Rejects_empty"))
    problem = failed["problems"][0]
    check_eq("TRX problem kind", problem["kind"], "failure")
    check_eq("TRX message is ErrorInfo/Message", problem["message"], "Assert.Equal() Failure\nExpected: 1\nActual:   0")
    check("TRX text is ErrorInfo/StackTrace", problem["text"].startswith("at Backend.Tests.FeedbackTests.Rejects_empty() in C:\\clone\\")
          and "InvokeMethod" in problem["text"])
    legacy = RUN.parse_trx(path)["results"]
    check_eq("TRX: test_id and status equal run_suite.parse_trx on the same file",
             [(r["test_id"], r["status"]) for r in rows], [(r["test_id"], r["status"]) for r in legacy])

    theory = write(root, "theory.trx", trx(
        "\n".join(passed_result(f"th-{i}", f"Backend.Tests.FeedbackTests.Rejects_blank(value: &quot;{v}&quot;)")
                  for i, v in enumerate(["", " ", "\\t"])),
        "\n".join(definition(f"th-{i}", "Backend.Tests.FeedbackTests", "Rejects_blank") for i in range(3))))
    theory_rows = R.read_rows(theory, "trx")
    check_eq("xUnit Theory: one row per result, each with its own testName",
             [r["test_id"] for r in theory_rows],
             ['Backend.Tests.FeedbackTests.Rejects_blank(value: "")',
              'Backend.Tests.FeedbackTests.Rejects_blank(value: " ")',
              'Backend.Tests.FeedbackTests.Rejects_blank(value: "\\t")'])
    check_eq("Theory rows share the method definition", {r["method_name"] for r in theory_rows}, {"Rejects_blank"})
    check_eq("Theory test_ids equal run_suite.parse_trx", [r["test_id"] for r in theory_rows],
             [r["test_id"] for r in RUN.parse_trx(theory)["results"]])

    inner = write(root, "inner.trx", trx(
        '    <UnitTestResult testId="o-1" testName="Backend.Tests.OrderedSuite" outcome="Failed">'
        '<Output><ErrorInfo><Message>One or more inner tests failed</Message></ErrorInfo></Output>'
        '<InnerResults>'
        + passed_result("o-1a", "Backend.Tests.OrderedSuite.Step1") +
        failed_result("o-1b", "Backend.Tests.OrderedSuite.Step2", "boom", FRAME_CLONE) +
        '</InnerResults></UnitTestResult>',
        definition("o-1", "Backend.Tests.OrderedSuite", "OrderedSuite")))
    inner_rows = R.read_rows(inner, "trx")
    check_eq("InnerResults: the parent and every inner UnitTestResult give a row",
             [(r["test_id"], r["status"]) for r in inner_rows],
             [("Backend.Tests.OrderedSuite", "failed"), ("Backend.Tests.OrderedSuite.Step1", "passed"),
              ("Backend.Tests.OrderedSuite.Step2", "failed")])
    check_eq("InnerResults: the parent's problem is its own ErrorInfo, not a child's",
             inner_rows[0]["problems"][0]["message"], "One or more inner tests failed")
    check_eq("InnerResults: an inner row without a definition has no class_name",
             "class_name" in inner_rows[1], False)

    orphan = write(root, "orphan.trx", trx(passed_result("zz-9", "Backend.Tests.Lonely.Runs"),
                                           definition("t-1", "Backend.Tests.Other", "Other")))
    orphan_rows = R.read_rows(orphan, "trx")
    check_eq("a result with no definition is still a row", [r["test_id"] for r in orphan_rows],
             ["Backend.Tests.Lonely.Runs"])
    check("and carries neither class_name nor method_name",
          "class_name" not in orphan_rows[0] and "method_name" not in orphan_rows[0])

    plain = write(root, "plain.trx", trx(passed_result("p-1", "Plain.Runs"), ns=False))
    check_eq("a TRX without the namespace is read the same", [r["test_id"] for r in R.read_rows(plain, "trx")],
             ["Plain.Runs"])
    check_eq("empty Results is []", R.read_rows(write(root, "none.trx", trx("")), "trx"), [])

    outcomes = write(root, "outcomes.trx", trx("\n".join([
        passed_result("a", "N.absent", outcome=""),
        passed_result("b", "N.notexec", outcome="NotExecuted"),
        passed_result("c", "N.inconclusive", outcome="Inconclusive"),
        passed_result("d", "N.skipped", outcome="Skipped"),
        failed_result("e", "N.timeout", "timed out", "", outcome="Timeout"),
        failed_result("f", "N.aborted", "run aborted", "", outcome="Aborted"),
        failed_result("g", "N.error", "setup threw", FRAME_CLONE, outcome="Error"),
        passed_result("h", "N.pending", outcome="Pending"),
        passed_result("i", "N.lower", outcome="passed"),
        failed_result("j", "N.skip_reason", "Skipped: needs the stand\nsecond line", "", outcome="NotExecuted"),
        failed_result("k", "N.inconclusive_reason", "Inconclusive: flaky stand", "", outcome="Inconclusive"),
        failed_result("l", "N.skip_empty", "", "", outcome="NotExecuted"),
        failed_result("m", "N.absent_with_info", "no verdict", "", outcome=""),
    ])))
    got = {r["test_id"]: r for r in R.read_rows(outcomes, "trx")}
    check_eq("an ABSENT outcome is not_run (FR-41), where parse_trx says passed", got["N.absent"]["status"], "not_run")
    check_eq("run_suite.parse_trx reads it through this reader now: not_run too",
             [r["status"] for r in RUN.parse_trx(outcomes)["results"]][0], "not_run")
    check_eq("NotExecuted is skipped", got["N.notexec"]["status"], "skipped")
    check_eq("Inconclusive is skipped", got["N.inconclusive"]["status"], "skipped")
    check_eq("Skipped is skipped", got["N.skipped"]["status"], "skipped")
    check_eq("Timeout is error", got["N.timeout"]["status"], "error")
    check_eq("Aborted is error", got["N.aborted"]["status"], "error")
    check_eq("Error is error", got["N.error"]["status"], "error")
    check_eq("an outcome outside the vocabulary is not_run, never a raw word", got["N.pending"]["status"], "not_run")
    check_eq("outcome case is ignored", got["N.lower"]["status"], "passed")
    check_eq("an error row keeps its ErrorInfo as a problem of kind error", got["N.timeout"]["problems"][0]["kind"], "error")
    check_eq("its empty stack is an empty text", got["N.timeout"]["problems"][0]["text"], "")
    check_eq("a not_run row has no problems", got["N.absent"]["problems"], [])
    check_eq("test_ids equal run_suite.parse_trx on every row",
             [r["test_id"] for r in R.read_rows(outcomes, "trx")],
             [r["test_id"] for r in RUN.parse_trx(outcomes)["results"]])
    # Q2: a skipped / not-executed TRX result carries its ErrorInfo/Message as a `skipped` problem.
    check_eq("skipped TRX row: one problem of kind skipped with the message",
             [(p["kind"], p["message"]) for p in got["N.skip_reason"]["problems"]],
             [("skipped", "Skipped: needs the stand\nsecond line")])
    check_eq("an Inconclusive row's reason is a skipped problem too",
             [p["kind"] for p in got["N.inconclusive_reason"]["problems"]], ["skipped"])
    check_eq("a skipped row with an empty ErrorInfo has an empty problems list", got["N.skip_empty"]["problems"], [])
    check_eq("a skipped row with no ErrorInfo at all has an empty problems list", got["N.notexec"]["problems"], [])
    check_eq("a not_run row has no problems even when it carries an ErrorInfo",
             got["N.absent_with_info"]["problems"], [])
    legacy_by_name = {r["test_id"]: r for r in RUN.parse_trx(outcomes)["results"]}
    for name in ("N.skip_reason", "N.inconclusive_reason", "N.skip_empty", "N.notexec"):
        problems = got[name]["problems"]
        derived = (problems[0]["message"].splitlines()[0][:160] if problems and problems[0]["message"] else "")
        check_eq(f"run_suite.parse_trx's reason for {name} is reproduced from the row",
                 derived, legacy_by_name[name]["reason"])
    check_eq("a result with no testName is '?' like parse_trx",
             [r["test_id"] for r in R.read_rows(write(root, "noname.trx", trx(
                 '    <UnitTestResult testId="q" outcome="Passed"/>')), "trx")], ["?"])


def dispatch_and_errors(root: Path) -> None:
    path = write(root, "x.xml", JUNIT)
    for name in ("none", "nunit", "", "TRX"):
        try:
            R.read_rows(path, name)
            check(f"reporter {name!r} is refused", False)
        except ValueError as exc:
            check(f"reporter {name!r} is refused naming it", repr(name) in str(exc), str(exc))
    # Dispatch is on the typed name, never on the root tag: a TRX read as junit-xml finds no testcase.
    trx_path = write(root, "y.trx", MAIN_TRX)
    check_eq("a TRX file read with the junit-xml reader yields nothing (no sniffing)",
             R.read_rows(trx_path, "junit-xml"), [])
    check_eq("a JUnit file read with the trx reader yields nothing (no sniffing)", R.read_rows(path, "trx"), [])
    bad = write(root, "bad.xml", "<testsuite><testcase")
    try:
        R.read_rows(bad, "pytest")
        check("malformed XML propagates", False)
    except ET.ParseError:
        check("malformed XML propagates the parser's error", True)
    try:
        R.read_rows(root / "absent.trx", "trx")
        check("a missing file propagates", False)
    except OSError:
        check("a missing file propagates the OS error", True)


def oracles_are_frozen() -> None:
    """The old private readers are gone; this file holds their answers as literals (OLD_*), and must
    not reach for them again: it imports neither red_sandbox nor window_record (read off its own
    source, by the AST, so this very check does not count as an import)."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    check("this file imports neither red_sandbox nor window_record",
          not ({"red_sandbox", "window_record"} & imported), str(sorted(imported)))
    sources = {name: (Path(R.__file__).parent / (name + ".py")).read_text(encoding="utf-8")
               for name in ("red_sandbox", "window_record")}
    for name, funcs in (("red_sandbox", ("_junit_rows", "_failure_detail", "_reason_text")),
                        ("window_record", ("_reason_text",))):
        for func in funcs:
            check(f"{name}.{func} is deleted (it had no caller but this file's oracles)",
                  f"def {func}(" not in sources[name])


JEST = ("Error: expect(received).toBe(expected)\n\n    Expected: 4\n    Received: 0\n\n"
        "      at Object.<anonymous> (/clone/tests/x.test.ts:5:20)\n"
        "      at node_modules/jest-circus/build/run.js:315:5")
JAVA = ("org.opentest4j.AssertionFailedError: expected: <4> but was: <0>\n"
        "\tat org.junit.jupiter.api.AssertionUtils.fail(AssertionUtils.java:55)\n"
        "\tat com.acme.CalcTest.adds(CalcTest.java:12)")
DOTNET_JUNIT = "Assert.Equal() Failure\n   at Backend.Tests.X.M() in C:\\clone\\backend\\Tests\\X.cs:line 42"


def unread_sites() -> None:
    """F2: only pytest's report has a site grammar this module reads. A `junit-xml` row of any other
    runner was sent to pytest's last-traceback rule: a Jest frame gave a garbage location with kind
    `exception`, Java JUnit and the .NET JUnit logger gave `{}` - and a probe on such a profile ended
    `survived` with no reason. It is a typed answer now, naming what is not read yet (B-337)."""
    def junit(text, status="failed", kind="failure"):
        return {"test_id": "x::t", "status": status, "problems": [{"kind": kind, "message": "m", "text": text}]}

    for label, text, runtime in (("a Jest-shaped frame", JEST, "npx"), ("a Java JUnit frame", JAVA, "mvn"),
                                 ("a .NET frame through the JUnit logger", DOTNET_JUNIT, "dotnet")):
        got = R.assertion_site(junit(text), "junit-xml", "/clone", "tests/x.test.ts",
                               pytest_command=False, runtime=runtime)
        check_eq(f"{label}: a typed unread site, not a location",
                 got, {"site_unread": f"junit-xml/{runtime}",
                       "reason": f"the assertion site of a junit-xml/{runtime} report is not read yet (B-337)"})
    got = R.assertion_site(junit(JAVA), "junit-xml", "/clone", "t", pytest_command=False)
    check_eq("no runtime hint: an unknown runtime, said so", got["site_unread"], "junit-xml/unknown runtime")
    check_eq("an error row is unread too",
             R.assertion_site(junit(JEST, "error", "error"), "junit-xml", "/c", "t", pytest_command=False,
                              runtime="npx")["site_unread"], "junit-xml/npx")
    for status in ("passed", "skipped", "not_run"):
        check_eq(f"a {status} row has no site to read, whatever the runner is",
                 R.assertion_site({"test_id": "x::t", "status": status, "problems": []}, "junit-xml", "/c", "t",
                                  pytest_command=False, runtime="npx"), {})
    # the invariant: pytest rows and TRX rows are what they were
    garbage = R.assertion_site(junit(JEST), "junit-xml", "/clone", "tests/x.test.ts")
    check_eq("a pytest command (the default) keeps the pytest rule - on a Jest frame that is the garbage "
             "the typed answer replaces for a runner that is not pytest", garbage["failure_kind"], "exception")
    check_eq("pytest's own grammar is untouched when the flag says so too",
             R.assertion_site(junit(PYTEST_TEXTS["assertion"]), "junit-xml", "/c", "tests/test_cart.py",
                              pytest_command=True, runtime="python"), _ASSERT_12)
    check_eq("the `pytest` reporter is never 'unread', whatever the flag says",
             R.assertion_site(junit(PYTEST_TEXTS["assertion"]), "pytest", "/c", "tests/test_cart.py",
                              pytest_command=False, runtime="make"), _ASSERT_12)
    check_eq("a TRX row is read by its own rule whatever the flag says",
             R.assertion_site(trx_row(FRAME_CLONE), "trx", CLONE_WIN, TEST_FILE, pytest_command=False,
                              runtime="dotnet"), {"location": "backend/Tests/FeedbackTests.cs:42",
                                                  "failure_kind": "assertion"})


def trx_row(stack: str, status: str = "failed", message: str = "Assert.Equal() Failure") -> dict:
    return {"test_id": "Backend.Tests.FeedbackTests.Rejects_empty", "status": status,
            "problems": [{"kind": "failure", "message": message, "text": stack}] if stack is not None else []}


def sites() -> None:
    def site(stack, status="failed", root=CLONE_WIN, test_file=TEST_FILE):
        return R.assertion_site(trx_row(stack, status), "trx", root, test_file)

    check_eq("a frame in the clone: clone-relative location, assertion", site(FRAME_CLONE),
             {"location": "backend/Tests/FeedbackTests.cs:42", "failure_kind": "assertion"})
    walk = ("   at Xunit.Assert.Equal[T](T expected, T actual)\r\n" + FRAME_CLONE + "\r\n"
            "   at System.RuntimeMethodHandle.InvokeMethod(Object target)")
    check_eq("frames without a file are skipped; CRLF is read",
             site(walk), {"location": "backend/Tests/FeedbackTests.cs:42", "failure_kind": "assertion"})
    product = ("   at Backend.Feedback.Service.Save() in C:\\clone\\backend\\src\\Service.cs:line 10\n" + FRAME_CLONE)
    check_eq("a product frame first: exception, and the location is the product frame",
             site(product), {"location": "backend/src/Service.cs:10", "failure_kind": "exception"})
    author = "   at Backend.Tests.FeedbackTests.Rejects_empty() in C:\\author\\backend\\Tests\\FeedbackTests.cs:line 42"
    got = site(author)
    check_eq("a frame in the author's tree keeps its path verbatim",
             got["location"], "C:\\author\\backend\\Tests\\FeedbackTests.cs:42")
    check("so it never equals a clone-relative expectation", got["location"] != "backend/Tests/FeedbackTests.cs:42")
    check_eq("and is never an assertion", got["failure_kind"], "exception")
    check_eq("a deterministic-build /_/ path is kept verbatim",
             site("   at Backend.Tests.X.M() in /_/src/x.cs:line 7", test_file="src/x.cs"),
             {"location": "/_/src/x.cs:7", "failure_kind": "exception"})
    posix = "   at Backend.Tests.FeedbackTests.Rejects_empty() in /work/clone/backend/Tests/FeedbackTests.cs:line 42"
    check_eq("a POSIX clone path is relativised", site(posix, root="/work/clone"),
             {"location": "backend/Tests/FeedbackTests.cs:42", "failure_kind": "assertion"})
    check_eq("a sibling directory with the same prefix is not inside the clone",
             site(posix.replace("/work/clone/", "/work/clone2/"), root="/work/clone")["location"],
             "/work/clone2/backend/Tests/FeedbackTests.cs:42")
    check_eq("a Path clone root works", site(posix, root=Path("/work/clone"))["failure_kind"], "assertion")
    check_eq("Windows drive letters compare case-insensitively",
             site(FRAME_CLONE.replace("C:\\clone", "c:\\CLONE"))["location"], "backend/Tests/FeedbackTests.cs:42")
    check_eq("a Windows-style test_file is normalised", site(FRAME_CLONE, test_file="backend\\Tests\\FeedbackTests.cs")
             ["failure_kind"], "assertion")
    # Q4: three kinds. assertion = failed + first located frame in the test file; exception =
    # failed + that frame elsewhere; error = the row's status is error (timeout, aborted, Error).
    check_eq("failed, first located frame in the test file: assertion", site(FRAME_CLONE)["failure_kind"], "assertion")
    check_eq("failed, first located frame in product code: exception", site(product)["failure_kind"], "exception")
    check_eq("an error row with a frame in the test file: error", site(FRAME_CLONE, status="error")["failure_kind"], "error")
    check_eq("an error row with a product frame first: error", site(product, status="error")["failure_kind"], "error")
    check_eq("an error row with no located frame is still {}", site("   at X.Y()", status="error"), {})
    skipped_row = {"status": "skipped", "problems": [{"kind": "skipped", "message": "m", "text": FRAME_CLONE}]}
    check_eq("a skipped row is never a failure site", R.assertion_site(skipped_row, "trx", CLONE_WIN, TEST_FILE), {})
    check_eq("a skipped JUnit row is never a failure site",
             R.assertion_site({"status": "skipped", "problems": [
                 {"kind": "skipped", "message": "m", "text": "tests/t.py:3: AssertionError"}]},
                 "pytest", "/c", "tests/t.py"), {})
    check_eq("a different test file is not an assertion",
             site(FRAME_CLONE, test_file="backend/Tests/OtherTests.cs")["failure_kind"], "exception")
    check_eq("no stack: {}", site(""), {})
    check_eq("no problems (a passed row): {}", site(None, status="passed"), {})
    check_eq("a stack with no located frame: {}", site("   at Xunit.Assert.Equal[T](T expected, T actual)"), {})
    check_eq("no clone root: nothing is stripped", site(FRAME_CLONE, root="")["location"],
             "C:\\clone\\backend\\Tests\\FeedbackTests.cs:42")
    try:
        R.assertion_site(trx_row(FRAME_CLONE), "none", CLONE_WIN, TEST_FILE)
        check("an unknown reporter is refused", False)
    except ValueError:
        check("an unknown reporter is refused", True)


# B-373 part (b): the frame grammars below are copies of the seed table's `frames` / `skip_frames`
# (t-464, with L1 for the TS skip list and L8 for the Vitest frame). The seed itself is data of
# part (c) in references/detectors.json; this file pins the READER, so it owns its own copies.
CS_FRAMES = [r"^\s*at\s+.+?\s+in\s+(?P<path>.+?):line\s+(?P<line>\d+)\s*$"]
CS_SKIP = [r"^\s*at\s+(?:Xunit|NUnit\.Framework|System|Microsoft)\."]
JAVA_FRAMES = [r"^\s*at\s+(?P<qual>[\w$.<>/]+)\((?P<path>[\w$]+\.java):(?P<line>\d+)\)"]
JAVA_SKIP = [r"^\s*at\s+(?:org\.junit|org\.opentest4j|org\.assertj|org\.hamcrest|java\.|jdk\.|sun\.|"
             r"org\.apache\.maven|org\.gradle)"]
TS_FRAMES = [r"^\s*at\s+(?:.*?\()?(?P<path>(?:[A-Za-z]:)?[^():\s][^():]*?):(?P<line>\d+):\d+\)?\s*$",
             "^\\s*\u276f\\s+(?P<path>(?:[A-Za-z]:)?[^():\\s][^():]*?):(?P<line>\\d+):\\d+\\s*$"]
TS_SKIP = [r"node_modules|node:internal|^\s*at\s+(?:new\s+)?Promise\b|\(<anonymous>\)\s*$|^\s*at\s+<anonymous>\s*$"]
JAVA_TEST = "src/test/java/com/acme/CalcTest.java"
JEST_TEST = "src/sum.test.ts"


def frame_sites(root: Path) -> None:
    """R11 / K9: the caller's frame grammar (B-373). `frames=None` is today's answer, byte for byte;
    with a grammar a failed row's first frame that is a PROJECT file is the site, and anything that
    cannot be resolved - a library-only stack, an empty one, a frame of another tree, a same-named
    file of another package - is the typed unread answer, never a location (so never `wrong_location`,
    which accuses the author)."""
    def row(text, status="failed", kind="failure"):
        return {"test_id": "x::t", "status": status, "problems": [{"kind": kind, "message": "m", "text": text}]}

    def read(text, frames, skip, test_file, *, root_dir="/clone", frame_path="path", status="failed",
             reporter="junit-xml", pytest_command=False, runtime="npx"):
        return R.assertion_site(row(text, status, "error" if status == "error" else "failure"), reporter, root_dir,
                                test_file, pytest_command=pytest_command, runtime=runtime, frames=frames,
                                skip_frames=skip, frame_path=frame_path)

    def unread(got, label, runtime="npx", reporter="junit-xml"):
        check_eq(f"{label}: the typed unread answer", got.get("site_unread"), f"{reporter}/{runtime}")
        check(f"{label}: no location, no kind", "location" not in got and "failure_kind" not in got, str(got))
        check(f"{label}: the reason says why", bool(got.get("reason")))

    # --- frames=None is today's output -----------------------------------------------------------
    for label, text, reporter, command in (("a Jest frame", JEST, "junit-xml", False),
                                           ("a pytest text", PYTEST_TEXTS["assertion"], "junit-xml", True),
                                           ("a pytest text, `pytest` reporter", PYTEST_TEXTS["assertion"], "pytest", True),
                                           ("a TRX stack", FRAME_CLONE, "trx", False)):
        plain = R.assertion_site(row(text), reporter, "/clone", JEST_TEST, pytest_command=command, runtime="npx")
        same = R.assertion_site(row(text), reporter, "/clone", JEST_TEST, pytest_command=command, runtime="npx",
                                frames=None, skip_frames=TS_SKIP, frame_path="basename")
        check_eq(f"{label}: frames=None gives today's answer whatever else is passed", same, plain)
        check("so it never carries a `frame` key", "frame" not in same)

    # --- Jest: the test frame RESOLVES (L1), library frames and node_modules do not -------------
    jest = ("Error: expect(received).toBe(expected)\n\n    Expected: 4\n    Received: 0\n\n"
            "      at Object.<anonymous> (/clone/src/sum.test.ts:11:20)\n"
            "      at Promise.then.completed (/clone/node_modules/jest-circus/build/utils.js:298:28)\n"
            "      at new Promise (<anonymous>)")
    got = read(jest, TS_FRAMES, TS_SKIP, JEST_TEST)
    check_eq("a Jest `at Object.<anonymous> (file:line:col)` frame resolves to the test file", got,
             {"location": "src/sum.test.ts:11", "failure_kind": "assertion",
              "frame": "      at Object.<anonymous> (/clone/src/sum.test.ts:11:20)"})
    lib_first = ("Error: boom\n      at Object.toBe (/clone/node_modules/expect/build/index.js:1:1)\n"
                 "      at node:internal/process/task_queues:95:5\n" + jest.split("\n\n", 2)[2])
    check_eq("a node_modules frame first is skipped, the test frame after it is the site",
             read(lib_first, TS_FRAMES, TS_SKIP, JEST_TEST)["location"], "src/sum.test.ts:11")
    only_lib = ("Error: boom\n      at Object.toBe (/clone/node_modules/expect/build/index.js:1:1)\n"
                "      at node:internal/process/task_queues:95:5\n      at new Promise (<anonymous>)")
    unread(read(only_lib, TS_FRAMES, TS_SKIP, JEST_TEST), "a trace with only node_modules and skipped frames")
    unread(read("", TS_FRAMES, TS_SKIP, JEST_TEST), "an empty trace")
    unread(read("Error: boom", TS_FRAMES, TS_SKIP, JEST_TEST), "a trace with no frame line at all")
    unread(R.assertion_site({"status": "failed", "problems": []}, "junit-xml", "/clone", JEST_TEST,
                            pytest_command=False, runtime="npx", frames=TS_FRAMES, skip_frames=TS_SKIP),
           "a failed row with no problem")
    check_eq("`skip_frames` ignored would take the node_modules frame: it is honoured",
             read(only_lib, TS_FRAMES, None, JEST_TEST)["location"], "node_modules/expect/build/index.js:1")
    check_eq("a frame in the clone that is not the test file: exception",
             read(jest.replace("src/sum.test.ts", "src/sum.ts"), TS_FRAMES, TS_SKIP, JEST_TEST),
             {"location": "src/sum.ts:11", "failure_kind": "exception",
              "frame": "      at Object.<anonymous> (/clone/src/sum.ts:11:20)"})
    check_eq("an error row is `error`, whatever the frame",
             read(jest, TS_FRAMES, TS_SKIP, JEST_TEST, status="error")["failure_kind"], "error")
    # U+276F is built by escape: only ASCII reaches a check name, and the console may be cp1252.
    vitest = " \u276f src/sum.test.ts:11:20\n \u276f runTest node_modules/@vitest/runner/dist/index.js:1:1"
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "sum.test.ts").write_text("// a test\n", encoding="utf-8")
    check_eq("a Vitest arrow frame (`path:line:col`), relative and existing, resolves",
             read(vitest, TS_FRAMES, TS_SKIP, JEST_TEST, root_dir=root)["location"], "src/sum.test.ts:11")
    check_eq("the same with a Path clone root and a `./` prefix",
             read(vitest.replace(" \u276f src", " \u276f ./src"), TS_FRAMES, TS_SKIP, JEST_TEST,
                  root_dir=root)["failure_kind"], "assertion")
    unread(read(vitest.replace("sum.test", "gone.test"), TS_FRAMES, TS_SKIP, JEST_TEST, root_dir=root),
           "a relative frame whose file does not exist")
    unread(read(vitest, TS_FRAMES, TS_SKIP, JEST_TEST, root_dir=""), "a relative frame with no clone root to look under")
    unread(read(vitest.replace(" \u276f src", " \u276f ../src"), TS_FRAMES, TS_SKIP, JEST_TEST, root_dir=root),
           "a relative frame that climbs out of the clone")
    unread(read(vitest.replace(" \u276f src", " \u276f src/../../src"), TS_FRAMES, TS_SKIP, JEST_TEST, root_dir=root),
           "a relative frame that climbs out through a middle segment")
    unread(read(jest.replace("/clone/", "/author/"), TS_FRAMES, TS_SKIP, JEST_TEST),
           "an absolute frame of another tree (TRX read it as `exception`; with a grammar it is unread)")
    other = temp_dir("qa-reporters-other-")
    try:
        (other / "src").mkdir()
        (other / "src" / "sum.test.ts").write_text("// the same file name, another tree\n", encoding="utf-8")
        unread(read(f"at Object.<anonymous> ({(other / 'src' / 'sum.test.ts').as_posix()}:11:20)", TS_FRAMES, TS_SKIP,
                    JEST_TEST, root_dir=root),
               "an absolute frame naming a file that EXISTS in another tree (existence is not residence)")
    finally:
        cleanup(other)
    unread(read(jest.replace("/clone/src", "/clone2/src"), TS_FRAMES, TS_SKIP, JEST_TEST),
           "a sibling directory with the same prefix is not inside the clone")
    check_eq("an absolute frame with `..` segments inside the clone is collapsed",
             read(jest.replace("/clone/src", "/clone/x/../src"), TS_FRAMES, TS_SKIP, JEST_TEST)["location"],
             "src/sum.test.ts:11")
    unread(read(jest.replace("/clone/src", "/clone/../src"), TS_FRAMES, TS_SKIP, JEST_TEST),
           "an absolute frame that climbs out of the clone")
    check_eq("a Windows frame in the clone, backslashes and drive case",
             read("at Object.<anonymous> (c:\\CLONE\\src\\sum.test.ts:11:20)", TS_FRAMES, TS_SKIP, JEST_TEST,
                  root_dir=CLONE_WIN)["location"], "src/sum.test.ts:11")

    # --- Java: a basename frame resolves only to the test file, in its package -------------------
    java = ("org.opentest4j.AssertionFailedError: expected: <4> but was: <0>\n"
            "\tat org.junit.jupiter.api.AssertionUtils.fail(AssertionUtils.java:55)\n"
            "\tat com.acme.CalcTest.adds(CalcTest.java:12)\n"
            "\tat java.base/java.lang.reflect.Method.invoke(Method.java:568)")
    got = read(java, JAVA_FRAMES, JAVA_SKIP, JAVA_TEST, frame_path="basename", runtime="mvn")
    check_eq("Java: library frames skipped, the test frame resolves to the test file, in the file's own form",
             got, {"location": "src/test/java/com/acme/CalcTest.java:12", "failure_kind": "assertion",
                   "frame": "\tat com.acme.CalcTest.adds(CalcTest.java:12)"})

    def java_read(text, test_file=JAVA_TEST, **extra):
        return read(text, JAVA_FRAMES, JAVA_SKIP, test_file, frame_path="basename", runtime="mvn", **extra)

    unread(java_read(java.replace("com.acme.CalcTest", "com.other.CalcTest")),
           "a same-named file in ANOTHER package (it must not become `wrong_location`)", runtime="mvn")
    check_eq("a package that is a proper suffix of the directory path resolves",
             java_read(java.replace("com.acme.CalcTest", "acme.CalcTest"))["location"],
             "src/test/java/com/acme/CalcTest.java:12")
    unread(java_read(java.replace("com.acme.CalcTest", "xacme.CalcTest")),
           "a package whose first segment only ends like the directory's segment (no partial segments)", runtime="mvn")
    unread(java_read(java, test_file="src/test/java/org/acme/CalcTest.java"),
           "the same frame against a test file whose directory is another package", runtime="mvn")
    unread(java_read(java, test_file="CalcTest.java"),
           "a package longer than the test file's whole directory", runtime="mvn")
    check_eq("the default package matches whatever the directory is",
             java_read(java.replace("com.acme.CalcTest", "CalcTest"), test_file="tests/CalcTest.java")["location"],
             "tests/CalcTest.java:12")
    check_eq("a nested class (`CalcTest$Inner`) and a lambda method are the same file",
             java_read(java.replace("com.acme.CalcTest.adds", "com.acme.CalcTest$Inner.lambda$adds$0"))["location"],
             "src/test/java/com/acme/CalcTest.java:12")
    check_eq("a Gradle `app//` module prefix is not part of the package",
             java_read(java.replace("com.acme.CalcTest", "app//com.acme.CalcTest"))["location"],
             "src/test/java/com/acme/CalcTest.java:12")
    unread(java_read(java.replace("com.acme.CalcTest.adds", "adds")),
           "a frame whose qualified name is not `Class.method`", runtime="mvn")
    unread(java_read(java.replace("com.acme.CalcTest.adds(CalcTest.java:12)", "com.acme.Calc.add(Calc.java:5)")),
           "a product frame first (a different file name never resolves under `basename`)", runtime="mvn")
    unread(read(java, [r"^\s*at\s+[\w$.<>/]+\((?P<path>[\w$]+\.java):(?P<line>\d+)\)"], JAVA_SKIP, JAVA_TEST,
                frame_path="basename", runtime="mvn"),
           "a basename grammar with no `qual` group cannot check the package", runtime="mvn")
    check_eq("an absolute test_file inside the clone is compared in its clone-relative form",
             java_read(java, test_file="/clone/" + JAVA_TEST)["location"], "src/test/java/com/acme/CalcTest.java:12")

    # --- TRX through the caller's grammar --------------------------------------------------------
    def trx_read(stack, **extra):
        return R.assertion_site(trx_row(stack, extra.pop("status", "failed")), "trx", CLONE_WIN, TEST_FILE,
                                pytest_command=False, runtime="dotnet", frames=CS_FRAMES, skip_frames=CS_SKIP, **extra)

    check_eq("a TRX frame in the clone, through the grammar: the same location, plus the raw line",
             trx_read(FRAME_CLONE), {"location": "backend/Tests/FeedbackTests.cs:42", "failure_kind": "assertion",
                                     "frame": FRAME_CLONE})
    walk = ("   at Xunit.Assert.Equal[T](T expected, T actual)\r\n" + FRAME_CLONE + "\r\n"
            "   at System.RuntimeMethodHandle.InvokeMethod(Object target)")
    check_eq("a skipped library frame first (CRLF read)", trx_read(walk)["location"], "backend/Tests/FeedbackTests.cs:42")
    check_eq("an error row is `error`", trx_read(FRAME_CLONE, status="error")["failure_kind"], "error")
    unread(trx_read("   at Xunit.Assert.Equal[T](T expected, T actual)"), "a TRX stack of skipped frames only",
           runtime="dotnet", reporter="trx")
    unread(trx_read("   at Backend.Tests.FeedbackTests.Rejects_empty() in C:\\author\\backend\\Tests\\FeedbackTests.cs:line 42"),
           "a TRX frame of the author's tree", runtime="dotnet", reporter="trx")
    check_eq("a passed TRX row has no site", R.assertion_site(
        trx_row(None, "passed"), "trx", CLONE_WIN, TEST_FILE, frames=CS_FRAMES), {})

    # --- where the caller's grammar is NOT read --------------------------------------------------
    check_eq("a pytest command keeps pytest's own rule, frames or not",
             R.assertion_site(row(PYTEST_TEXTS["assertion"]), "junit-xml", "/c", "tests/test_cart.py",
                              pytest_command=True, runtime="python", frames=TS_FRAMES, skip_frames=TS_SKIP), _ASSERT_12)
    check_eq("the `pytest` reporter too",
             R.assertion_site(row(PYTEST_TEXTS["assertion"]), "pytest", "/c", "tests/test_cart.py",
                              pytest_command=False, runtime="make", frames=TS_FRAMES), _ASSERT_12)
    for status in ("passed", "skipped", "not_run"):
        check_eq(f"a {status} row has no site to read, grammar or not",
                 R.assertion_site({"status": status, "problems": []}, "junit-xml", "/c", "t",
                                  pytest_command=False, runtime="npx", frames=TS_FRAMES), {})
    check_eq("the failure's own text is walked, not a skip's",
             R.assertion_site({"status": "failed", "problems": [
                 {"kind": "skipped", "message": "m", "text": jest}]}, "junit-xml", "/clone", JEST_TEST,
                 pytest_command=False, runtime="npx", frames=TS_FRAMES, skip_frames=TS_SKIP).get("site_unread"),
             "junit-xml/npx")

    # --- a grammar that cannot be used is a typed gap, never a crash, never a guess --------------
    unread(read(jest, ["(unclosed"], TS_SKIP, JEST_TEST), "a frames regex that does not compile")
    unread(read(jest, TS_FRAMES, ["(unclosed"], JEST_TEST), "a skip_frames regex that does not compile")
    unread(read(jest, [r"at (?P<path>\S+):(?P<row>\d+)"], TS_SKIP, JEST_TEST), "a frames regex without the `line` group")
    unread(read(jest, TS_FRAMES, TS_SKIP, JEST_TEST, frame_path="glob"), "an unknown frame_path")
    unread(read(jest, [], TS_SKIP, JEST_TEST), "an empty frames list (a grammar was given, and it is empty)")
    check_eq("a bare string is one pattern, not a list of letters",
             read(jest, TS_FRAMES[0], TS_SKIP[0], JEST_TEST)["location"], "src/sum.test.ts:11")
    unread(read(jest, 5, TS_SKIP, JEST_TEST), "a frames grammar that is not iterable (an int)")
    unread(read(jest, {"path": 1}, TS_SKIP, JEST_TEST), "a frames grammar that is a dict")
    unread(read(jest, TS_FRAMES, 5, JEST_TEST), "a skip_frames grammar that is not iterable")
    unread(read(jest, [5], TS_SKIP, JEST_TEST), "a frames list holding a non-regex")
    # a group that took no part in the match is no frame (it was `x:None` or an AttributeError)
    no_path = [r"^(?:\s*at (?P<path>\S+):(?P<line>\d+)|\s*boom(?P<x>))"]
    unread(read("boom", no_path, None, JEST_TEST), "a match in which the `path` group took no part")
    no_line = [r"^\s*at (?P<path>\S+?)(?::(?P<line>\d+))?$"]
    unread(read("at src/sum.test.ts", no_line, None, JEST_TEST), "a match in which the `line` group took no part")
    check_eq("such a non-frame is passed over: the next line that is a frame is the site",
             read("at src/sum.test.ts\nat /clone/src/sum.test.ts:7", no_line, None, JEST_TEST)["location"],
             "src/sum.test.ts:7")

    # --- a relative frame that is a tail of the test file's path is ambiguous (E26) ---------------
    (root / "packages" / "a" / "src").mkdir(parents=True, exist_ok=True)
    (root / "packages" / "a" / "src" / "sum.test.ts").write_text("// the package's test\n", encoding="utf-8")
    nested = "packages/a/src/sum.test.ts"
    got = read(vitest, TS_FRAMES, TS_SKIP, nested, root_dir=root)
    unread(got, "a relative frame that is a tail of the test file's path, both files existing")
    check("the reason names the ambiguity", "ambiguous relative frame" in got.get("reason", ""), str(got))
    check_eq("(control) the same frame, test file at the clone root, resolves",
             read(vitest, TS_FRAMES, TS_SKIP, JEST_TEST, root_dir=root)["failure_kind"], "assertion")
    check_eq("(control) the full relative path of the nested test file resolves",
             read(vitest.replace(" ❯ src", " ❯ packages/a/src"), TS_FRAMES, TS_SKIP, nested,
                  root_dir=root)["location"], nested + ":11")
    (root / "src" / "other.test.ts").write_text("// another file\n", encoding="utf-8")
    check_eq("(control) an existing relative frame that is not a tail of the test file stays an exception",
             read(vitest.replace("sum.test", "other.test"), TS_FRAMES, TS_SKIP, nested,
                  root_dir=root).get("failure_kind"), "exception")
    check_eq("a test_file written `./x` and an absolute one are the same file as `x` (one helper, both readers)",
             [read(jest, TS_FRAMES, TS_SKIP, "./" + JEST_TEST)["failure_kind"],
              read(jest, TS_FRAMES, TS_SKIP, "/clone/" + JEST_TEST)["failure_kind"],
              R.assertion_site(trx_row(FRAME_CLONE), "trx", CLONE_WIN, "./" + TEST_FILE)["failure_kind"],
              R.assertion_site(trx_row(FRAME_CLONE), "trx", CLONE_WIN, CLONE_WIN + "\\" + TEST_FILE)["failure_kind"]],
             ["assertion"] * 4)
    check_eq("an ABSOLUTE frame in the clone is never ambiguous",
             read("at /clone/src/sum.test.ts:11:20", TS_FRAMES, None, nested)["failure_kind"], "exception")


PYTEST_TEXTS = {
    "assertion": ("def test_total():\n>       assert total(1, 2) == 4, 'wrong total'\n"
                  "E       AssertionError: wrong total\n\ntests/test_cart.py:12: AssertionError"),
    "qualified": "tests/test_cart.py:12: builtins.AssertionError",
    "value": "def f():\n>   int('x')\nE   ValueError: bad\n\ntests/test_cart.py:3: ValueError",
    "no-tail": "E   something odd happened\n   and nothing else",
    "empty": "",
    "trailing-blank": "tests/test_cart.py:12: AssertionError\n\n   \n",
}

# FROZEN ORACLE. These literals were taken from ONE run of the old private readers -
# `red_sandbox._junit_rows` (the row) and `red_sandbox._failure_detail` (the site) - over exactly
# the PYTEST_TEXTS above, wrapped as <failure> and as <error>, before those functions were deleted
# (they had no caller but this file). The shared reader must keep agreeing with them.
OLD_ROW_TEXT = {  # `_junit_rows(...)[0]["text"]`: the node body, stripped
    "assertion": PYTEST_TEXTS["assertion"],
    "qualified": "tests/test_cart.py:12: builtins.AssertionError",
    "value": "def f():\n>   int('x')\nE   ValueError: bad\n\ntests/test_cart.py:3: ValueError",
    "no-tail": "E   something odd happened\n   and nothing else",
    "empty": "",
    "trailing-blank": "tests/test_cart.py:12: AssertionError",
}
_ASSERT_12 = {"location": "tests/test_cart.py:12", "failure_kind": "assertion"}
OLD_SITE = {  # `_failure_detail(_junit_rows(...)[0])`, by (label, tag)
    ("assertion", "failure"): _ASSERT_12, ("assertion", "error"): _ASSERT_12,
    ("qualified", "failure"): {"location": "tests/test_cart.py:12", "failure_kind": "exception"},
    ("qualified", "error"): {"location": "tests/test_cart.py:12", "failure_kind": "error"},
    ("value", "failure"): {"location": "tests/test_cart.py:3", "failure_kind": "exception"},
    ("value", "error"): {"location": "tests/test_cart.py:3", "failure_kind": "error"},
    ("no-tail", "failure"): {}, ("no-tail", "error"): {},
    ("empty", "failure"): {}, ("empty", "error"): {},
    ("trailing-blank", "failure"): _ASSERT_12, ("trailing-blank", "error"): _ASSERT_12,
}
OLD_FOLD = {  # `red_sandbox._reason_text(s)` == `window_record._reason_text(s)` for each sample
    "AssertionError: x  y": "x y", "x y": "x y", "": "", "AssertionError:": "", "  AssertionError:   z\n w": "z w",
}


def pytest_parity(root: Path) -> None:
    for label, text in PYTEST_TEXTS.items():
        for tag in ("failure", "error"):
            body = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            path = write(root, f"par-{label}-{tag}.xml",
                         f'<testsuite><testcase classname="tests.test_cart" name="t"><{tag} message="m">{body}</{tag}>'
                         "</testcase></testsuite>")
            new_row = R.read_rows(path, "pytest")[0]
            check_eq(f"frozen row ({label}, {tag}): the old reader's test_id, status and body",
                     (new_row["test_id"], new_row["status"], new_row["problems"][0]["message"],
                      new_row["problems"][0]["text"]),
                     ("tests.test_cart::t", "failed" if tag == "failure" else "error", "m", OLD_ROW_TEXT[label]))
            check_eq(f"pytest parity ({label}, {tag}): the old reader's site, frozen",
                     R.assertion_site(new_row, "pytest", "/ignored", "tests/test_cart.py"), OLD_SITE[label, tag])
            check_eq(f"junit-xml parity ({label}, {tag}): the same rule for a pytest command",
                     R.assertion_site(new_row, "junit-xml", "/ignored", "tests/test_cart.py"), OLD_SITE[label, tag])
    check_eq("the pytest rule's own answer", R.assertion_site(
        {"status": "failed", "problems": [{"kind": "failure", "message": "m", "text": PYTEST_TEXTS["assertion"]}]},
        "pytest", "/c", "tests/test_cart.py"), {"location": "tests/test_cart.py:12", "failure_kind": "assertion"})
    check_eq("a passed pytest row has no site",
             R.assertion_site({"status": "passed", "problems": []}, "pytest", "/c", "t.py"), {})
    both = {"status": "error", "problems": [
        {"kind": "error", "message": "", "text": "tests/conftest.py:5: RuntimeError"},
        {"kind": "failure", "message": "", "text": "tests/test_cart.py:20: AssertionError"}]}
    check_eq("pytest: a failure problem is read before an error one, as the old row reader did",
             R.assertion_site(both, "pytest", "/c", "t.py")["location"], "tests/test_cart.py:20")


def reasons() -> None:
    check_eq("pytest's AssertionError: prefix is folded away on either side",
             R.assertion_reason("Expected the node's border", "AssertionError: Expected the node's border"),
             ("Expected the node's border", "Expected the node's border"))
    for expected, actual in (("wrong total", "AssertionError: wrong total"), ("AssertionError: wrong total", "wrong total"),
                             ("AssertionError: wrong total", "AssertionError: wrong total"),
                             ("AssertionError:  a\n  b", "a b")):
        e, a = R.assertion_reason(expected, actual)
        check(f"match: {expected!r} vs {actual!r}", bool(e) and e == a, f"{e!r} {a!r}")
    check_eq("whitespace runs are folded in the receipt form", R.assertion_reason("a   b\n c", "a b c"), ("a b c", "a b c"))
    e, a = R.assertion_reason("Assert.Equal() Failure",
                              "Assert.Equal() Failure\nExpected: 1\nActual:   0")
    check_eq("a TRX headline plus Expected/Actual detail against a one-line expected", (e, a),
             ("Assert.Equal() Failure", "Assert.Equal() Failure"))
    # F2 (critic t-443): the headline fallback is for ONE pinned line only. Detail the author pinned
    # is never ignored; detail the author did not pin never refuses an honest receipt.
    def matches(expected, actual) -> bool:
        e, a = R.assertion_reason(expected, actual)
        return bool(e) and e == a
    check("a two-line pin whose second line differs does not match (4 vs 5)",
          not matches("count mismatch\nexpected 4", "count mismatch\nexpected 5"))
    check("a multi-line pin against a different multi-line actual does not match",
          not matches("Assert.Equal() Failure\nExpected: 1\nActual: 0", "Assert.Equal() Failure\nExpected: 2\nActual: 0"))
    check("a one-line pin plus the runner's own detail lines matches (the .NET receipt)",
          matches("Assert.Equal() Failure", "Assert.Equal() Failure\nExpected: 4\nActual: 5"))
    check("a one-line pin against an actual whose FIRST line differs does not match",
          not matches("Assert.Equal() Failure", "Assert.IsType() Failure\nAssert.Equal() Failure"))
    check("identical multi-line texts match", matches("count mismatch\nexpected 4", "count mismatch\nexpected 4"))
    check("a multi-line pin matches its own text with different whitespace folding",
          matches("count mismatch\nexpected 4", "count mismatch   expected 4"))
    for label, left, right in (("trailing blank lines", "count mismatch\nexpected 4\n\n\n", "count mismatch\nexpected 4"),
                               ("CRLF", "count mismatch\r\nexpected 4\r\n", "count mismatch\nexpected 4")):
        check(f"{label} in the pin do not change a match", matches(left, right))
        check(f"{label} in the actual do not change a match", matches(right, left))
        check(f"{label} in the pin do not turn a 4/5 mismatch into a match",
              not matches(left, "count mismatch\nexpected 5"))
        check(f"{label} in the actual do not turn a 4/5 mismatch into a match",
              not matches("count mismatch\nexpected 4", right.replace("4", "5")))
    check("a one-line pin with CRLF detail lines in the actual still matches",
          matches("Assert.Equal() Failure", "Assert.Equal() Failure\r\nExpected: 4\r\nActual: 5\r\n"))
    check_eq("an empty pin never matches, and (as before) its pair keeps the headline of a one-line actual",
             R.assertion_reason("", "AssertionError: x"), ("", "x"))
    check_eq("an empty pin's pair keeps the actual's headline (as before the rule), so the window stores no whole text",
             R.assertion_reason("", "x\ny"), ("", "x"))
    e, a = R.assertion_reason("Assert.IsType() Failure\nExpected: x", "Assert.Equal() Failure\nExpected: x")
    check("a different headline does not match", bool(e) and e != a, f"{e!r} {a!r}")
    e, a = R.assertion_reason("Assert.Equal() Failure", "AssertionError:\nAssert.Equal() Failure\nExpected: 1")
    check("a bare AssertionError: first line does not become the headline", e == a == "Assert.Equal() Failure", f"{e!r} {a!r}")
    e, a = R.assertion_reason("a\nb", "a b")
    check("the whole-text match whose headlines differ still matches (rule one)", e == a == "a b", f"{e!r} {a!r}")
    e, a = R.assertion_reason("", "AssertionError: x")
    check("an empty expected never matches", not (bool(e) and e == a))
    e, a = R.assertion_reason("x", None)
    check("an empty actual never matches", not (bool(e) and e == a))
    e, a = R.assertion_reason("", "")
    check("both empty never match", not (bool(e) and e == a))
    e, a = R.assertion_reason("\n\n  \n", "\n")
    check("whitespace only never matches", not (bool(e) and e == a))
    # The shared rule must agree with the two private folds it replaced, frozen in OLD_FOLD (both
    # of them gave the same answer on every sample; see the note at OLD_ROW_TEXT).
    for sample, old in OLD_FOLD.items():
        check_eq(f"the shared fold agrees with the old red_sandbox and window_record folds on {sample!r}",
                 R.assertion_reason(sample, sample)[0], old)


# --- B-416 N1 (D-0031): every reader the code has is TRIED on a report it could not read; entities never reach the parser ----------

def b416_fits_and_entities(root: Path) -> None:
    """`fits` says which of `junit-xml` / `trx` counts at least one test in a file - diagnosis only, `read_rows` is unchanged - and errs
    ONLY toward "nothing fits" (G16). `entity_declared` is the gate before the parser (G4); `PARSE_LIMIT` is the size gate (G3)."""
    def fitting(path) -> list:
        return [row["reader"] for row in R.fits(path) if row["tests"] >= 1]
    check_eq("the limits of the spec: 5 MiB parsed and kept, 5 files kept, a 64 KiB prolog scan",
             (R.PARSE_LIMIT, R.KEEP_LIMIT, R.KEEP_FILES, R.ENTITY_SCAN_LIMIT), (5242880, 5242880, 5, 65536))
    check_eq("a pytest JUnit report fits `junit-xml` and not `trx`", fitting(write(root, "f-junit.xml", JUNIT)), ["junit-xml"])
    check_eq("a TRX report fits `trx` and not `junit-xml`", fitting(write(root, "f.trx", MAIN_TRX)), ["trx"])
    check_eq("fits names both readers it tried, with a count each", [(row["reader"], row["tests"]) for row in R.fits(root / "f-junit.xml")],
             [("junit-xml", 5), ("trx", 0)])
    # G16: the inputs that must stay on the safe side - nothing fits
    cases = {
        "an empty file": "",
        "HTML": "<html><body><p>no tests</p></body></html>",
        "JSON": '{"tests": 3, "passed": 3}',
        "a namespaced JUnit (the reader looks for bare tags)": '<testsuite xmlns="urn:x" tests="1"><testcase classname="a" name="b"/></testsuite>',
        "`tests=\"0\"`": '<testsuite name="s" tests="0"/>',
        "a TRX with no UnitTestResult": trx("", ""),
        "plain text": "3 passed in 0.1s",
        "a truncated XML": '<testsuite><testcase classname="a" name="b"',
    }
    for label, text in cases.items():
        got = fitting(write(root, "g16.xml", text))
        check_eq(f"G16: {label}: nothing fits", got, [])
    check_eq("G16: a file that is not there: nothing fits and nothing raises",
             ([r["reader"] for r in R.fits(root / "no-such-file.xml")], fitting(root / "no-such-file.xml")), (["junit-xml", "trx"], []))
    (root / "g16.bin").write_bytes(bytes(range(256)) * 4)
    check_eq("G16: a binary file: nothing fits", fitting(root / "g16.bin"), [])
    # the entity bomb is refused BEFORE the parser, with its reason, and a DOCTYPE with no entity is read
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
            '<testsuite tests="1"><testcase classname="a" name="&lol2;"/></testsuite>')
    rows = R.fits(write(root, "g4-bomb.xml", bomb))
    check_eq("G4: an entity bomb: nothing fits", [r["tests"] for r in rows], [0, 0])
    check_in("G4: ... and the row says why: the factory does not expand entities", "does not expand", rows[0]["error"])
    plain = ('<?xml version="1.0"?><!DOCTYPE testsuite [<!ELEMENT testsuite ANY>]><testsuite tests="1">'
             '<testcase classname="a" name="b"/></testsuite>')
    check_eq("G4: a DOCTYPE with no ENTITY is parsed and fits", fitting(write(root, "g4-plain.xml", plain)), ["junit-xml"])
    check("G4: `entity_declared` is True for the bomb and False for the plain DOCTYPE and for a report with no DOCTYPE",
          R.entity_declared(root / "g4-bomb.xml") and not R.entity_declared(root / "g4-plain.xml") and not R.entity_declared(root / "f-junit.xml"))
    tricky = ('<?xml version="1.0"?><!-- c --><!DOCTYPE a [<!ATTLIST x y CDATA "<z>"> <!ENTITY e "v">]><testsuite tests="1">'
              '<testcase classname="a" name="b"/></testsuite>')
    check("G4: an ENTITY declared after a `<z>` inside a quoted default is still seen", R.entity_declared(write(root, "g4-tricky.xml", tricky)))
    check("G4: the ENTITY spelled in lower case or after a comment is still seen",
          R.entity_declared(write(root, "g4-case.xml", '<!DOCTYPE a [<!-- x --><!entity e "v">]><a/>')))
    (root / "g4-utf16.xml").write_bytes(bomb.encode("utf-16"))
    check("G4: a UTF-16 report is read by its BOM (an entity in it is seen)", R.entity_declared(root / "g4-utf16.xml"))
    (root / "g4-nul.xml").write_bytes(b"<a>\x00\x00</a>")
    check("G4: NUL bytes with no BOM: the prolog cannot be read, so it is refused (the safe side)", R.entity_declared(root / "g4-nul.xml"))
    # the scan limit: a root start at byte 65536 is read, none within 65537 is refused
    pad = lambda n: " " * n + '<testsuite tests="1"><testcase classname="a" name="b"/></testsuite>'  # noqa: E731
    check_eq("G4 AT the limit: a root start at 65536 is read (not refused)", R.entity_declared(write(root, "g4-at.xml", pad(65536))), False)
    check_eq("G4 BEYOND it: no root start within 65537 bytes is refused", R.entity_declared(write(root, "g4-over.xml", pad(65537))), True)
    check_eq("G4: the scan limit is a parameter", R.entity_declared(root / "g4-at.xml", scan_limit=100), True)
    # G3: PARSE_LIMIT - at the limit parsed, one byte beyond not parsed and named
    body = '<testsuite tests="1"><testcase classname="a" name="b"/></testsuite>'
    at = write(root, "g3-at.xml", body + " " * (R.PARSE_LIMIT - len(body)))
    check_eq("G3 AT the limit: a report of exactly PARSE_LIMIT bytes is parsed", (at.stat().st_size, fitting(at)), (R.PARSE_LIMIT, ["junit-xml"]))
    over = write(root, "g3-over.xml", body + " " * (R.PARSE_LIMIT - len(body) + 1))
    rows = R.fits(over)
    check_eq("G3 BEYOND it: one byte more is not parsed, and the row names the limit", ([r["tests"] for r in rows], "larger than" in rows[0]["error"]), ([0, 0], True))
    check_eq("`fits` takes the limit as a parameter", [r["tests"] for r in R.fits(at, size_limit=10)], [0, 0])
    # `read_rows` is unchanged: a declared reader still reads what it reads, `fits` is diagnosis only
    check_eq("read_rows is unchanged: a TRX read as junit-xml gives no row, not an error", R.read_rows(root / "f.trx", "junit-xml"), [])


# --- B-380: the detail of the failure a reason was compared against ---------------------------------------------------------

def reason_detail_says_which_rule_matched() -> None:
    """R-T1: `reason_detail.rule` is the rule `assertion_reason` applies - the one `_reason_rule`. M8 (`> 1` -> `>= 1`) is
    killed by the existing `reasons()` headline checks and by the `headline` row here."""
    rules = (("equal after the fold", "AssertionError:  a   b", "a b", "whole"),
             ("a two-line pin", "count mismatch\nexpected 4", "count mismatch\nexpected 5", "whole"),
             ("a one-line pin, the texts differ", "Assert.Equal() Failure", "Assert.Equal() Failure\nExpected: 4", "headline"),
             ("an empty pin", "", "x\ny", "empty_pin"),
             ("empty against empty", "", "", "whole"),
             ("only blank lines pinned", "\n \n", "x", "empty_pin"))
    for label, expected, actual, want in rules:
        check_eq(f"R-T1: {label} -> {want}", R.reason_detail(expected, actual)["rule"], want)
    check_eq("R-T1: the pair `assertion_reason` returns is unchanged by the refactor (a headline match)",
             R.assertion_reason("Assert.Equal() Failure", "Assert.Equal() Failure\nExpected: 4"),
             ("Assert.Equal() Failure", "Assert.Equal() Failure"))


def reason_detail_is_bounded() -> None:
    """R-T2: AT and BEYOND `REASON_DETAIL_LINES` (12) and `REASON_DETAIL_CHARS` (200); the total is the true count (E10)."""
    check_eq("R-T2: the limits of the spec", (R.REASON_DETAIL_LINES, R.REASON_DETAIL_CHARS, R.REASON_DETAIL_SHOWN), (12, 200, 3))

    def lines(n) -> str:
        return "\n".join(f"line {i}" for i in range(1, n + 1))
    at = R.reason_detail("line 1", lines(12))
    check_eq("R-T2: 12 lines are all kept, total 12 (AT the cap)", (len(at["actual_lines"]), at["actual_lines_total"]), (12, 12))
    beyond = R.reason_detail("line 1", lines(13))
    check_eq("R-T2: 13 lines keep 12, total 13 (BEYOND the cap)",
             (len(beyond["actual_lines"]), beyond["actual_lines_total"]), (12, 13))
    check_eq("R-T2: the kept lines are the FIRST 12", beyond["actual_lines"][-1], "line 12")
    check_eq("R-T2: a line of exactly 200 characters is kept whole", R.reason_detail("x", "a" * 200)["actual_lines"], ["a" * 200])
    cut = R.reason_detail("x", "a" * 201)["actual_lines"][0]
    check_eq("R-T2: 201 characters become 199 + the cut mark (length 200)", (cut, len(cut)), ("a" * 199 + "…", 200))
    crlf = R.reason_detail("x", "one\r\n\r\n   \r\ntwo\r\n")
    check_eq("R-T2: blank lines and CRLF are not lines", (crlf["actual_lines"], crlf["actual_lines_total"]), (["one", "two"], 2))
    check_eq("R-T2: an absent actual is [] and 0 (AR-23)",
             (R.reason_detail("x", None)["actual_lines"], R.reason_detail("x", None)["actual_lines_total"]), ([], 0))
    check_eq("R-T2: a leading `AssertionError:` is dropped first, not counted as a line",
             R.reason_detail("x", "AssertionError:\nboom\n  detail   here")["actual_lines"], ["boom", "detail here"])


def reason_detail_line_speaks_only_for_a_headline_match() -> None:
    """R-T3: the note exists only when the reason was compared on the first line, the failure has more lines, and the probe's
    two reasons MATCHED (m-6). It never starts with the instance id (`<iid>:` lines are proof notes)."""
    head = "Assert.Equal() Failure"

    def probe(expected, actual, same=True) -> dict:
        return {"expected_reason": head, "actual_reason": head if same else "other",
                "reason_detail": R.reason_detail(expected, actual)}
    two = probe(head, head + "\nExpected: 4")
    check_eq("R-T3: two lines -> one detail line, no `more`", R.reason_detail_line(two, "t[x]"),
             "probe reason matched on the failure's first line only (\"Assert.Equal() Failure\"); 1 other line(s) of the "
             "failure were not compared: \"Expected: 4\" (t[x])")
    five = R.reason_detail_line(probe(head, head + "\nb\nc\nd\ne"), "t[x]")
    check_eq("R-T3: five lines -> three shown and `(+1 more)`", (five.count(" | "), "(+1 more)" in five, "4 other line(s)" in five),
             (2, True, True))
    check("R-T3: the line does not start with the instance id", not five.startswith("t[x]"), five)
    check_eq("R-T3: a whole match is silent", R.reason_detail_line(probe(head + "\nb", head + "\nb"), "i"), "")
    check_eq("R-T3: an empty pin is silent", R.reason_detail_line(probe("", head + "\nb"), "i"), "")
    check_eq("R-T3: a one-line failure (total 1) is silent", R.reason_detail_line(probe(head, head), "i"), "")
    check_eq("R-T3: an older record without the block is silent",
             R.reason_detail_line({"expected_reason": "a", "actual_reason": "a"}, "i"), "")
    check_eq("R-T3: no probe at all is silent", R.reason_detail_line(None, "i"), "")
    for label, bad in (("lines not a list", {"rule": "headline", "actual_lines": "x", "actual_lines_total": 3}),
                       ("total not an int", {"rule": "headline", "actual_lines": ["a", "b"], "actual_lines_total": "3"}),
                       ("total a bool", {"rule": "headline", "actual_lines": ["a", "b"], "actual_lines_total": True}),
                       ("no lines", {"rule": "headline", "actual_lines": [], "actual_lines_total": 3}),
                       ("a block that is no dict", "headline")):
        check_eq(f"R-T3: a malformed block ({label}) is silent", R.reason_detail_line(dict(two, reason_detail=bad), "i"), "")
    check_eq("R-T3 (m-6): a headline RULE whose reasons differ did not match: silent",
             R.reason_detail_line(probe(head, head + "\nb", same=False), "i"), "")
    check_eq("R-T3 (m-6): ... and an empty expected reason is silent",
             R.reason_detail_line(dict(two, expected_reason="", actual_reason=""), "i"), "")


def main() -> None:
    root = temp_dir("qa-reporters-")
    try:
        b416_fits_and_entities(root)
        junit(root)
        trx_rows(root)
        dispatch_and_errors(root)
        sites()
        unread_sites()
        frame_sites(root)
        pytest_parity(root)
        reasons()
        reason_detail_says_which_rule_matched()
        reason_detail_is_bounded()
        reason_detail_line_speaks_only_for_a_headline_match()
        oracles_are_frozen()
    finally:
        cleanup(root)
    finish("test_reporters")


if __name__ == "__main__":
    main()
