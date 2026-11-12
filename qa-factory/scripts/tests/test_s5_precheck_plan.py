#!/usr/bin/env python3
"""SC1-14 B2: `s5_precheck` checks a window against its plan, and hands the plan dispatch to `s5_plan.check`.

A window of a story whose S5 began with a plan (`s5_plan.mode` = planned) is checked against its slice of the plan: C1 an instance
of every planned test lists the cases in `covers`, C2 every planned Then is bound to an assertion of the planned test, C3 the
manifest has the planned tests and no others, C4 the origin of the instance, C5 the shape, C7 the parameter count, C12 a row for
every plan remark, C13 a difference is a finding unless a `deviations[]` row declares it. A story on the earlier form gets one
note. The plan dispatch itself has no manifest: its detector is `s5_plan.check`. Each key names the mutation it kills (spec t-1246
section 5, B2: M25 a declared deviation read as a finding, M26 a remark without a row read as no finding, M27 an unreadable plan
read as a pass, M28 the plan dispatch sent through the manifest checks).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import s5_plan as SP  # noqa: E402
import s5_precheck as P  # noqa: E402

ASKED = ["TC-1", "TC-2"]


def test_row(identifier, file, function, cases, thens, **extra):
    row = {"id": identifier, "file": file, "function": function, "cases": list(cases), "thens": list(thens), "level": "api",
           "shape": "new", "extends": "", "consolidates": [], "params": None, "uses": [], "data": "own", "assert": "x", "deviation": []}
    row.update(extra)
    return row


def piece(remarks=(), tests=None):
    tests = tests if tests is not None else [test_row("T-1", "tests/test_a.py", "test_one", ["TC-1"], ["TC-1#1"]),
                                             test_row("T-2", "tests/test_b.py", "test_two", ["TC-2"], ["TC-2#1"])]
    return {"window": 1, "windows": [1], "asked": list(ASKED), "cases": [], "missing": [], "tests": tests, "remainders": [],
            "requirements": [], "remarks": list(remarks), "surface": "other", "size": 2, "over_cap": False, "cap": None, "grown": []}


def instance(function, case, file=None, **extra):
    row = {"instance_id": function, "test_function": function, "file": file or f"tests/test_{'a' if case == 'TC-1' else 'b'}.py",
           "covers": [case], "shape": "new", "status": "green"}
    row.update(extra)
    return row


def binding(case, instance_id, then=1, **extra):
    row = {"case": case, "then": then, "instance_id": instance_id, "assertion_ref": "t.py:10", "status": "covered"}
    row.update(extra)
    return row


def manifest(tests=None, bindings=None):
    return {"tests": tests if tests is not None else [instance("test_one", "TC-1"), instance("test_two", "TC-2")],
            "then_bindings": bindings if bindings is not None else [binding("TC-1", "test_one"), binding("TC-2", "test_two")]}


def conform(root, man, pc=None, **rows):
    findings, notes = [], []
    P._conform(root, man, pc or piece(), dict({"plan_remarks": [], "deviations": [], "origins": {}}, **rows), findings, notes)
    return findings, notes


def says(findings, *needles):
    return any(all(n in f["message"] for n in needles) for f in findings)


def deviation(test, kind):
    return {"test": test, "from": kind, "planned": "x", "reason": "because"}


def conformance_checks():
    root = temp_project("qa-s5pre-plan-")
    try:
        findings, notes = conform(root, manifest())
        check_eq("a window that is its plan: no finding", [f["message"] for f in findings], [])
        check_eq("C4: no origin row in the form is named as not checked, not passed", [n for n in notes if n.startswith("C4")] != [], True)
        # C3
        gone = manifest(tests=[instance("test_one", "TC-1")], bindings=[binding("TC-1", "test_one")])
        check("C3: a planned test that is not in the manifest is an undeclared deviation", says(conform(root, gone)[0], "C3", "T-2", "tests/test_b.py::test_two"))
        extra = manifest(tests=[instance("test_one", "TC-1"), instance("test_two", "TC-2"), instance("test_three", "TC-2", file="tests/test_c.py")])
        check("C3: a manifest test the plan does not have is an undeclared deviation", says(conform(root, extra)[0], "C3", "tests/test_c.py::test_three"))
        moved = manifest(tests=[instance("test_one", "TC-1"), instance("test_two", "TC-2", file="tests/test_c.py")],
                         bindings=[binding("TC-1", "test_one"), binding("TC-2", "test_two")])
        check("C3: a test in another file is both missing and unplanned", len(conform(root, moved)[0]) == 2)
        # M25: the declared deviation is not a finding (E13)
        # fix Y B-2: the move row names BOTH sides (old -> new: it used to carry only `test`, the new side, and excused the planned side
        # through "any unplanned test of the window"; now `planned` names the planned test)
        move = dict(deviation("tests/test_c.py::test_two", "file"), planned="tests/test_b.py::test_two")
        declared = conform(root, moved, deviations=[move])[0]
        check_eq("C13 (M25): a row of kind `file` naming both sides declares the move - no finding", [f["message"] for f in declared], [])
        check("B-2: a move row naming only the new side excuses the unplanned test, not the missing planned one",
              [f["check"] for f in conform(root, moved, deviations=[deviation("tests/test_c.py::test_two", "file")])[0]] == ["plan"]
              and says(conform(root, moved, deviations=[deviation("tests/test_c.py::test_two", "file")])[0], "C3", "T-2"))
        # B-2 scenario 1 (missing): T-1 and T-2 planned, both gone, one unplanned test; one rename row excuses exactly the T it names
        two_gone = manifest(tests=[instance("test_three", "TC-2", file="tests/test_c.py")], bindings=[])
        rename = dict(deviation("tests/test_c.py::test_three", "function"), planned="tests/test_b.py::test_two")
        found = conform(root, two_gone, deviations=[rename])[0]
        check("B-2: a rename row for test_two does not excuse the OTHER missing planned test (T-1)",
              says(found, "C3", "T-1") and not says(found, "C3", "the plan has test T-2"), [f["message"] for f in found])
        check("B-2: ... and T-2 is not reported missing (its row names it)", not any("test T-2 (tests/test_b.py::test_two) for" in f["message"] for f in found))
        # B-2 scenario 2 (unplanned): a row naming PLANNED test A with a deviation in A; an undeclared unplanned test B is still refused
        a_dev = manifest(tests=[instance("test_one", "TC-1", shape="consolidate"), instance("test_two", "TC-2"),
                                instance("test_z", "TC-2", file="tests/test_z.py")])
        shape_a = deviation("tests/test_a.py::test_one", "shape")
        found = conform(root, a_dev, deviations=[shape_a])[0]
        check("B-2: a row naming A (planned) does not excuse the undeclared unplanned test B, and names B",
              len(found) == 1 and says(found, "C3", "tests/test_z.py::test_z"), [f["message"] for f in found])
        both_declared = conform(root, a_dev, deviations=[shape_a, deviation("tests/test_z.py::test_z", "file")])[0]
        check_eq("B-2: a row naming A for A's deviation and a row naming B for B: clean", [f["message"] for f in both_declared], [])
        check_eq("B-2: a row naming A with a deviation in A only: passes", conform(root, manifest(tests=[instance("test_one", "TC-1", shape="consolidate"), instance("test_two", "TC-2")]),
                 deviations=[shape_a])[0], [])
        check("B-2: a row naming no test excuses nothing (as before)",
              len(conform(root, moved, deviations=[{"from": "file", "planned": "x", "reason": "r"}])[0]) == 2)
        check("C13: a row of the WRONG kind does not declare it", len(conform(root, moved, deviations=[deviation("tests/test_c.py::test_two", "count")])[0]) == 2)
        check("C13: a row naming another test does not declare it", len(conform(root, moved, deviations=[deviation("tests/test_z.py::test_z", "file")])[0]) == 2)
        # C1
        bare = manifest(tests=[instance("test_one", "TC-1"), instance("test_two", "TC-2", covers=[])])
        check("C1: an instance of the planned test that does not list the case in `covers`", says(conform(root, bare)[0], "C1", "TC-2"))
        # C2
        unbound = manifest(bindings=[binding("TC-1", "test_one")])
        check("C2: a planned Then with no binding to the planned test", says(conform(root, unbound)[0], "C2", "Then 1 of TC-2"))
        noref = manifest(bindings=[binding("TC-1", "test_one"), binding("TC-2", "test_two", assertion_ref="")])
        check("C2: a binding with no assertion_ref is no binding", says(conform(root, noref)[0], "C2", "TC-2"))
        other = manifest(bindings=[binding("TC-1", "test_one"), binding("TC-2", "test_one")])
        check("C2: a Then bound to ANOTHER test is not bound in the planned one", says(conform(root, other)[0], "C2", "TC-2"))
        remainder = manifest(bindings=[binding("TC-1", "test_one"), binding("TC-2", "test_two", status="unresolved", assertion_ref="")])
        check("C13: a planned Then recorded as a remainder with no row is an undeclared deviation", says(conform(root, remainder)[0], "C13", "remainder"))
        check_eq("C13: ... and with a `remainder` row it is not a finding",
                 conform(root, remainder, deviations=[deviation("tests/test_b.py::test_two", "remainder")])[0], [])
        # C5, C7, C4
        shaped = manifest(tests=[instance("test_one", "TC-1", shape="consolidate"), instance("test_two", "TC-2")])
        check("C5: the manifest shape against the plan's", says(conform(root, shaped)[0], "C5", "`new`", "consolidate"))
        check_eq("C5: ... a `shape` row declares it", conform(root, shaped, deviations=[deviation("tests/test_a.py::test_one", "shape")])[0], [])
        counted = piece(tests=[test_row("T-1", "tests/test_a.py", "test_one", ["TC-1"], ["TC-1#1"], params=3),
                               test_row("T-2", "tests/test_b.py", "test_two", ["TC-2"], ["TC-2#1"])])
        check("C7: 3 parameters planned, 1 instance in the manifest", says(conform(root, manifest(), counted)[0], "C7", "3 parameter", "1 instance"))
        check_eq("C7: ... a `count` row declares it", conform(root, manifest(), counted, deviations=[deviation("tests/test_a.py::test_one", "count")])[0], [])
        check_eq("C7: the count that matches is clean", conform(root, manifest(), piece(tests=[test_row("T-1", "tests/test_a.py", "test_one", ["TC-1"], ["TC-1#1"], params=1),
                                                                                         test_row("T-2", "tests/test_b.py", "test_two", ["TC-2"], ["TC-2#1"])]))[0], [])
        extend = piece(tests=[test_row("T-1", "tests/test_a.py", "test_one", ["TC-1"], ["TC-1#1"], shape="extend", extends="tests/test_a.py::test_old"),
                              test_row("T-2", "tests/test_b.py", "test_two", ["TC-2"], ["TC-2#1"])])
        origin = {"test_one": "new", "test_two": "new"}
        both = manifest(tests=[instance("test_one", "TC-1", shape="extend"), instance("test_two", "TC-2")])
        check("C4: planned `extend` and an instance whose origin is `new`", says(conform(root, both, extend, origins=origin)[0], "C4", "extend"))
        check_eq("C4: planned `extend`, origin `changed`: clean", conform(root, both, extend, origins={"test_one": "changed", "test_two": "new"})[0], [])
        check("C4: planned `new` and origin `changed`", says(conform(root, manifest(), origins={"test_one": "changed", "test_two": "new"})[0], "C4", "new"))
        # M26 / E12: a row for every remark, exactly one
        remarks = [{"id": "PR-1", "kind": "remark"}, {"id": "PR-2", "kind": "blocker"}]
        check("C12 (M26): no row for PR-1 and PR-2 is a finding each", len([f for f in conform(root, manifest(), piece(remarks))[0] if "C12" in f["message"]]) == 2)
        rows = [{"id": "PR-1", "row": "applied", "reason": ""}, {"id": "PR-2", "row": "applied", "reason": ""}]
        check_eq("C12: one row each - clean", conform(root, manifest(), piece(remarks), plan_remarks=rows)[0], [])
        check("C12: two rows for one id is still a finding", says(conform(root, manifest(), piece(remarks), plan_remarks=rows + rows[:1])[0], "PR-1"))
        check("C12: the finding is the family `plan` and no word passes it", all(f["check"] == "plan" and not P._passable(f) for f in conform(root, manifest(), piece(remarks))[0]))
        check_in("a case the plan has no row for is a note, never a finding", "TC-9: not in the plan",
                 conform(root, manifest(), dict(piece(), missing=["TC-9"]))[1])
    finally:
        cleanup(root)


def put(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def view(root, *records):
    put(root, "state/controller.json", json.dumps({"dispatches": {r["id"]: r for r in records}}))


def window(identifier="W1", **extra):
    return dict({"id": identifier, "stage": "S5", "role": "qa-automator", "status": "running", "scope": list(ASKED),
                 "request_binding": {"purpose": "repair_verify"}}, **extra)


def plan_record(identifier="P1", status="accepted"):
    return {"id": identifier, "stage": "S5", "role": "qa-automator", "status": status, "request_binding": {"purpose": "s5_plan"}}


def wrapper_checks():
    root = temp_project("qa-s5pre-plan-w-")
    real_slice = SP.window_slice
    asked_for = {}
    try:
        def slice_of(task, **kw):
            asked_for.update(kw)
            return piece([{"id": "PR-1", "kind": "remark"}])
        SP.window_slice = slice_of
        def run(dispatch="W1"):
            found, noted = [], []
            P.check_plan_conformance(root, manifest(), ASKED, found, noted, dispatch)
            return found, noted

        # legacy: a live window and no plan record -> a note, not a finding (E5)
        view(root, window())
        f, n = run()
        check_eq("legacy: no finding", f, [])
        check_in("legacy: one note that names the form and what was not checked", "no S5 plan for this story", n)
        check_in("legacy: ... and says conformance is not checked", "conformance not checked", n)
        check_eq("legacy: the slice is never asked for", asked_for, {})
        f, n = run("W-unknown")
        check_eq("a dispatch id with no record: a note, no finding", (f, len(n)), ([], 1))
        found, noted = [], []
        P.check_plan_conformance(root, manifest(), ASKED, found, noted, None)
        check_eq("no dispatch named: nothing added (the printed result of such a run stays what it was)", (found, noted), ([], []))
        # planned, plan file missing / unreadable -> a finding (M27, AR-28)
        view(root, plan_record(), window())
        f, n = run()
        check("M27: a plan record and no file is a finding with its door", says(f, "does not exist") and "plan before windows" in f[0]["fix"])
        put(root, "work/s5-plan.json", "{not json")
        f, n = run()
        check("M27: a plan that is not JSON is a finding, not a pass", says(f, "cannot be read for this window"))
        # planned and readable: the slice is asked BY CASES of the dispatch; remarks get their rows from the form
        put(root, "work/s5-plan.json", json.dumps({"schema": 1, "cases": [], "tests": []}))
        f, n = run()
        check_eq("planned: the slice is asked for the dispatch's cases", asked_for.get("cases"), ASKED)
        check("planned: PR-1 has no row (the form is not written yet) - a finding, and a note says the form is missing",
              says(f, "PR-1", "C12") and any("form is not written yet" in x for x in n))
        put(root, "work/handoffs/W1.yaml", "contract: s5-automator-to-critic\nplan_remarks:\n  - id: PR-1\n    row: applied\n    reason: done\ndeviations: []\n")
        f, n = run()
        check("planned: the form's row answers PR-1 (and the manifest is the plan)", not says(f, "PR-1"))
        put(root, "work/handoffs/W1.yaml", "contract: s5-automator-to-critic\nplan_remarks: nope\n")
        f, n = run()
        check("planned: a `plan_remarks` that is not a list is a finding", says(f, "`plan_remarks` of the window's form is not a list"))
        # the plan dispatch (M28): its result is the plan's own check; the manifest is never read
        view(root, plan_record("P1", "running"), window())
        check("is_plan_dispatch: a plan record", P.is_plan_dispatch(root, "P1") and not P.is_plan_dispatch(root, "W1") and not P.is_plan_dispatch(root, None))
        real_check = SP.check_report
        SP.check_report = lambda task, controller, files=True: (["test T-1: shape `x` is not a word of the plan — fix: use `new`"], ["a note"])
        try:
            result = P.plan_result(root, "P1")
            check_eq("plan result: one finding of the family plan, message and fix split", (result["ok"], len(result["findings"]), result["findings"][0]["check"],
                     result["findings"][0]["fix"]), (False, 1, "plan", "use `new`"))
            out = io.StringIO()
            old_argv = sys.argv
            sys.argv = ["s5_precheck.py", "--task-root", str(root), "--dispatch", "P1"]
            try:
                with contextlib.redirect_stdout(out):
                    code = P.main()
            finally:
                sys.argv = old_argv
            text = out.getvalue()
            check("M28: the plan dispatch goes to the plan check, with no manifest present (REJECT, exit 1)",
                  code == 1 and "REJECT — 1 finding(s)" in text and "[plan " in text, text[:300])
            view(root, plan_record(), window())
            sys.argv = ["s5_precheck.py", "--task-root", str(root), "--dispatch", "W1"]
            put(root, "work/automation-manifest.json", json.dumps({"tests": [], "then_bindings": []}))
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    P.main()
            finally:
                sys.argv = old_argv
            check("a window dispatch is NOT sent to the plan check", "S5 plan" not in out.getvalue(), out.getvalue()[:300])
        finally:
            SP.check_report = real_check
        # the report line of a clean plan
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = P.report({"ok": True, "findings": [], "notes": ["n"], "plan": True, "cases": []})
        check_eq("a clean plan reports OK and names what it did not check", (code, buf.getvalue().strip().splitlines()),
                 (0, ["note: n", "OK: the S5 plan has no gap (1 thing(s) not checked, named above)."]))
    finally:
        SP.window_slice = real_slice
        cleanup(root)


def plan_hint_checks():
    """t-1502 G-1 (K2, K6): the producer's REAL plan through `plan_result` and `report`. The hint is advice: it never moves `ok`, the
    findings or the notes' count; a plan that cannot be read has its finding and no hint; a hint that cannot be computed is a note."""
    import s5_plan
    from test_s5_plan_grouping import GROUPED, REASON, fixture_plan, fixture_story, run_main, write_plan
    real_hints = SP.grouping_hints
    with fixture_story() as (project, task):
        try:
            result = P.plan_result(task)
            SP.grouping_hints = lambda plan, file_key=None: []
            bare = P.plan_result(task)
            SP.grouping_hints = real_hints
            check_eq("K2: the real plan: one hint, of the family plan, level hint, tagged by its group",
                     [(h["check"], h["level"], h["id"].startswith("plan:TC-001:group-")) for h in result["hints"]], [("plan", "hint", True)])
            check("K2: ... its message is the seven-test message of the plan", result["hints"][0]["message"].startswith("7 tests at level api in ")
                  and "+3 more): TC-001, TC-002, TC-004, TC-005, TC-006, TC-007, TC-011" in result["hints"][0]["message"], result["hints"][0]["message"])
            check_eq("K2: the real plan has no finding, so the hint leaves `ok` true", (result["ok"], result["findings"]), (True, []))
            check_eq("K2: `ok` and the findings are those of the same plan without hints", (result["ok"], result["findings"]), (bare["ok"], bare["findings"]))
            check_eq("K2: ... and so are the notes", result["notes"], bare["notes"])
            check_eq("K2: ... the bare run has no hint", bare["hints"], [])
            # a finding beside a hint: ok is false because of the finding only, and the finding count is the same with and without the hint
            bad = fixture_plan()
            bad["tests"][1]["apart_reason"] = "y" * 301
            write_plan(task, bad)
            with_hint = P.plan_result(task)
            SP.grouping_hints = lambda plan, file_key=None: []
            without = P.plan_result(task)
            SP.grouping_hints = real_hints
            check_eq("K2: a finding + a hint: ok false, one finding, one hint", (with_hint["ok"], len(with_hint["findings"]), len(with_hint["hints"])), (False, 1, 1))
            check_eq("K2: ... the finding count is that of the run without hints", len(with_hint["findings"]), len(without["findings"]))
            write_plan(task, fixture_plan())
            # the report: the hint before the OK line, and the OK line says it is advice - the sentence of `s5_plan --check`
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = P.report(P.plan_result(task))
            lines = buf.getvalue().splitlines()
            check_eq("K2: report: exit 0", code, 0)
            check("K2: report: `hint: [plan] 7 tests at level api in ...` and its consider line come before the OK line",
                  lines[-3].startswith("hint: [plan] 7 tests at level api in ") and lines[-2].startswith("  consider: if they share setup and action")
                  and lines[-1].startswith("OK: the S5 plan has no gap ("), "\n".join(lines))
            check("K2: report: the OK line ends with the advice sentence", lines[-1].endswith(s5_plan.HINT_ADVICE), lines[-1])
            check_eq("K2: the sentence is the spec's", s5_plan.HINT_ADVICE,
                     "The hint above is advice about the shape you chose, not a repair: take it or answer it in the test's `apart_reason`.")
            _code, main_out, _err = run_main(project, "--task", "QA-1", "--check")
            check("K2: `s5_plan --check` ends its OK line with the same sentence (one text for one plan)",
                  next(l for l in main_out.splitlines() if l.startswith("OK:")).endswith(s5_plan.HINT_ADVICE))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                P.report({"ok": True, "findings": [], "notes": [], "plan": True, "cases": [], "hints": []})
            check_not_in("K2: report: a plan with no hint says nothing of advice", "advice", buf.getvalue())
            # K6: the hint cannot be computed: no hint, a note, nothing else moves
            SP.grouping_hints = lambda plan, file_key=None: (_ for _ in ()).throw(ValueError("no way"))
            broken = P.plan_result(task)
            SP.grouping_hints = real_hints
            check_eq("K6: a grouping_hints that raises: no hint, `ok` unchanged, the findings unchanged", (broken["hints"], broken["ok"], broken["findings"]), ([], True, []))
            check_in("K6: ... and a note that says the hints were not checked", "not checked: the grouping hints of the plan (ValueError: no way)", broken["notes"])
            # K6: a plan that cannot be read: its finding stays (as before), there is no hint and no 'not checked' note about hints
            put(task, "work/s5-plan.json", "{not json")
            unreadable = P.plan_result(task)
            check_eq("K6: an unreadable plan: ok false, one finding, no hint", (unreadable["ok"], len(unreadable["findings"]), unreadable["hints"]), (False, 1, []))
            check("K6: ... and no note about the hints (the finding already says it)", not any("grouping hints" in n for n in unreadable["notes"]), str(unreadable["notes"]))
            (task / "work" / "s5-plan.json").unlink()
            missing = P.plan_result(task)
            check_eq("K6: no plan file: a finding as before, no hint", (missing["ok"], missing["hints"]), (False, []))
            # every candidate answered by its reason: the hint is gone
            answered = fixture_plan()
            for test in answered["tests"]:
                if test["cases"][0] in GROUPED:
                    test["apart_reason"] = REASON
            write_plan(task, answered)
            check_eq("K2: every candidate with its apart_reason: no hint, ok", (P.plan_result(task)["hints"], P.plan_result(task)["ok"]), ([], True))
        finally:
            SP.grouping_hints = real_hints


def main():
    conformance_checks()
    wrapper_checks()
    plan_hint_checks()
    finish("test_s5_precheck_plan")


if __name__ == "__main__":
    main()
