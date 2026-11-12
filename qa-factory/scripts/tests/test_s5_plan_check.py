#!/usr/bin/env python3
"""SC1-14 A1b: the plan check, the window slice, the chain of plan reviews and the remarks.

`s5_plan.check` names every gap of `work/s5-plan.json` at once, before the code critic sees the plan; `window_slice` is the part
of the plan one window is written against; `reviews` / `remarks_of` read the chain of the critic's reviews (the one reader);
`remark_rows_missing` is the one implementation of "a row for every remark". Every key names the mutation it kills (spec t-1246
section 5, A1b: M5 a Then in two tests, M6 an S3 level of None read as a match, M7 the limit 300 read as `<`, M8 the blocker of a
non-last review kept, M9 a test over two windows passing).
"""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CT  # noqa: E402
import detector_verdict as DV  # noqa: E402
import s5_plan as SP  # noqa: E402

import test_s5_plan as BASE  # noqa: E402  (its fixtures: put, refusal, s5_story; its checks run only under its own __main__)

put, refusal = BASE.put, BASE.refusal


CUT = [{"index": 1, "surface": "other", "scope": ["TC-1", "TC-2"]}, {"index": 2, "surface": "other", "scope": ["TC-3"]}]


class Fake:
    """What `check` asks a controller: the state, the S5 scope, the project root and the windows the controller cuts
    (`windows`: the cut the test wants the check to see; the real cut is `Controller.s5_windows_for`, FJ-B)."""

    def __init__(self, scope, project=None, derived=True, windows=None):
        self.scope, self.project, self.derived = list(scope), project, derived
        self.windows = CUT if windows is None else windows

    def state(self):
        return {}

    def stage_scope(self, stage, state=None):
        return {"scope": list(self.scope), "derived": self.derived, "reason": "" if self.derived else "no dispositions"}

    def s5_windows_for(self, plan, state=None, scope=None, mapping=None):
        if isinstance(self.windows, Exception):
            raise self.windows
        return [dict(window) for window in self.windows], {"grown": [], "why": "a fake cut"}

    def _project_root(self):
        return self.project


def case_row(case, thens=1, fit="new", level="api"):
    return {"case": case, "requirements": ["R-1"],
            "s3": {"row": "TS-" + case[-1], "level": level, "fit": fit, "oracle": "requirement:R-1"},
            "thens": [{"n": n, "text": f"outcome {n}"} for n in range(1, thens + 1)], "remainders": []}


def test_row(identifier, cases, thens, **extra):
    row = {"id": identifier, "file": f"tests/test_{identifier.lower()}.py", "function": "test_it", "cases": list(cases),
           "thens": list(thens), "level": "api", "shape": "new", "extends": "", "consolidates": [], "params": None,
           "uses": [], "data": "own", "assert": "the response is 200", "deviation": []}
    row.update(extra)
    return row


def good_plan():
    """Three cases (the fake cut puts TC-1 and TC-2 in window 1 and TC-3 in window 2); one new test per case (TC-1 has two Then
    clauses). The plan holds no window."""
    return {"schema": 1, "scope_hash": "s", "gate_a_plan_hash": "g",
            "cases": [case_row("TC-1", thens=2), case_row("TC-2"), case_row("TC-3")],
            "tests": [test_row("T-1", ["TC-1"], ["TC-1#1", "TC-1#2"]), test_row("T-2", ["TC-2"], ["TC-2#1"]),
                      test_row("T-3", ["TC-3"], ["TC-3#1"])],
            "fixtures": [], "refactor": ""}


SCOPE = ("TC-1", "TC-2", "TC-3")


def run(root, plan, project=None, scope=SCOPE, windows=None):
    put(root, SP.PLAN_REL, json.dumps(plan))
    return SP.check_report(root, Fake(scope, project, windows=windows))


def findings_of(root, plan, **kw):
    return run(root, plan, **kw)[0]


def has(findings, *needles):
    return any(all(n in f for n in needles) for f in findings)


def mutate(plan, fn):
    plan = copy.deepcopy(plan)
    fn(plan)
    return plan


# --- (a) the cases ----------------------------------------------------------------------------------------

def k1_cases():
    root = temp_dir("qa-s5chk-a-")
    try:
        findings, notes = run(root, good_plan())
        check_eq("K1: the good plan has no finding", findings, [])
        check_eq("K1: ... and every finding is one physical line with a fix (the detector contract) - none to look at", notes, [])
        check_eq("K1: SP.check is the findings of check_report", SP.check(root, Fake(SCOPE)), [])
        f = findings_of(root, mutate(good_plan(), lambda p: p["cases"].pop()))
        check("K1 (a): a case of the scope with no row is a finding", has(f, "case TC-3", "has no row"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["cases"].append(case_row("TC-9"))))
        check("K1 (a): a row of a case outside the scope is a finding", has(f, "case TC-9", "not in the S5 scope"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["cases"].append(case_row("TC-2"))))
        check("K1 (a): a case row twice is a finding", has(f, "case TC-2", "appears twice"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["cases"][1].update(thens=[])))
        check("K1 (a): a case with no Then clause is a finding", has(f, "case TC-2", "no Then clause"))
        f = findings_of(root, mutate(good_plan(), lambda p: p.update(cases="x")))
        check("K1 (a): cases that is not a list is a finding, nothing raises", has(f, "`cases` is not a list"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["cases"].append("junk")))
        check("K1 (a): a row that is not a row is a finding", has(f, "cases[3] is not a row"))
    finally:
        cleanup(root)


# --- (b) the Then clauses ---------------------------------------------------------------------------------

def k2_thens():
    root = temp_dir("qa-s5chk-b-")
    try:
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(thens=["TC-1#1"])))
        check("K2 (b): a Then in no test and no remainder is a finding", has(f, "case TC-1 Then 2", "no test and in no remainder"))

        def both(p):
            p["cases"][0]["remainders"] = [{"then": 2, "reason": "impossible", "detail": "d"}]
        f = findings_of(root, mutate(good_plan(), both))
        check("K2 (b) M5: a Then in a test AND in the remainders is a finding - both", has(f, "case TC-1 Then 2", "both"))

        def moved(p):
            p["tests"][0]["thens"] = ["TC-1#1"]
            both(p)
        check_eq("K2 (b): a Then only in the remainders is no finding", findings_of(root, mutate(good_plan(), moved)), [])

        def two_tests(p):
            p["tests"][1]["cases"] = ["TC-2", "TC-1"]
            p["tests"][1]["thens"] = ["TC-2#1", "TC-1#2"]
        f = findings_of(root, mutate(good_plan(), two_tests))
        check("K2 (b) M5: a Then in two tests is a finding", has(f, "case TC-1 Then 2", "2 tests (T-1 and T-2)"))

        def twice(p):
            p["tests"][0]["thens"] = ["TC-1#1"]
            p["cases"][0]["remainders"] = [{"then": 2, "reason": "impossible", "detail": "d"}] * 2
        f = findings_of(root, mutate(good_plan(), twice))
        check("K2 (b): a remainder twice is a finding", has(f, "case TC-1 Then 2", "remainder 2 times"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(thens=["TC-1#1", "TC-1#2", "TC-1#7"])))
        check("K2 (b): a reference to a Then the case does not have is a finding", has(f, "TC-1#7", "a Then the case does not have"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(thens=["TC-1#1", "TC-1#2", "TC-2#1"])))
        check("K2 (b): a Then of a case the test does not list is a finding", has(f, "TC-2#1", "does not list TC-2"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(thens=["nonsense"])))
        check("K2 (b): a reference that is not <case>#<n> is a finding", has(f, "'nonsense'", "not `<case>#<n>`"))

        def bad_remainder(p):
            p["tests"][0]["thens"] = ["TC-1#1"]
            p["cases"][0]["remainders"] = [{"then": 2, "reason": "because", "detail": "d"}]
        f = findings_of(root, mutate(good_plan(), bad_remainder))
        check("K2 (b): a remainder reason outside contract.UNRESOLVED_REASONS is a finding", has(f, "reason 'because'", "impossible"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["cases"][0].update(remainders=[{"then": 9, "reason": "impossible"}])))
        check("K2 (b): a remainder naming a Then the case lacks is a finding", has(f, "remainders[0] names Then 9"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["cases"][0].update(remainders="x")))
        check("K2 (b): remainders that is not a list is a finding", has(f, "`remainders` is not a list"))
    finally:
        cleanup(root)


# --- (c) (d) shape and level against S3; E17 --------------------------------------------------------------

def k3_shape_and_level_against_s3():
    root = temp_dir("qa-s5chk-cd-")
    try:
        def extend_fit(**changes):      # t-1502 G-2: `fit: new` now allows `parameterize`, so the departure is from an S3 `extend` word
            def apply(p):
                p["cases"][0]["s3"]["fit"] = "extend T1"
                p["tests"][0].update(**changes)
            return mutate(good_plan(), apply)
        f = findings_of(root, extend_fit(shape="parameterize"))
        check("K3 (c): a shape the S3 fit does not allow, with no deviation, is a finding", has(f, "test T-1", "shape `parameterize`", "TC-1", "no deviation"))
        check_eq("K3 (c): ... and the same shape with a `fit` deviation is none",
                 findings_of(root, extend_fit(shape="parameterize", deviation=[{"from": "fit", "reason": "r"}])), [])
        f = findings_of(root, extend_fit(shape="parameterize", deviation=[{"from": "level", "reason": "r"}]))
        check("K3 (c): a deviation of the OTHER kind does not cover a shape departure", has(f, "shape `parameterize`", "no deviation"))
        check_eq("K3 (c): `consolidate` is allowed by every fit (and names what it merges)",
                 findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(shape="consolidate", consolidates=["T-2"]))), [])
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(shape="grow")))
        check("K3 (c): a shape that is no word of the vocabulary is a finding", has(f, "shape 'grow'", "reuse, extend, parameterize"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(level="api2")))
        check("K3 (d): a level outside PLAN_LEVELS is a finding", has(f, "level 'api2'", "unit, component, api"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(level="e2e-ui")))
        check("K3 (d): a level other than the S3 one, with no deviation, is a finding", has(f, "level `e2e-ui` departs from S3", "TC-1"))
        check_eq("K3 (d): ... with a `level` deviation it is none",
                 findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(level="e2e-ui", deviation=[{"from": "level", "reason": "r"}]))), [])
        # E17 / M6: S3 says nothing -> "not checked", a note, never a pass and never a finding
        def silent(p):
            p["cases"][0]["s3"].update(level=None, fit=None)
            p["tests"][0].update(level="e2e-ui", shape="parameterize")
        findings, notes = run(root, mutate(good_plan(), silent))
        check_eq("K3 (E17, M6): an S3 row with no level and no fit makes no finding", [x for x in findings if "TC-1" in x], [])
        check("K3 (E17, M6): ... and the check says out loud it did not run", has(notes, "not checked", "shape against the S3 `fit` for TC-1")
              and has(notes, "level against the S3 `level` for TC-1"))
        findings, notes = run(root, mutate(good_plan(), lambda p: p["cases"][0]["s3"].update(fit="manual walk")))
        check("K3 (E17): a fit word the plan does not know is a note, not a finding", findings == [] and has(notes, "TC-1 (manual)"))
        check_eq("K3 (E17): a plan whose S3 says everything has no note", run(root, good_plan())[1], [])
        # a test over two cases is compared with BOTH rows
        def two(p):
            p["cases"][1]["s3"]["fit"] = "extend tests/x.py::t"
            p["tests"][0]["cases"] = ["TC-1", "TC-2"]
            p["tests"][0]["thens"] = ["TC-1#1", "TC-1#2", "TC-2#1"]
            p["tests"].pop(1)
        f = findings_of(root, mutate(good_plan(), two))
        check("K3 (c): a shape is compared with every case the test proves", has(f, "test T-1", "shape `new` departs", "TC-2") and not has(f, "TC-1 (S3"))
    finally:
        cleanup(root)


# --- (d') extends exists (E16) ----------------------------------------------------------------------------

def k4_extends():
    project = temp_project("qa-s5chk-d-")
    root = temp_dir("qa-s5chk-d-task-")
    try:
        put(project, "tests/test_x.py", "def test_x():\n    assert 1\n\n\nclass TestK:\n    def test_m(self):\n        assert 1\n")
        put(project, "tests/test_bad.py", "def (:\n")

        def ext(spec, shape="extend"):
            return mutate(good_plan(), lambda p: p["tests"][0].update(
                shape=shape, extends=spec, deviation=[{"from": "fit", "reason": "r"}]))
        for spec in ("tests/test_x.py::test_x", "tests/test_x.py::TestK::test_m", "tests\\test_x.py::test_x"):
            check_eq(f"K4 (d): {spec!r} exists", findings_of(root, ext(spec), project=project), [])
        check_eq("K4 (d): `reuse` is looked up too", findings_of(root, ext("tests/test_x.py::test_x", "reuse"), project=project), [])
        f = findings_of(root, ext("tests/test_x.py::test_gone"), project=project)
        check("K4 (d): a function that is not in the file is a finding with the path", has(f, "test T-1", "tests/test_x.py::test_gone", "no test function test_gone"))
        f = findings_of(root, ext("tests/test_nope.py::test_x"), project=project)
        check("K4 (d): a file that is not there is a finding with the path", has(f, "tests/test_nope.py", "not under the project root"))
        check("K4 (d): an empty `extends` is a finding", has(findings_of(root, ext(""), project=project), "`extends` is empty"))
        check("K4 (d): no `::` is a finding", has(findings_of(root, ext("tests/test_x.py"), project=project), "no `::<function>`"))
        findings, notes = run(root, ext("src/Calc.java::Calc.adds"), project=project)
        check("K4 (d, E16): another language is 'not checked', a note and no finding",
              not has(findings, "extends") and has(notes, "not checked", "Calc.java", "not a Python file"))
        findings, notes = run(root, ext("tests/test_bad.py::test_x"), project=project)
        check("K4 (d): a file that does not parse is 'not checked'", not has(findings, "extends") and has(notes, "could not be parsed"))
        findings, notes = run(root, ext("tests/test_x.py::test_x"), project=None)
        check("K4 (d): no project is 'not checked', never a pass in silence", not has(findings, "extends") and has(notes, "project is not found"))
        check("K4 (d): a shape that does not extend asks nothing of `extends`", findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(extends="gone.py::t")), project=project) == [])
        check("K4 (e): consolidate names what it merges", has(findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(shape="consolidate"))), "`consolidates`"))
    finally:
        cleanup(project)
        cleanup(root)


# --- (g) data, (i) ids, (k) windows -----------------------------------------------------------------------

def k5_words_ids_windows():
    root = temp_dir("qa-s5chk-ik-")
    try:
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(data="luck")))
        check("K5 (g): a data strategy outside the vocabulary is a finding", has(f, "data 'luck'", "own, run_tag, seeded"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][1].update(id="T-1")))
        check("K5 (i): a test id used twice is a finding", has(f, "test T-1", "used twice"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][1].pop("id")))
        check("K5 (i): a test without an id is a finding", has(f, "has no `id`"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(cases=["TC-1", "TC-8"])))
        check("K5 (i): a test over a case outside the scope is a finding", has(f, "test T-1", "TC-8", "outside the S5 scope"))
        f = findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(cases=[])))
        check("K5 (i): a test over no case is a finding", has(f, "test T-1", "`cases` is not a non-empty list"))
        f = findings_of(root, mutate(good_plan(), lambda p: p.update(tests="x")))
        check("K5: tests that is not a list is a finding", has(f, "`tests` is not a list"))

        def across(p):
            p["tests"][1]["cases"] = ["TC-2", "TC-3"]
            p["tests"][1]["thens"] = ["TC-2#1", "TC-3#1"]
            p["tests"].pop()
        f = findings_of(root, mutate(good_plan(), across))
        check("a test across two written windows is a finding", has(f, "test T-2 covers cases of windows 1 and 2, both already written"))
        check("a test across two written windows is a finding: ... and the way out", has(f, "fix: split the test; written windows are not merged"))

        def whole(p):       # one test over all three cases: the group of the plan
            p["tests"] = [test_row("T-1", ["TC-1", "TC-2", "TC-3"], ["TC-1#1", "TC-1#2", "TC-2#1", "TC-3#1"])]
        for surface in ("other", "ui"):
            over = [{"index": 1, "surface": surface, "scope": ["TC-1", "TC-2", "TC-3"], "over_cap": True, "cap": 2}]
            f, notes = run(root, mutate(good_plan(), whole), windows=over)
            check_eq(f"a group over the cap is a note, not a finding ({surface.upper() if surface == 'ui' else surface})", f, [])
            check_in(f"a group over the cap is a note: the {surface} cap and the tying test are named",
                     f"window 1: 3 cases over the {surface} cap of 2, kept whole because test(s) T-1 tie them", " | ".join(notes))
        fine = [{"index": 1, "surface": "other", "scope": ["TC-1", "TC-2", "TC-3"]}]
        check_eq("a group at the cap is clean: no finding and no note", run(root, mutate(good_plan(), whole), windows=fine), ([], []))
        f, notes = run(root, mutate(good_plan(), whole), windows=RuntimeError("the state cannot be read"))
        check_eq("an unreadable cut checks nothing and says so: no finding, one note",
                 (f, [n for n in notes if n.startswith("not checked: the fit of the tests to the windows")] != []), ([], True))
        check_eq("two cases of ONE window in a test are fine", findings_of(root, mutate(good_plan(), lambda p: (
            p["tests"][0].update(cases=["TC-1", "TC-2"], thens=["TC-1#1", "TC-1#2", "TC-2#1"]), p["tests"].pop(1)))), [])
    finally:
        cleanup(root)


# --- (z) the 300-character limits AT and BEYOND (E14, M7) -------------------------------------------------

def k6_limits():
    root = temp_dir("qa-s5chk-z-")
    try:
        slots = (("assert", lambda p, v: p["tests"][0].update(**{"assert": v}), "`assert`"),
                 ("deviation reason", lambda p, v: p["tests"][0].update(shape="parameterize", deviation=[{"from": "fit", "reason": v}]),
                  "`deviation[0].reason`"),
                 ("remainder detail", lambda p, v: (p["tests"][0].update(thens=["TC-1#1"]),
                                                    p["cases"][0].update(remainders=[{"then": 2, "reason": "impossible", "detail": v}])),
                  "`remainders[0].detail`"),
                 ("refactor", lambda p, v: p.update(refactor=v), "`refactor`"))
        for label, put_value, name in slots:
            at = findings_of(root, mutate(good_plan(), lambda p: put_value(p, "x" * 300)))
            beyond = findings_of(root, mutate(good_plan(), lambda p: put_value(p, "x" * 301)))
            check_eq(f"K6 (E14, M7): {label} of 300 characters passes", at, [])
            check(f"K6 (E14, M7): {label} of 301 characters is a finding that says 301 and 300",
                  has(beyond, name, "301 characters", "limit is 300"))
        check("K6 (E14): characters, not bytes - 300 two-byte characters pass", findings_of(root, mutate(good_plan(), lambda p: p.update(refactor="é" * 300))) == [])
        check("K6: an `assert` that is not text is a finding", has(findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(**{"assert": ["a"]}))), "`assert` is not text"))
        check("K6: an empty `assert` is a finding", has(findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(**{"assert": ""}))), "`assert` is empty"))
        check_eq("K6: an empty refactor is 'no refactor promised', not a finding", findings_of(root, mutate(good_plan(), lambda p: p.update(refactor=""))), [])
        check("K6: a deviation that does not say fit|level is a finding", has(findings_of(root, mutate(good_plan(), lambda p: p["tests"][0].update(deviation=[{"from": "count", "reason": "r"}]))), "deviation[0] does not say"))
    finally:
        cleanup(root)


# --- all at once, and the plan that is not there -----------------------------------------------------------

def k7_all_at_once_and_absent():
    root = temp_dir("qa-s5chk-all-")
    try:
        def many(p):
            p["tests"][0]["thens"] = ["TC-1#1"]                  # (b)
            p["tests"][1]["shape"] = "grow"                      # (c)
            p["tests"][2]["data"] = "luck"                       # (g)
            p["cases"][1]["thens"] = []                          # (a)
            p["refactor"] = "y" * 301                            # (z)
        findings = findings_of(root, mutate(good_plan(), many))
        check("K7: five different gaps are all named in ONE run", len(findings) >= 5 and has(findings, "TC-1 Then 2") and has(findings, "shape 'grow'")
              and has(findings, "data 'luck'") and has(findings, "case TC-2", "no Then") and has(findings, "`refactor`"))
        check("K7: every finding is ONE physical line with a ' — fix: ' (the detector contract)",
              all("\n" not in x and " — fix: " in x for x in findings))
        out = SP.check_report(root, Fake(SCOPE, derived=False))
        check("K7 (AR-28): a scope that cannot be derived is a finding", has(out[0], "scope cannot be derived", "no dispositions"))
        (root / SP.PLAN_REL).unlink()
        out = SP.check_report(root, Fake(SCOPE))
        check("K7: no plan file is a finding with the door", has(out[0], "does not exist", "--init"))
        out = SP.check_report(root, Fake(()))
        check_eq("K7 (E7): an empty scope owes no plan - no finding, a note", (out[0], has(out[1], "no plan is owed")), ([], True))
        put(root, SP.PLAN_REL, b"{half")
        out = SP.check_report(root, Fake(SCOPE))
        check("K7 (AR-28): an unreadable plan is a finding, not a pass and not a traceback", len(out[0]) == 1 and has(out[0], SP.PLAN_REL, "--init"))
    finally:
        cleanup(root)


# --- the review chain ------------------------------------------------------------------------------------

FORM = """schema_version: 1
contract: s5-critic-plan-to-automator
review:
  outcome: {outcome}
remarks:
{remarks}"""


def remark_text(identifier, kind, case="-", test="-", then="-", check_id="K4"):
    return (f"  - id: {identifier}\n    case: {case}\n    test: {test}\n    then: {then}\n    kind: {kind}\n    check: {check_id}\n"
            f"    problem: problem {identifier}\n    expected: expected {identifier}\n    fix: fix {identifier}\n")


def write_form(root, dispatch, outcome, *remarks):
    text = FORM.format(outcome=outcome, remarks="".join(remarks))
    put(root, f"work/handoffs/{dispatch}.yaml", text if remarks else text.replace("remarks:\n", "remarks: []\n"))


def critic(identifier, status="accepted", purpose=CT.S5_PLAN, role="qa-code-critic", stage="S5"):
    return {"id": identifier, "stage": stage, "role": role, "status": status, "request_binding": {"purpose": purpose}}


def state_of(*records):
    return {"dispatches": {r["id"]: r for r in records}}


def k8_reviews_and_remarks():
    root = temp_dir("qa-s5chk-rev-")
    try:
        put(root, SP.PLAN_REL, json.dumps(good_plan()))
        state = state_of(critic("C1"), critic("C2"))
        check_eq("K8: no form and no receipt - the elements are there and unreadable, nothing is skipped",
                 [(e["dispatch"], bool(e["unreadable"])) for e in SP.reviews(root, state)], [("C1", True), ("C2", True)])
        write_form(root, "C1", "blocked", remark_text("PR-1", "blocker", case="TC-1", test="T-1"), remark_text("PR-2", "remark"))
        SP.stamp_review(root, "C1")
        write_form(root, "C2", "approved")
        SP.stamp_review(root, "C2")
        chain = SP.reviews(root, state)
        check_eq("K8: both reviews are readable", [e["unreadable"] for e in chain], ["", ""])
        check_eq("K8: outcomes in the order of the journal", [e["outcome"] for e in chain], ["blocked", "approved"])
        check_eq("K8: the first review's remarks, normalised (a dash is None)",
                 [(r["id"], r["kind"], r["case"], r["test"], r["then"], r["review"]) for r in chain[0]["remarks"]],
                 [("PR-1", "blocker", "TC-1", "T-1", None, "C1"), ("PR-2", "remark", None, None, None, "C1")])
        check_eq("K8: the receipt is the stamp_review line", (chain[0]["plan_sha256"], chain[0]["rows_sha"]),
                 (SP.stamp_review(root, "C1")["plan_sha256"], SP.rows_sha(good_plan())))
        check_eq("K8: an approved review with `remarks: []` has none", chain[1]["remarks"], [])
        # M8: blocked -> re-look approved: the mended blocker stays out, the remark of the first review goes on
        check_eq("K8 (M8): blocked -> re-look approved: the fixed blocker stays out, the remark of review 1 goes to the windows",
                 [r["id"] for r in SP.remarks_of(root, state)], ["PR-2"])
        write_form(root, "C2", "blocked", remark_text("PR-3", "blocker", case="TC-2"))
        SP.stamp_review(root, "C2")
        check_eq("K8 (M8): blocked -> blocked again: the blocker of the LAST review is kept, the first one's is not",
                 [r["id"] for r in SP.remarks_of(root, state)], ["PR-2", "PR-3"])
        check_eq("K8: one review: its blocker is the last review's, so it is kept",
                 [r["id"] for r in SP.remarks_of(root, state_of(critic("C1")))], ["PR-1", "PR-2"])
        check_eq("K8: no review, no remarks", SP.remarks_of(root, state_of()), [])
        # only accepted critic dispatches of the PLAN kind count
        other = state_of(critic("C1"), critic("W1", purpose="repair_verify"), critic("C3", status="rejected"),
                         critic("A1", role="qa-automator"), critic("S4", stage="S4"))
        check_eq("K8: a window critic, a rejected one, an automator and another stage are not the chain",
                 [e["dispatch"] for e in SP.reviews(root, other)], ["C1"])
        # unreadable parts are named, and remarks_of refuses (E28)
        write_form(root, "C2", "maybe")
        SP.stamp_review(root, "C2")
        check_in("K8: an outcome outside plan_verdicts is unreadable", "review.outcome", SP.reviews(root, state)[1]["unreadable"])
        check_in("K8 (E28): remarks_of refuses a chain it cannot read, naming the dispatch", "C2", refusal(lambda: SP.remarks_of(root, state)))
        write_form(root, "C2", "approved", remark_text("PR-4", "note"))
        check_in("K8: a remark of a kind outside plan_remark_kinds is unreadable", "kind 'note'", SP.reviews(root, state)[1]["unreadable"])
        put(root, "work/handoffs/C2.yaml", "review:\n  outcome: approved\nremarks: nope\n")
        check_in("K8: remarks that is not a list is unreadable", "`remarks` is not a list", SP.reviews(root, state)[1]["unreadable"])
        put(root, "work/handoffs/C2.yaml", "review:\n  outcome: approved\n")
        check_eq("K8: remarks absent reads as the empty list (the contract's 'or the empty list')", SP.reviews(root, state)[1]["remarks"], [])
        (root / SP.REVIEWS_REL).write_bytes(b"{broken")
        check_in("K8: a broken receipt file is unreadable for every review", "cannot be read as a JSON list", SP.reviews(root, state)[0]["unreadable"])
        (root / SP.REVIEWS_REL).unlink()
        check_in("K8: a missing receipt file is unreadable", "does not exist", SP.reviews(root, state)[0]["unreadable"])
        check("K8 (AR-28): a state that is not a mapping is refused", bool(refusal(lambda: SP.reviews(root, None))) and bool(refusal(lambda: SP.reviews(root, {"dispatches": []}))))
    finally:
        cleanup(root)


def k9_remark_rows_missing():
    remarks = [{"id": "PR-1"}, {"id": "PR-2"}, {"id": "PR-3"}]
    rows = [{"id": "PR-1", "row": "applied"}, {"id": "PR-2", "row": "applied"}, {"id": "PR-2", "row": "not_applicable"}]
    check_eq("K9: no row (PR-3) and two rows (PR-2) are missing, one row (PR-1) is not", SP.remark_rows_missing(remarks, rows), ["PR-2", "PR-3"])
    check_eq("K9: exactly one row each - nothing missing", SP.remark_rows_missing(remarks, [{"id": i} for i in ("PR-1", "PR-2", "PR-3")]), [])
    check_eq("K9: no rows at all - every id", SP.remark_rows_missing(remarks, []), ["PR-1", "PR-2", "PR-3"])
    check_eq("K9: rows that are not a list have no rows", SP.remark_rows_missing(remarks[:1], "x"), ["PR-1"])
    check_eq("K9: a row that is not a row, or has no id, counts for nothing", SP.remark_rows_missing(remarks[:1], ["PR-1", {"row": "applied"}, None]), ["PR-1"])
    check_eq("K9: no remarks, nothing to answer", SP.remark_rows_missing([], [{"id": "PR-9"}]), [])
    check_eq("K9: an id is named once", SP.remark_rows_missing([{"id": "PR-1"}, {"id": "PR-1"}], []), ["PR-1"])
    check_eq("K9: ids as text - a number id 1 equals '1'", SP.remark_rows_missing([{"id": 1}], [{"id": "1"}]), [])


# --- the window slice ---------------------------------------------------------------------------------------

def k10_window_slice():
    root = temp_dir("qa-s5chk-slice-")
    try:
        # a real story: the windows of a slice are the controller's cut (cap 2: TC-1 and TC-2 fill window 1, TC-3 opens window 2)
        BASE.s5_story(root, cases=SCOPE, with_case_files=True)
        put(root, "qa-factory/config.json", json.dumps({"dispatch": {"ui_window_cases": 2, "api_window_cases": 2}}))
        plan = good_plan()
        plan["cases"][0]["remainders"] = []
        put(root, SP.PLAN_REL, json.dumps(plan))
        state = state_of(critic("C1"))
        write_form(root, "C1", "approved_with_remarks",
                   remark_text("PR-1", "remark", case="TC-3", test="T-3"),      # window 2
                   remark_text("PR-2", "remark"),                               # global
                   remark_text("PR-3", "remark", case="TC-1"),                  # window 1
                   remark_text("PR-4", "remark", case="TC-99"),                 # names a case the plan lacks
                   remark_text("PR-5", "remark", test="T-2"),                   # by test only: window 1
                   remark_text("PR-6", "remark", then="TC-3#1"),                # by Then only: window 2
                   remark_text("PR-7", "remark", test="T-77"))                  # names a test the plan lacks
        SP.stamp_review(root, "C1")
        one, two = SP.window_slice(root, 1, state), SP.window_slice(root, 2, state)
        check_eq("K10: window 1 holds its cases", [r["case"] for r in one["cases"]], ["TC-1", "TC-2"])
        check_eq("K10: ... the tests that touch them", [t["id"] for t in one["tests"]], ["T-1", "T-2"])
        check_eq("K10: window 2 holds its case and test", ([r["case"] for r in two["cases"]], [t["id"] for t in two["tests"]]), (["TC-3"], ["T-3"]))
        check_eq("K10: the windows the plan has", one["windows"], [1, 2])
        check_eq("K10: requirements are the union, in order", one["requirements"], ["R-1"])
        check_eq("K10 (E10): the global remark is in EVERY window, the placed ones only in theirs",
                 [r["id"] for r in one["remarks"]], ["PR-2", "PR-3", "PR-4", "PR-5", "PR-7"])
        check_eq("K10: ... window 2", [r["id"] for r in two["remarks"]], ["PR-1", "PR-2", "PR-4", "PR-6", "PR-7"])
        check_eq("K10: a remark that names nothing the plan has is 'unplaced' and goes everywhere (never lost)",
                 {r["id"]: r["placement"] for r in one["remarks"]}, {"PR-2": "global", "PR-3": "window", "PR-4": "unplaced", "PR-5": "window", "PR-7": "unplaced"})
        # a test over two cases of ONE window is in that window's slice once
        plan2 = mutate(good_plan(), lambda p: (p["tests"][0].update(cases=["TC-1", "TC-2"], thens=["TC-1#1", "TC-1#2", "TC-2#1"]), p["tests"].pop(1)))
        put(root, SP.PLAN_REL, json.dumps(plan2))
        SP.stamp_review(root, "C1")
        check_eq("K10: a shared test appears once", [t["id"] for t in SP.window_slice(root, 1, state)["tests"]], ["T-1"])
        # remainders, E41 and the markdown
        plan3 = good_plan()
        plan3["tests"] = [t for t in plan3["tests"] if t["id"] != "T-3"]
        plan3["cases"][2]["remainders"] = [{"then": 1, "reason": "impossible", "detail": "no stand"}]
        put(root, SP.PLAN_REL, json.dumps(plan3))
        SP.stamp_review(root, "C1")
        only = SP.window_slice(root, 2, state_of())
        check_eq("K10: remainders are flat, with the case", only["remainders"], [{"then": 1, "reason": "impossible", "detail": "no stand", "case": "TC-3"}])
        text = SP.render_slice(only)
        check_in("K10 (E41): a window with no tests says so", "no tests planned for this window: write the remainders", text)
        check_in("K10 (E9): a window with no remarks says so", "no remarks for this window", text)
        check_in("K10: the markdown names the remainder", "TC-3 Then 1: impossible - no stand", text)
        full = SP.render_slice(SP.window_slice(root, 1, state))
        check_in("K10: the markdown carries a remark whole", "PR-2 [remark] the whole plan (K4; global): problem PR-2 Expected: expected PR-2 Fix: fix PR-2", full)
        check_in("K10: ... and a test row", "### T-1 - tests/test_t-1.py::test_it (new, api, data own)", full)
        check_in("K10: a window the plan does not have is a ValueError naming the ones it has", "expected one of 1, 2", refusal_value(lambda: SP.window_slice(root, 3, state)))
        k10b_slice_by_the_cut(root, state)
        (root / SP.PLAN_REL).unlink()
        check_in("K10: no plan, no slice - the door is named", "--init", refusal(lambda: SP.window_slice(root, 1, state)))
        put(root, SP.PLAN_REL, json.dumps(plan3))
        (root / SP.REVIEWS_REL).unlink()
        check("K10 (AR-28): a chain that cannot be read refuses the slice instead of making it without remarks", bool(refusal(lambda: SP.window_slice(root, 1, state))))
    finally:
        cleanup(root)


def k10b_slice_by_the_cut(root, state):
    """The slice reads the controller's cut (cap 2 in `root`): a row's own `window` is no word, a slice is asked by cases, a window
    over its cap or grown says so. KILLS: MJ16 (a row's window key read again), MJ20 (the placed remarks of one window in another)."""
    plan = good_plan()
    for row, stray in zip(plan["cases"], (2, 2, 1)):
        row["window"] = stray       # the old skeleton's key: nothing reads it any more
    put(root, SP.PLAN_REL, json.dumps(plan))
    SP.stamp_review(root, "C1")
    check_eq("a row's window key is not read", ([r["case"] for r in SP.window_slice(root, 1, state)["cases"]],
                                               SP.window_slice(root, 2, state)["windows"]), (["TC-1", "TC-2"], [1, 2]))
    by = SP.window_slice(root, cases=["TC-1"], state=state)
    check_eq("slice by cases", (by["window"], [r["case"] for r in by["cases"]], [t["id"] for t in by["tests"]], by["missing"]),
             (1, ["TC-1"], ["T-1"], []))
    ids = [r["id"] for r in by["remarks"]]
    check("slice by cases: the placed remarks of another window stay out (MJ20)", "PR-1" not in ids and "PR-3" in ids)
    two = SP.window_slice(root, cases=["TC-2", "TC-3"], state=state)
    check_eq("slice by cases over two windows has no number", two["window"], None)
    check_in("slice by cases over two windows has no number: the header names the cases", "# S5 plan - cases TC-2, TC-3", SP.render_slice(two))
    check_in("a case not in the plan is said so", "TC-77 (not in the plan)", SP.render_slice(SP.window_slice(root, cases=["TC-1", "TC-77"], state=state)))
    check("window_slice takes exactly one of n and cases", bool(refusal_value(lambda: SP.window_slice(root, state=state))) and
          bool(refusal_value(lambda: SP.window_slice(root, 1, state, cases=["TC-1"]))))
    whole = good_plan()
    whole["tests"] = [test_row("T-1", ["TC-1", "TC-2", "TC-3"], ["TC-1#1", "TC-1#2", "TC-2#1", "TC-3#1"])]
    put(root, SP.PLAN_REL, json.dumps(whole))
    SP.stamp_review(root, "C1")
    over = SP.window_slice(root, 1, state)
    check_eq("the slice of an over-cap window says so", (over["over_cap"], over["cap"], over["size"]), (True, 2, 3))
    check_in("the slice of an over-cap window says so: the line",
             "This window holds 3 cases, over the other window cap of 2: test(s) T-1 cover them together, and a test is written in one window.",
             SP.render_slice(over))
    written = {"A1": {"id": "A1", "stage": "S5", "role": "qa-automator", "status": "accepted", "scope": ["TC-1", "TC-2"]}}
    grown_plan = good_plan()
    grown_plan["tests"] = [test_row("T-1", ["TC-1", "TC-3"], ["TC-1#1", "TC-1#2", "TC-3#1"]), grown_plan["tests"][1]]
    put(root, SP.PLAN_REL, json.dumps(grown_plan))
    SP.stamp_review(root, "C1")
    grown = SP.window_slice(root, 1, {"dispatches": dict(state["dispatches"], **written)})
    check_eq("the slice of a grown window names the new cases", grown["grown"], ["TC-3"])
    check_in("the slice of a grown window names the new cases: the line",
             "This window grew by TC-3 after the plan review: add their tests, keep what stands.", SP.render_slice(grown))


def refusal_value(call):
    try:
        call()
    except ValueError as exc:
        return str(exc)
    return ""


# --- the command line -------------------------------------------------------------------------------------

def k11_cli():
    project = temp_project("qa-s5chk-cli-")
    try:
        task = project / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True)
        put(task, "pipeline.json", json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}}))
        BASE.s5_story(task, with_case_files=True, mark=False)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "PYTHONDONTWRITEBYTECODE": "1"}

        def go(*args):
            return subprocess.run([sys.executable, "-B", str(SCRIPTS / "s5_plan.py"), "--task", "QA-1", *args], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", env=env, cwd=str(project), timeout=300)

        missing = go("--check")
        check_eq("K11: --check with no plan is exit 1, a REJECT of one finding", (missing.returncode, missing.stdout.startswith("REJECT — 1 finding(s)")), (1, True))
        go("--init")
        done = go("--check")
        verdict = DV.parse(done.returncode, done.stdout, done.stderr)
        check_eq("K11: the skeleton has no test: exit 1 and the verdict is parseable form 1 (one line per finding)", (done.returncode, bool(verdict["findings"]), verdict["unmigrated"], verdict["defects"]), (1, True, "", []))
        check("K11: ... every Then of the skeleton is named", any("case TC-1 Then 1" in f for f in verdict["findings"]) and any("case TC-2 Then 2" in f for f in verdict["findings"]))
        check_in("K11: ... and the tail names the way back", "--check` again", done.stdout)
        plan = json.loads((task / SP.PLAN_REL).read_text(encoding="utf-8"))
        check("K11: the skeleton the CLI writes holds no window", all("window" not in row for row in plan["cases"]))
        number = 0
        for row in plan["cases"]:
            for then in row["thens"]:
                number += 1
                plan["tests"].append(test_row(f"T-{number}", [row["case"]], [f"{row['case']}#{then['n']}"]))
        put(task, SP.PLAN_REL, json.dumps(plan))
        clean = go("--check")
        check_eq("K11: a filled plan (the real controller's scope and windows) passes: exit 0 and OK", (clean.returncode, clean.stdout.startswith("note:") or clean.stdout.startswith("OK:")), (0, True))
        window = go("--window", "1")
        check_eq("K11: --window 1 prints the slice as markdown", (window.returncode, window.stdout.startswith("# S5 plan - window 1 of ")), (0, True))
        out = project / "slice.md"
        written = go("--window", "1", "--out", str(out))
        check_eq("K11: --out writes the same bytes and prints one JSON line", (written.returncode, out.read_text(encoding="utf-8") == window.stdout, json.loads(written.stdout)["window"]), (0, True, 1))
        check_eq("K11: no temporary file is left by --out", sorted(p.name for p in project.glob("slice.md*")), ["slice.md"])
        check_eq("K11: a window the plan does not have is a refusal (exit 2)", go("--window", "9").returncode, 2)
        check_eq("K11: --out without --window is refused by the parser", go("--check", "--out", str(out)).returncode, 2)
        check_eq("K11: --check and --window together are refused by the parser", go("--check", "--window", "1").returncode, 2)
        put(task, SP.PLAN_REL, b"{half")
        broken = go("--check")
        check("K11: an unreadable plan is a REJECT of one finding, no traceback", broken.returncode == 1 and "Traceback" not in broken.stderr and "REJECT — 1 finding(s)" in broken.stdout)
    finally:
        cleanup(project)


if __name__ == "__main__":
    k1_cases()
    k2_thens()
    k3_shape_and_level_against_s3()
    k4_extends()
    k5_words_ids_windows()
    k6_limits()
    k7_all_at_once_and_absent()
    k8_reviews_and_remarks()
    k9_remark_rows_missing()
    k10_window_slice()
    k11_cli()
    finish("test_s5_plan_check")
