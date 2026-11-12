#!/usr/bin/env python3
"""t-1502 G-1 / G-2: the grouping hint of the S5 plan, the `apart_reason` field and the rule's text in three carriers.

The join key (the forge finding of 28.10.2026): the REAL output of the producer - `fixtures/run-12586-s5-plan/s5-plan.json`, the
plan the 0.10.3 author wrote for run TP1-12586 - goes through its consumers (`s5_plan.grouping_hints`, `check_report`,
`render_slice`, `--check`; `s5_precheck.plan_result`; the plan critic's brief), not only a hand-built input.

Every key names the mutation it kills (spec t-1502 section 5.1/5.2): K3 the `apart_reason` exception removed; K9 grouping without
the level, or a private path normalizer instead of `s5_precheck._file_key`; K5 the list limit 5; K1 `extend` among the candidates;
K4 a non-text `apart_reason` kept a candidate; K3c `render_slice` without the line; K8 a second `load` in `main`; K2 (in
test_s5_precheck_plan.py) `ok = not findings and not hints`; K10 / K-G2 the text of a carrier cut out (DOC-DISPATCH witness: the
keys are the spec's lines, quoted verbatim BEFORE the run, with a negative control that cuts one key out and must go red).
"""
import contextlib
import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import s5_plan as SP  # noqa: E402

import test_s5_plan as BASE  # noqa: E402  (its fixtures; its checks run only under its own __main__)
from test_s5_plan_check import Fake, good_plan, has, mutate  # noqa: E402

put = BASE.put
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-s5-plan" / "s5-plan.json"
FIXTURE_CASES = ("TC-001", "TC-002", "TC-003", "TC-004", "TC-005", "TC-006", "TC-007", "TC-008", "TC-009", "TC-011")
GROUPED = ("TC-001", "TC-002", "TC-004", "TC-005", "TC-006", "TC-007", "TC-011")      # the seven api cases of one file
API_FILE = "testproject1_test_harness/tests/integrations/project/test_integration_project_change.py"
REASON = "another fixture: needs an MS Teams integration in the target project"
# The two project files the plan's two `extend` rows name: the check looks them up under the project root.
STUBS = {"testproject1_test_harness/tests/integrations/project/test_ms_teams_integration.py":
         "def test_create_ms_teams_integration_duplicate_returns_409():\n    assert True\n",
         "testproject1_test_harness/tests/ui/integrations/test_edit_integration.py":
         "def test_edit_integration_update_alias():\n    assert True\n\n\ndef test_edit_integration_update_credentials():\n    assert True\n"}
IDS = {"TC-001": "test_put_project_change_moves_integration", "TC-002": "test_put_project_change_moves_ms_teams_integration",
       "TC-004": "test_put_project_change_requires_admin_in_target", "TC-005": "test_put_project_change_from_user_scope_and_collision"}


def fixture_plan():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@contextlib.contextmanager
def fixture_story(ticket="QA-1"):
    """`(project, task)`: an onboarded project holding the two files the plan extends and, under a story folder, the producer's own
    `s5-plan.json`. The story's CONTROLLER is the one seam that is faked (the helpers of the story fixtures are written for the case
    ids TC-1..TC-n): `controller.Controller(task_root)` answers `Fake` with the fixture's ten cases as the S5 scope, one window
    holding all of them, and the project root - so the real plan reader, the real plan check, the real hint and the real consumers
    (`main`, `plan_result`, the brief) all read the real file. The project is cleaned up on exit."""
    import controller as CT
    project = temp_project("qa-s5grp-")
    task = project / "qa-factory" / "artifacts" / ticket
    task.mkdir(parents=True)
    put(task, "pipeline.json", json.dumps({"ticket": ticket, "size": "S", "environment": "local", "stages": {}, "gates": {}, "halts": []}))
    for rel, text in STUBS.items():
        put(project, rel, text)
    harness.use_project(project)
    put(task, SP.PLAN_REL, FIXTURE.read_bytes())
    real = CT.Controller
    CT.Controller = lambda root, *args, **kw: Fake(FIXTURE_CASES, project, windows=[{"index": 1, "surface": "other", "scope": list(FIXTURE_CASES)}])
    try:
        yield project, task
    finally:
        CT.Controller = real
        cleanup(project)


def run_main(project, *argv):
    """`(exit code, stdout, stderr)` of `s5_plan.main()` with these arguments, in this process (the controller seam as `fixture_story`)."""
    out, err, old = io.StringIO(), io.StringIO(), sys.argv
    sys.argv = ["s5_plan.py", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = SP.main()
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


def piece_of(plan, cases):
    """The slice of the cases as `window_slice` makes it (a hand-built piece: the same keys), for `render_slice`."""
    rows = [r for r in SP._rows(plan, "cases") if r.get("case") in cases]
    return {"window": 1, "windows": [1], "asked": list(cases), "cases": rows, "missing": [],
            "tests": [t for t in SP._rows(plan, "tests") if any(c in cases for c in t.get("cases") or [])], "remainders": [],
            "requirements": [], "remarks": [], "surface": "other", "size": len(cases), "over_cap": False, "cap": None, "grown": []}


def write_plan(task, plan):
    put(task, SP.PLAN_REL, json.dumps(plan))


def with_reason(plan, case, reason):
    plan = copy.deepcopy(plan)
    for test in plan["tests"]:
        if test["cases"] == [case]:
            test["apart_reason"] = reason
    return plan


def row(identifier, cases, file="tests/test_a.py", level="api", shape="new", **extra):
    return dict({"id": identifier, "file": file, "cases": cases if isinstance(cases, str) else list(cases), "level": level, "shape": shape}, **extra)


# --- K1: the producer's real output, through the hint ---------------------------------------------------------

def k1_the_real_plan():
    plan = fixture_plan()
    hints = SP.grouping_hints(plan)
    check_eq("K1: the stand's plan gives exactly one hint (seven tests, one group)", len(hints), 1)
    expected = (f"7 tests at level api in {API_FILE} each prove their own case(s) ({IDS['TC-001']}, {IDS['TC-002']}, {IDS['TC-004']}, "
                f"{IDS['TC-005']}, +3 more): " + ", ".join(GROUPED))
    check_eq("K1: its message names the file, four test ids, '+3 more' and the seven cases", hints[0]["message"], expected)
    tail = hints[0]["message"].split("): ", 1)[1]
    check("K1: TC-003 (extend, another file) and TC-008/TC-009 (e2e-ui extends) are in no group",
          not any(case in tail for case in ("TC-003", "TC-008", "TC-009")), tail)
    check_eq("K1: the row is neutral: case, message, fix, tag", sorted(hints[0]), ["case", "fix", "message", "tag"])
    check_eq("K1: its case is the first of the group", hints[0]["case"], "TC-001")
    check("K1: its fix leads only to a parameterized test and names the door",
          "one parameterized test" in hints[0]["fix"] and "`apart_reason`" in hints[0]["fix"] and "consolidate" not in hints[0]["fix"], hints[0]["fix"])
    check("K1: the tag is stable and has the group form", hints[0]["tag"] == SP.grouping_hints(fixture_plan())[0]["tag"] and hints[0]["tag"].startswith("group-")
          and len(hints[0]["tag"]) == len("group-") + 8)
    # the same through the one reader of the file on disk
    root = temp_dir("qa-s5grp-k1-")
    try:
        put(root, SP.PLAN_REL, FIXTURE.read_bytes())
        check_eq("K1: SP.load of the producer's file gives the same hint", SP.grouping_hints(SP.load(root)), hints)
        findings, notes = SP.check_report(root, Fake(FIXTURE_CASES, windows=[{"index": 1, "surface": "other", "scope": list(FIXTURE_CASES)}]))
        check_eq("K1: the producer's real plan is clean for the plan check (the hint is no finding)", findings, [])
    finally:
        cleanup(root)


# --- K3 / K3b / K3c: the door `apart_reason`, a parameter of one test, the slice ---------------------------------

def k3_apart_reason():
    plan = with_reason(fixture_plan(), "TC-002", REASON)
    hints = SP.grouping_hints(plan)
    check_eq("K3: a reason on TC-002's test leaves a group of six", len(hints), 1)
    message = hints[0]["message"]
    check("K3: ... six tests, without TC-002 and without its test id",
          message.startswith("6 tests at level api in ") and "TC-002" not in message and IDS["TC-002"] not in message, message)
    check_in("K3: ... '+2 more'", ", +2 more)", message)
    for blank in ("   ", "", None, "\t\n"):
        again = SP.grouping_hints(with_reason(fixture_plan(), "TC-002", blank))
        check_eq(f"K3: a blank reason ({blank!r}) is no reason - seven again", again[0]["message"].split(" ", 1)[0] if again else None, "7")
    only = fixture_plan()
    for test in only["tests"]:
        if test["cases"][0] in GROUPED:
            test["apart_reason"] = REASON
    check_eq("K3: every candidate with a reason: no hint", SP.grouping_hints(only), [])


def k3b_red_as_a_parameter():
    """A case expected red is a PARAMETER of one test (B1): one test over the seven cases is not a group and is no hint."""
    plan = fixture_plan()
    tests = [t for t in plan["tests"] if t["cases"][0] not in GROUPED]
    merged = {"id": IDS["TC-001"], "file": API_FILE, "function": IDS["TC-001"], "cases": list(GROUPED),
              "thens": [t for test in plan["tests"] if test["cases"][0] in GROUPED for t in test["thens"]],
              "level": "api", "shape": "parameterize", "data": "own", "assert": "each parameter id names its case"}
    plan["tests"] = [merged] + tests
    check_eq("K3b: the seven cases as parameters of ONE parameterized test: no hint", SP.grouping_hints(plan), [])


def k3c_slice_shows_the_reason():
    text = SP.render_slice(piece_of(with_reason(fixture_plan(), "TC-002", REASON), ["TC-002"]))
    check_in("K3c: the slice of a window shows the test's reason", f"apart_reason: {REASON}", text)
    check_not_in("K3c: no field, no line", "apart_reason", SP.render_slice(piece_of(fixture_plan(), ["TC-002"])))
    check_not_in("K3c: a blank reason is no line", "apart_reason", SP.render_slice(piece_of(with_reason(fixture_plan(), "TC-002", "   "), ["TC-002"])))
    check_not_in("K3c: a reason that is not text is no line (it is a finding of the check)", "apart_reason",
                 SP.render_slice(piece_of(with_reason(fixture_plan(), "TC-002", {"why": "x"}), ["TC-002"])))
    check_in("K3c: the line sits with the other fields of the test, before its assert", f"apart_reason: {REASON}\nassert: ",
             SP.render_slice(piece_of(with_reason(fixture_plan(), "TC-002", REASON), ["TC-002"])))


# --- K4: the field's form: 300 / 301, not text ------------------------------------------------------------------

def k4_field_form():
    root = temp_dir("qa-s5grp-k4-")
    try:
        def findings_with(value, key="apart_reason"):
            plan = mutate(good_plan(), lambda p: p["tests"][0].__setitem__(key, value))
            put(root, SP.PLAN_REL, json.dumps(plan))
            return SP.check_report(root, Fake(("TC-1", "TC-2", "TC-3")))[0]
        check_eq("K4: 300 characters is accepted (AT)", [f for f in findings_with("x" * 300) if "apart_reason" in f], [])
        over = [f for f in findings_with("x" * 301) if "apart_reason" in f]
        check("K4: 301 is a finding (BEYOND), naming the field and the limit", len(over) == 1 and "301 characters" in over[0] and "limit is 300" in over[0], str(over))
        for blank in ("", None, "   "):
            check_eq(f"K4: {blank!r} is no finding (the field is optional)", [f for f in findings_with(blank) if "apart_reason" in f], [])
        absent = [f for f in SP.check_report(root, Fake(("TC-1", "TC-2", "TC-3")))[0] if "apart_reason" in f]
        check_eq("K4: the field absent (an old plan): no finding", absent, [])
        for value in ({"why": "x"}, 5, ["x"], True):
            found = [f for f in findings_with(value) if "apart_reason" in f]
            check(f"K4: {value!r} is a finding of form: not text", len(found) == 1 and "is not text" in found[0], str(found))
        pair = [row("T-1", ["TC-1"]), row("T-2", ["TC-2"], apart_reason={"why": "x"})]
        check_eq("K4: a test whose reason is not text is NOT a candidate (one candidate left: no group)", SP.grouping_hints({"tests": pair}), [])
        pair[1]["apart_reason"] = None
        check_eq("K4: ... with null it is a candidate", len(SP.grouping_hints({"tests": pair})), 1)
        pair[1]["apart_reason"] = "another surface"
        check_eq("K4: ... with a text reason it stands apart", SP.grouping_hints({"tests": pair}), [])
    finally:
        cleanup(root)


# --- K5: the list of ids: 4 / 5 ---------------------------------------------------------------------------------

def k5_id_list():
    four = SP.grouping_hints({"tests": [row(f"T-{n}", [f"TC-{n}"]) for n in range(1, 5)]})[0]["message"]
    check("K5: four ids are listed whole, with no tail (AT)", "(T-1, T-2, T-3, T-4)" in four and "more" not in four, four)
    five = SP.grouping_hints({"tests": [row(f"T-{n}", [f"TC-{n}"]) for n in range(1, 6)]})[0]["message"]
    check("K5: five ids list four and '+1 more' (BEYOND)", "(T-1, T-2, T-3, T-4, +1 more)" in five and "T-5)" not in five, five)


# --- K6: the helpers never raise; awkward inputs -----------------------------------------------------------------

def k6_helpers():
    root = temp_dir("qa-s5grp-k6-")
    try:
        check_eq("K6: no file -> (None, 'no plan')", SP.plan_for_hints(root), (None, "no plan"))
        check_eq("K6: no file -> no rows and nothing to say (the plan check says it)", SP.hint_rows(root), ([], ""))
        put(root, SP.PLAN_REL, b"{not json")
        plan, why = SP.plan_for_hints(root)
        check("K6: a plan that is not JSON -> (None, 'PlanUnreadable: ...')", plan is None and why.startswith("PlanUnreadable: "), why)
        check_eq("K6: ... no rows and nothing to say (a finding already refuses it)", SP.hint_rows(root), ([], ""))
        put(root, SP.PLAN_REL, b'{"schema": 2}')
        check("K6: another schema -> the same", SP.plan_for_hints(root)[0] is None and SP.plan_for_hints(root)[1].startswith("PlanUnreadable: "))
        put(root, SP.PLAN_REL, FIXTURE.read_bytes())
        check_eq("K6: a readable plan -> (plan, '')", (SP.plan_for_hints(root)[1], SP.plan_for_hints(root)[0]["schema"]), ("", 1))
        check_eq("K6: ... and its rows, nothing to say", (len(SP.hint_rows(root)[0]), SP.hint_rows(root)[1]), (1, ""))
        real_load = SP.load

        def boom(_root):
            raise RuntimeError("boom " + "x" * 200)
        SP.load = boom
        try:
            plan, why = SP.plan_for_hints(root)
            check("K6: a `load` that raises -> (None, '<Type>: <message up to 100>')", plan is None and why.startswith("RuntimeError: boom") and len(why) <= 100 + 20, why)
            check("K6: ... hint_rows says what failed, never raises", SP.hint_rows(root)[0] == [] and SP.hint_rows(root)[1].startswith("RuntimeError: boom"))
        finally:
            SP.load = real_load
        real_hints = SP.grouping_hints

        def broken(_plan, file_key=None):
            raise ValueError("no way")
        SP.grouping_hints = broken
        try:
            check_eq("K6: grouping_hints that raises -> hint_rows says so", SP.hint_rows(root), ([], "ValueError: no way"))
        finally:
            SP.grouping_hints = real_hints
    finally:
        cleanup(root)
    awkward = [("plan None", None), ("plan []", []), ("plan 'x'", "x"), ("tests {}", {"tests": {}}), ("tests None", {"tests": None}),
               ("row [1]", {"tests": [[1], row("T-1", ["TC-1"])]}),
               ("cases a string", {"tests": [row("T-1", "TC-1"), row("T-2", "TC-2")]}),
               ("cases with None", {"tests": [row("T-1", [1, None]), row("T-2", ["TC-2", None])]}),
               ("file 5", {"tests": [row("T-1", ["TC-1"], file=5), row("T-2", ["TC-2"], file=5)]}),
               ("level API", {"tests": [row("T-1", ["TC-1"], level="API"), row("T-2", ["TC-2"], level="API")]}),
               ("shape New", {"tests": [row("T-1", ["TC-1"], shape="New"), row("T-2", ["TC-2"], shape="New")]}),
               ("level a list", {"tests": [row("T-1", ["TC-1"], level=["api"]), row("T-2", ["TC-2"], level=["api"])]}),
               ("file blank", {"tests": [row("T-1", ["TC-1"], file="  "), row("T-2", ["TC-2"], file="  ")]}),
               ("one test", {"tests": [row("T-1", ["TC-1", "TC-2"])]}),
               ("one case in two tests", {"tests": [row("T-1", ["TC-1"]), row("T-2", ["TC-1"])]}),
               ("apart_reason a mapping", {"tests": [row("T-1", ["TC-1"], apart_reason={"why": "x"}), row("T-2", ["TC-2"], apart_reason={"why": "x"})]})]
    for label, plan in awkward:
        try:
            got = SP.grouping_hints(plan)
        except Exception as exc:        # noqa: BLE001
            got = f"raised {exc!r}"
        check_eq(f"K6: an awkward input ({label}) gives no hint and no exception", got, [])
    repeated = SP.grouping_hints({"tests": [row("T-1", ["TC-1"]), row("T-1", ["TC-2"])]})
    check_eq("K6: a repeated id does not raise (one group of two rows)", len(repeated), 1)
    check_eq("K6: a test already naming two cases and a lone neighbour of the same file: a hint",
             len(SP.grouping_hints({"tests": [row("T-1", ["TC-1", "TC-2"], shape="parameterize"), row("T-2", ["TC-3"])]})), 1)
    for shape in ("extend", "reuse", "consolidate"):
        check_eq(f"K6: shape {shape} is not a candidate", SP.grouping_hints({"tests": [row("T-1", ["TC-1"], shape=shape), row("T-2", ["TC-2"], shape=shape)]}), [])


# --- K8: --check on the real plan, through the command line ---------------------------------------------------------

def k8_check_command():
    with fixture_story() as (project, task):
        code, out, err = run_main(project, "--task", "QA-1", "--check")
        lines = out.splitlines()
        hint_at = next((i for i, line in enumerate(lines) if line.startswith("hint: [plan] 7 tests at level api in ")), None)
        ok_at = next((i for i, line in enumerate(lines) if line.startswith("OK:")), None)
        check("K8: the real plan prints the hint before the OK line", hint_at is not None and ok_at is not None and hint_at < ok_at, out[:800])
        check_eq("K8: ... the exit code is 0 (a hint is no finding)", code, 0)
        check_in("K8: ... the line under the hint is its advice", "  consider: if they share setup and action, write one parameterized test", out)
        check_in("K8: ... the OK line says the hint is advice and names the door", SP.HINT_ADVICE, out)
        verdict = DV.parse(code, out, err)
        check_eq("K8: the detector's reader finds a pass (no finding, no defect)", (verdict["findings"], verdict["defects"], verdict["unmigrated"]), ([], [], ""))
        # the same plan with every candidate answered: no hint, the same exit code
        answered = fixture_plan()
        for test in answered["tests"]:
            if test["cases"][0] in GROUPED:
                test["apart_reason"] = REASON
        write_plan(task, answered)
        code, out, err = run_main(project, "--task", "QA-1", "--check")
        check_eq("K8: every candidate answered: no hint line and the same exit code", (code, "hint:" in out), (0, False))
        check_not_in("K8: ... and the OK line carries no advice sentence", SP.HINT_ADVICE, out)
        # a finding next to a hint: the hint is printed, the verdict is a REJECT with ONE finding, exit 1
        bad = fixture_plan()
        bad["tests"][1]["apart_reason"] = "y" * 301
        write_plan(task, bad)
        code, out, err = run_main(project, "--task", "QA-1", "--check")
        check_eq("K8: a finding + a hint: exit 1, REJECT of one finding, the hint above it",
                 (code, "REJECT — 1 finding(s)" in out, 0 <= out.find("hint:") < out.find("REJECT")), (1, True, True))
        verdict = DV.parse(code, out, err)
        check_eq("K8: ... and the detector's reader counts one finding, no defect", (len(verdict["findings"]), verdict["defects"]), (1, []))
        # an unreadable plan: REJECT, exit 1, no hint, no traceback and not exit 2 (F5)
        put(task, SP.PLAN_REL, b"{half")
        code, out, err = run_main(project, "--task", "QA-1", "--check")
        check("K8: an unreadable plan is a REJECT of one finding, exit 1 (not 2), no hint, no traceback",
              code == 1 and "REJECT — 1 finding(s)" in out and "hint:" not in out and "Traceback" not in err, out + err)
        (task / SP.PLAN_REL).unlink()
        code, out, err = run_main(project, "--task", "QA-1", "--check")
        check("K8: no plan file: exit 1, REJECT, no hint", code == 1 and "REJECT" in out and "hint:" not in out, out + err)
        # the hints could not be computed (any other failure): a note that says so, the verdict unchanged
        write_plan(task, fixture_plan())
        real = SP.grouping_hints
        SP.grouping_hints = lambda plan, file_key=None: (_ for _ in ()).throw(ValueError("no way"))
        try:
            code, out, err = run_main(project, "--task", "QA-1", "--check")
        finally:
            SP.grouping_hints = real
        check("K8: grouping_hints that raises: exit 0, a 'not checked' note, no hint, no traceback",
              code == 0 and "note: not checked: the grouping hints of the plan (ValueError: no way)" in out and "hint:" not in out, out + err)


# --- K9: the key of the group, with an unlike plan ----------------------------------------------------------------------

def k9_the_key():
    check_eq("K9: one level, two files: no group",
             SP.grouping_hints({"tests": [row("T-1", ["TC-1"], file="tests/a.py"), row("T-2", ["TC-2"], file="tests/b.py")]}), [])
    spelled = SP.grouping_hints({"tests": [row("T-1", ["TC-1"], file="tests/x.py"), row("T-2", ["TC-2"], file="./tests/x.py"),
                                           row("T-3", ["TC-3"], file="tests\\x.py"), row("T-4", ["TC-4"], file=".\\tests\\x.py")]})
    check("K9: 'x.py', './x.py' and a backslash path are ONE group (the one normalizer, _file_key)",
          len(spelled) == 1 and spelled[0]["message"].startswith("4 tests at level api in tests/x.py "), str(spelled))
    check_eq("K9: the case of a path is not folded",
             SP.grouping_hints({"tests": [row("T-1", ["TC-1"], file="tests/X.py"), row("T-2", ["TC-2"], file="tests/x.py")]}), [])
    check_eq("K9: api and e2e-ui tests of one file, one of each: no group",
             SP.grouping_hints({"tests": [row("T-1", ["TC-1"], level="api"), row("T-2", ["TC-2"], level="e2e-ui")]}), [])
    two = SP.grouping_hints({"tests": [row("T-1", ["TC-1"], level="api"), row("T-2", ["TC-2"], level="api"),
                                       row("T-3", ["TC-3"], level="e2e-ui"), row("T-4", ["TC-4"], level="e2e-ui")]})
    check_eq("K9: two of each level in one file: two groups, by level, in order of appearance",
             [h["message"].split(" ")[4] for h in two], ["api", "e2e-ui"])
    check("K9: ... their tags differ", two[0]["tag"] != two[1]["tag"])
    check_eq("K9: a different suite (java, a name with no test_ prefix): the same rule, no pattern of a language",
             len(SP.grouping_hints({"tests": [row("T-1", ["TC-1"], file="src/test/CalcSpec.java", level="unit"),
                                              row("T-2", ["TC-2"], file="src/test/CalcSpec.java", level="unit")]})), 1)


# --- G-2: `fit: new` allows `parameterize`; the two meanings of `consolidates` ---------------------------------------------

TWO_LISTS = "`consolidates` means two lists: in the S5 plan, the tests a consolidated test merges; in the manifest, the cases the instance proves"      # without the full stop: it closes a parenthesis in two carriers


def merged_plan(cases, fit_of=None):
    """The fixture's plan with the tests of `cases` (all in the one api file) replaced by ONE `parameterize` test over them."""
    plan = fixture_plan()
    mine = [t for t in plan["tests"] if t["cases"][0] in cases]
    merged = {"id": mine[0]["id"], "file": API_FILE, "function": mine[0]["function"], "cases": list(cases),
              "thens": [x for t in mine for x in t["thens"]], "level": "api", "shape": "parameterize", "data": "own",
              "assert": "each parameter id names its case"}
    plan["tests"] = [merged] + [t for t in plan["tests"] if t["cases"][0] not in cases]
    for row_ in plan["cases"]:
        if fit_of and row_["case"] in fit_of:
            row_["s3"]["fit"] = fit_of[row_["case"]]
    return plan


def kg2_fit_new_parameterize():
    root = temp_dir("qa-s5grp-g2-")
    scope = Fake(FIXTURE_CASES, windows=[{"index": 1, "surface": "other", "scope": list(FIXTURE_CASES)}])
    try:
        def findings_of(plan):
            put(root, SP.PLAN_REL, json.dumps(plan))
            return SP.check_report(root, scope)[0]
        check_eq("G-2 K1: TC-004 and TC-005 (S3 fit `new`) as ONE parameterize test: no finding", findings_of(merged_plan(["TC-004", "TC-005"])), [])
        check_eq("G-2 K3 (= G-1 K3b): the seven cases of the stand as parameters of one test (fit `new` and `param`): no finding, no hint",
                 (findings_of(merged_plan(list(GROUPED))), SP.grouping_hints(merged_plan(list(GROUPED)))), ([], []))
        found = findings_of(merged_plan(["TC-004", "TC-005"], fit_of={"TC-004": "extend T3"}))
        check("G-2 K2: S3 `extend T3` + a parameterize test is still a finding (a person's S3 word needs a deviation)",
              has(found, "shape `parameterize` departs from S3", "TC-004 (S3 fit `extend T3` allows extend, reuse, consolidate)"), str(found))
        check_eq("G-2: the vocabulary row itself", SP._words()[1]["new"], ["new", "parameterize", "consolidate"])
    finally:
        cleanup(root)


def kg2_two_lists_in_three_places():
    # the two carriers' words are the row `consolidates-means-two-lists` of design/role-rules.json; the finding's text stays here
    root = temp_dir("qa-s5grp-g2b-")
    try:
        plan = mutate(good_plan(), lambda p: p["tests"][0].__setitem__("shape", "consolidate"))
        put(root, SP.PLAN_REL, json.dumps(plan))
        finding = next(f for f in SP.check_report(root, Fake(("TC-1", "TC-2", "TC-3")))[0] if "`consolidates`" in f)
        check_in("G-2 K5: the finding of an empty `consolidates` carries the phrase", TWO_LISTS, finding)
        check_in("G-2 K5: ... after its fix, in one line", "fix: list the tests it merges (", finding)
    finally:
        cleanup(root)


def kfix_one_printer_and_the_vocabulary():
    import handoff
    import s5_precheck as PC
    check("fix 4: every GROUP_SHAPES entry is a word of vocabulary `test_shapes`",
          set(SP.GROUP_SHAPES) <= set(handoff.vocabulary()["test_shapes"]), str(SP.GROUP_SHAPES))
    check("fix 4 (negative control): a shape outside the vocabulary is caught by the same comparison",
          not {"no-such-shape"} <= set(handoff.vocabulary()["test_shapes"]))
    hint = {"check": "plan", "message": "2 tests\nin one file", "fix": "write one\ntest", "level": "hint"}

    def printed(call):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            call()
        return buf.getvalue()
    direct = printed(lambda: SP.print_hints([hint]))
    via_report = printed(lambda: PC.report({"ok": True, "findings": [], "hints": [hint], "notes": [], "cases": []}))
    check_in("fix 2: report prints the lines of the shared printer", direct, via_report)
    check_eq("fix 2: a newline in a hint is one line on both paths", direct,
             "hint: [plan] 2 tests in one file\n  consider: write one test\n")


def main():
    k1_the_real_plan()
    kfix_one_printer_and_the_vocabulary()
    k3_apart_reason()
    k3b_red_as_a_parameter()
    k3c_slice_shows_the_reason()
    k4_field_form()
    k5_id_list()
    k6_helpers()
    k8_check_command()
    k9_the_key()
    kg2_fit_new_parameterize()
    kg2_two_lists_in_three_places()
    finish("test_s5_plan_grouping")


if __name__ == "__main__":
    main()
