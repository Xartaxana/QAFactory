#!/usr/bin/env python3
"""SC1-14 C2 = SC1-15: the briefs of the S5 plan and of its windows (spec t-1246 section 3, part C2; edges E10, E15, E39, E41).

  * the PLAN dispatch (`purpose: s5_plan`): no «window N of M» in the scope line; the author is told its work is the plan and its exit
    check; the critic is told its form, the rubric section and, on a re-look, the number its new remarks start after; a plan over
    the guard's whole-read cap is named by its parts as the windows will cut it, each written whole, and a cap that cannot be read
    leaves the plan named whole and says it was not checked (E39);
  * a WINDOW of the plan form: the slice of the plan is a side file, the head gets one count line (`N tests planned, M remarks for
    this window`, or `no tests planned ...: write the remainders`, E41) and one more only for an over-cap or grown window; a
    remark with no case goes to every window (E10); the code file holds the extended test, the fixture and a neighbouring test,
    at most 60 code lines an excerpt and 28 000 bytes with the left-out list (E15, at 28 000 and 28 001); the head grows by at
    most two lines and the brief stays under 6 KB;
  * a resumed rework writes a delta with the fallback line (E4); a fresh one does not;
  * the earlier form (`legacy`) is the brief as it was: no plan path, no slice, no side file.

Every key names the mutation it kills (spec section 5, C2: M38 the 28 000 cap without the left-out list, M39 the head over the cap,
M40 a global remark missing from window 2, M41 a plan over the cap with no slices).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, s5_plan_ready, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack  # noqa: E402
import s5_plan as SP  # noqa: E402
from event_store import atomic_json  # noqa: E402

from test_s5_plan import put, s5_story  # noqa: E402
from test_s5_plan_check import test_row  # noqa: E402
from test_s5_plan_controller import send  # noqa: E402
from test_s5_plan_windows import set_tests  # noqa: E402

AUTHOR, CRITIC = "qa-automator", "qa-code-critic"
TICKET = "QA-9"
CASES = ("TC-1", "TC-2", "TC-3")
REMARK = ("  - id: {id}\n    case: {case}\n    test: \"-\"\n    then: \"-\"\n    kind: {kind}\n    check: K5\n    problem: the {id} problem\n"
          "    expected: the {id} expectation\n    fix: the {id} fix\n")


def config(project, other=2, read=None):
    block = {"dispatch": {"ui_window_cases": 2, "api_window_cases": other}}
    if read is not None:
        block["read"] = {"max_bytes": read}
    put(project, "qa-factory/config.json", json.dumps(block))


def review(task, remarks=(), outcome="approved_with_remarks", dispatch="S5-plan-critic-1"):
    """The critic's review form of `dispatch`, rewritten (the receipt of the stamp is by rows and stays valid)."""
    rows = "".join(REMARK.format(**r) for r in remarks)
    put(task, f"work/handoffs/{dispatch}.yaml",
        f"schema_version: 1\ncontract: s5-critic-plan-to-automator\nreview:\n  outcome: {outcome}\nremarks:{chr(10) + rows if rows else ' []'}\n")


def story(cases=CASES, groups=None, other=2, read=None):
    """(project, task, controller): a story on the plan form, the plan reviewed and accepted, tests one per case (or `groups`)."""
    project = temp_project("qa-bp-s5-")
    task = project / "qa-factory" / "artifacts" / TICKET
    task.mkdir(parents=True)
    put(task, "pipeline.json", json.dumps({"ticket": TICKET, "size": "S", "environment": "local", "stages": {}, "gates": {}, "halts": []}))
    c = s5_story(task, cases=cases, with_case_files=True, mark=False)
    config(project, other, read)
    harness.use_project(project)
    s5_plan_ready(c, task, list(cases))
    set_tests(task, groups or [[case] for case in cases])
    return project, task, c


def build(role, dispatch, write=False):
    return brief_pack.build(TICKET, "S5", role, dispatch, write=write)


def head_of(text):
    return text.split("## What earlier roles produced")[0].splitlines()


def k1_plan_dispatch():
    project, task, c = story()
    try:
        author = build(AUTHOR, "S5-plan-author-1")["markdown"]
        scope_line = next(line for line in author.splitlines() if line.startswith("Scope:"))
        check_not_in("the plan dispatch: the scope line has no window", "window 1 of", scope_line)
        check_in("the plan dispatch: the author's work is the plan, with its exit check and the grouping rule (t-1502 G-1)",
                 "Your work is the plan, not the code: fill work/s5-plan.json (one row of your digest per case). Cases with the same setup and "
                 "action are one parameterized test (test-code-patterns.md «Executable shape»); a test kept apart says why in `apart_reason`. "
                 "`s5_plan.py --check` is the exit check; its hints are advice, not repairs",
                 author)
        check_in("the plan dispatch: the plan is named, with its size", f"qa-factory/artifacts/{TICKET}/work/s5-plan.json (", author)
        check_in("the plan dispatch: the card has the plan's exit check", f"s5_plan.py --task {TICKET} --check", author)
        check_in("the plan dispatch: the cases of the whole scope", "TC-3", author)
        critic = build(CRITIC, "S5-plan-critic-1")["markdown"]
        check_not_in("the plan critic: no window in the scope line", "window 1 of", next(l for l in critic.splitlines() if l.startswith("Scope:")))
        check_in("the plan critic: its review form is named", "work/handoffs/S5-plan-critic-1.yaml - your review form", critic)
        check_in("the plan critic: the rubric section", "code-review-rubric.md", critic)
        check_in("the plan critic: the section of the rubric", "«On the plan»", critic)
        check_in("the plan critic: a brief built after an accepted review is a re-look of it", "chain's last PR-n (PR-0)", critic)
        # a re-look: the chain has a review whose last remark is PR-3
        review(task, [{"id": "PR-3", "case": "TC-1", "kind": "remark"}])
        send(c, task, "S5-plan-critic-2", CRITIC, scope=list(CASES), purpose="s5_plan", rework_of="S5-plan-critic-1")
        again = build(CRITIC, "S5-plan-critic-2")["markdown"]
        check_in("the plan critic's re-look: new remarks start after the chain's last PR-n", "after the chain's last PR-n (PR-3)", again)
        review(task, [{"id": "PR-3", "case": "TC-1", "kind": "remark"}, {"id": "PR-11", "case": "-", "kind": "remark"}])
        check_in("the re-look: the highest PR number, not the last or the count", "(PR-11)", build(CRITIC, "S5-plan-critic-2")["markdown"])
        extra = [l for l in head_of(again) if "chain's last PR-n" in l or l.startswith("Your work is the plan")]
        check_eq("the plan critic's head grows by two lines at most", len(extra), 2)
    finally:
        cleanup(project)


def k2_plan_over_the_cap():
    project, task, c = story(read=2500)
    try:
        plan = SP.load(task)
        plan["refactor"] = "x" * 4000                       # the plan is now over the cap; each window's slice is not
        atomic_json(task / SP.PLAN_REL, plan)
        size = (task / SP.PLAN_REL).stat().st_size
        got = build(AUTHOR, "S5-plan-author-1", write=True)
        text = got["markdown"]
        check("M41: the plan is over the guard's cap (fixture)", size > 2500, str(size))
        check_not_in("M41: a plan over the cap is not named as a path to read whole", f"work/s5-plan.json ({size} B)", text)
        check_in("M41: ... its parts are named, as the windows will cut it", "as the windows will cut it", text)
        slices = [p for p in got["written"] if "-plan-w" in p]
        check_eq("M41: one slice file per window (cap 2: two windows)", len(slices), 2)
        check("M41: every slice is written whole and under the cap",
              all(0 < Path(p).stat().st_size <= 2500 for p in slices), str([Path(p).stat().st_size for p in slices]))
        check_in("M41: the slice paths are in the brief", "S5-plan-author-1-plan-w2.md", text)
        dry = build(AUTHOR, "S5-plan-author-1")["markdown"]
        check_in("a dry run names the slices and says they are not written", "(not written in this run)", dry)
        # at the cap: the plan is named whole
        config(project, 2, size)
        check_in("at the cap (the plan's size) the plan is named whole", f"s5-plan.json ({size} B)", build(AUTHOR, "S5-plan-author-1")["markdown"])
        config(project, 2, size - 1)
        check_not_in("one byte over the cap the plan is cut into parts", f"s5-plan.json ({size} B)", build(AUTHOR, "S5-plan-author-1")["markdown"])
        # a cap that cannot be read: the plan whole, and the line says it was not checked (E39)
        import guard_pre_tool
        real = guard_pre_tool.big_read_cap
        guard_pre_tool.big_read_cap = lambda cfg: (_ for _ in ()).throw(RuntimeError("no cap"))
        try:
            unread = build(AUTHOR, "S5-plan-author-1")["markdown"]
        finally:
            guard_pre_tool.big_read_cap = real
        check_in("E39: a cap that cannot be read leaves the plan whole", f"s5-plan.json ({size} B)", unread)
        check_in("E39: ... and says it was not checked", "not checked against the guard's read cap", unread)
    finally:
        cleanup(project)


def k3_window_plan_slice():
    project, task, c = story(cases=("TC-1", "TC-2", "TC-3"), other=2)
    try:
        review(task, [{"id": "PR-1", "case": "TC-1", "kind": "remark"}, {"id": "PR-2", "case": "-", "kind": "remark"}])
        send(c, task, "S5-qa-automator-1", AUTHOR, scope=["TC-1", "TC-2"])
        one = build(AUTHOR, "S5-qa-automator-1", write=True)
        accept_window(c, task, "S5-qa-automator-1")
        send(c, task, "S5-qa-automator-2", AUTHOR, scope=["TC-3"])
        two = build(AUTHOR, "S5-qa-automator-2", write=True)
        check_in("window 1: the head counts tests and remarks", "2 tests planned, 2 remarks for this window", one["markdown"])
        check_in("M40: window 2 gets the remark that names no case (E10)", "1 remarks for this window", two["markdown"])
        slice_two = Path([p for p in two["written"] if p.endswith("-plan.md")][0]).read_text(encoding="utf-8")
        check_in("M40: ... PR-2 is in window 2's slice", "PR-2", slice_two)
        check_not_in("window 2's slice has no remark of TC-1", "PR-1", slice_two)
        check_in("the window's slice has the requirements and the tests", "## Tests", slice_two)
        check("the plan's path is not named to a window", "s5-plan.json" not in one["markdown"].split("## Commands")[0].split("## Read these files")[1],
              "the plan file is named in the files of a window")
        check_in("the slice is named in the files", "S5-qa-automator-1-plan.md", one["markdown"])
        check("the slice and the code are side files written with the brief",
              any(p.endswith("-plan.md") for p in one["written"]) and any(p.endswith("-code.md") for p in one["written"]), str(one["written"]))
        check_eq("the head holds one plan line for a window within its cap", len([l for l in head_of(one["markdown"]) if l.startswith("Plan slice")]), 1)
        check_eq("... and no over-cap or grown line", len([l for l in head_of(one["markdown"]) if l.startswith("This window")]), 0)
        # E41: a window whose cases have no test in the plan (all their Then clauses are remainders)
        plan = SP.load(task)
        plan["tests"] = [t for t in plan["tests"] if t["cases"] != ["TC-3"]]
        atomic_json(task / SP.PLAN_REL, plan)
        none = build(AUTHOR, "S5-qa-automator-2")["markdown"]
        check_in("E41: no test in the window -> write the remainders", "no tests planned for this window: write the remainders", none)
        check_not_in("E41: ... and no «0 tests planned»", "0 tests planned", none)
    finally:
        cleanup(project)


def k4_over_cap_and_head():
    project, task, c = story(cases=("TC-1", "TC-2", "TC-3"), groups=[["TC-1", "TC-2", "TC-3"]], other=2)
    try:
        # a long answer of the person must not push the head past the brief's ceiling (the head is never shrunk)
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["gates"] = {"A": {"gate": "A", "status": "approved", "authorization_source": "go " * 2500}}
        put(task, "pipeline.json", json.dumps(pipeline))
        send(c, task, "S5-qa-automator-1", AUTHOR, scope=["TC-1", "TC-2", "TC-3"])
        got = build(AUTHOR, "S5-qa-automator-1", write=True)
        head = head_of(got["markdown"])
        check_eq("an over-cap window: one count line and one over-cap line, no more",
                 (len([l for l in head if l.startswith("Plan slice")]), len([l for l in head if l.startswith("This window holds")])), (1, 1))
        check_in("the over-cap line is the slice's own wording", "over the other window cap of 2", "\n".join(head))
        check("M39: the brief stays under 6 KB with the plan lines and 10 KB of the person's words",
              got["budget_bytes"] <= brief_pack.BRIEF_MAX_BYTES, str(got["budget_bytes"]))
        check("M39: the plan slice line stayed under the ceiling", "S5-qa-automator-1-plan.md" in got["markdown"], got["markdown"][-300:])
    finally:
        cleanup(project)


def write_code(project, name, text):
    put(project, name, text)


def one_target_plan(extends, uses=(), file="tests/test_new.py", fixtures=()):
    return {"schema": 1, "fixtures": list(fixtures),
            "tests": [test_row("T-1", ["TC-1"], ["TC-1#1"], file=file, function="test_new", extends=extends, shape="extend", uses=list(uses))]}


def k5_code_file():
    project = temp_project("qa-bp-code-")
    try:
        harness.use_project(project)
        write_code(project, "tests/conftest.py", "import pytest\n\n\n@pytest.fixture\ndef client_fx():\n    return 1\n")
        write_code(project, "tests/test_base.py", "def test_base(client_fx):\n    assert client_fx == 1\n\n\ndef test_other():\n    assert True\n")
        write_code(project, "tests/test_ext.py", "def test_ext():\n    assert True\n")
        plan = one_target_plan("tests/test_ext.py::test_ext", uses=["client_fx", "ghost_fx"])
        text, omitted = brief_pack.window_code_file(project, plan, plan["tests"], "D-1")
        check_in("the extended test's body", "def test_ext():", text)
        check_in("the fixture's definition from the conftest chain", "def client_fx():", text)
        check_in("a fixture nobody defines is named, not skipped (E16)", "fixture ghost_fx: not found in", text)
        check_in("the neighbour: the test file is not there, so the first test of the directory", "test_base (the first test of the directory", text)
        check_in("the fields of a manifest row come from their carrier", "- assertion_id:", text)
        check_in("... with the carrier's values", "new_or_changed", text)
        check_eq("nothing left out of a small file", omitted, [])
        gone = one_target_plan("tests/test_base.py::test_missing")
        check_in("an extended test that is not there is named (E16)", "T-1 extends tests/test_base.py::test_missing: not found",
                 brief_pack.window_code_file(project, gone, gone["tests"], "D-1")[0])
        other = one_target_plan("src/helpers.js::case")
        check_in("a target in another language is not checked, out loud", "not a Python file",
                 brief_pack.window_code_file(project, other, other["tests"], "D-1")[0])
        new = one_target_plan("tests/test_base.py::test_base", fixtures=[{"name": "fresh_fx", "file": "tests/conftest.py", "new": True}], uses=["fresh_fx"])
        check_in("a fixture the plan introduces is named as new", "fixture fresh_fx: new, to be written", brief_pack.window_code_file(project, new, new["tests"], "D-1")[0])
        # a neighbour in the target's own file: the nearest test function, one per file
        write_code(project, "tests/test_new.py", "def test_a():\n    pass\n\n\ndef test_new():\n    pass\n\n\ndef test_z():\n    pass\n")
        near = brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0]
        check_in("the neighbour is the nearest test of the same file", "test_a (a neighbouring test in tests/test_new.py)", near)
        check_not_in("... and only one per file", "test_z (a neighbouring", near)
        # the 60-line excerpt: AT and BEYOND the bound
        for total in (60, 61):
            body = "".join(f"    x{n} = {n}\n" for n in range(total - 1))
            write_code(project, "tests/test_big.py", f"def test_big():\n{body}")
            big = one_target_plan("tests/test_big.py::test_big", file="tests/test_big2.py")
            text = brief_pack.window_code_file(project, big, big["tests"], "D-1")[0]
            fenced = text.split("```python\n")[1].split("```")[0].splitlines()
            check_eq(f"an excerpt of {total} lines: at most 60 code lines", len(fenced), 60)
            check_eq(f"an excerpt of {total} lines: the cut is named only beyond 60", "(cut: lines 61-61" in text, total == 61)
    finally:
        cleanup(project)


def k6_code_file_cap():
    project = temp_project("qa-bp-cap-")
    try:
        harness.use_project(project)

        def made(filler):
            write_code(project, "tests/test_cap.py", f"def test_cap():\n    # {'f' * filler}\n    assert True\n")
            plan = one_target_plan("tests/test_cap.py::test_cap", file="tests/test_cap2.py")
            return brief_pack.window_code_file(project, plan, plan["tests"], "D-1")

        base = len(made(0)[0].encode("utf-8"))
        text, omitted = made(brief_pack.CODE_FILE_BYTES - base)
        check_eq("E15: a file of exactly 28 000 bytes is whole", len(text.encode("utf-8")), 28_000)
        check_eq("E15 (at 28 000): nothing is left out", (omitted, "## Left out" in text), ([], False))
        text, omitted = made(brief_pack.CODE_FILE_BYTES - base + 1)
        check("M38: 28 001 bytes -> under the cap", len(text.encode("utf-8")) <= 28_000, str(len(text.encode("utf-8"))))
        check_eq("M38: 28 001 -> the omitted list names file:lines", [w.startswith("tests/test_cap.py:1-3") for w in omitted], [True])
        check_in("M38: ... and the file says so under a heading", "## Left out", text)
        check_in("M38: ... with the same file:lines", "- tests/test_cap.py:1-3", text)
        check_not_in("M38: the dropped excerpt is not in the file", "assert True", text)
        # many targets over the cap: the first ones stay, the last are named
        write_code(project, "tests/test_many.py", "".join(f"def test_{n}():\n    # {'m' * 9000}\n    pass\n\n\n" for n in range(5)))
        tests = [test_row(f"T-{n}", ["TC-1"], ["TC-1#1"], file=f"tests/test_n{n}.py", function="test_new", extends=f"tests/test_many.py::test_{n}", shape="extend")
                 for n in range(5)]
        text, omitted = brief_pack.window_code_file(project, {"schema": 1, "tests": tests}, tests, "D-1")
        check("excerpts are dropped from the end", omitted and omitted[-1].startswith("tests/test_many.py:") and len(text.encode("utf-8")) <= 28_000,
              str(omitted))
        check_in("the first excerpt stays", "test_0 (the test you extend)" if False else "T-0: tests/test_many.py::test_0", text)
    finally:
        cleanup(project)


IMPORT_LINE = "the parameter-list module is found through the test file's import; `--file` is for what it cannot find"
WAIT_LINE = "wait for a condition, not seconds; fixtures in conftest are the window's code too"


def k10_marker_form():
    """EP1-25 AK5/AK6: the marker form reaches the role in its code file, from its carrier (`manifest_from_tests`), and the tool line
    of the card names the keys the old line left out. Kills: the form spelled as a literal (a key added to the carrier is not in the
    brief), the form after the excerpts (dropped by the cap), the form missing when the carrier cannot be read."""
    import types
    import manifest_from_tests as MFT
    project = temp_project("qa-bp-form-")
    try:
        harness.use_project(project)
        write_code(project, "tests/test_cap.py", "def test_cap():\n    assert True\n")
        plan = one_target_plan("tests/test_cap.py::test_cap", file="tests/test_cap2.py")
        text, _omitted = brief_pack.window_code_file(project, plan, plan["tests"], "D-1")
        check("AK5: a `## Marker form` section stands before the fields", 0 <= text.find("## Marker form") < text.find("## Fields every"), text[:300])
        check("AK5: every key of the carrier is named, `qa` and `qa_unresolved` by their names from data",
              all(f"`{k}`" in text for k in MFT.QA_KWARGS + MFT.UNRESOLVED_KWARGS)
              and f"@pytest.mark.{MFT.MARK_QA}(" in text and f"@pytest.mark.{MFT.MARK_UNRESOLVED}(" in text, text[:900])
        check_in("AK5: the example carries `then` and `partition`", "then=[1, 2], partition=\"<partition id>\"", text)
        check_in("AK5: `consolidates` is said to be the script's", "`consolidates` is not a marker key: the script writes it", text)
        check_in("AK5: the import line", IMPORT_LINE, text)
        check("TQ1-16 AK4: the wait line stands in the header, before the fields",
              0 <= text.find(WAIT_LINE) < text.find("## Fields every"), text[:900])
        check_in("AK5: the shapes are the vocabulary's", ", ".join(MFT.SHAPES), text)
        # M: the form spelled as a literal -> a key added to the carrier would not be here
        kept = MFT.QA_KWARGS
        MFT.QA_KWARGS = kept + ("zz_new_key",)
        try:
            check_in("AR-13: a key added to the carrier is in the brief with no edit in brief_pack", "`zz_new_key`",
                     brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0])
        finally:
            MFT.QA_KWARGS = kept
        # the carrier cannot be read: the brief is still built, with the door
        real = sys.modules["manifest_from_tests"]
        sys.modules["manifest_from_tests"] = types.SimpleNamespace()
        try:
            text_bad = brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0]
        finally:
            sys.modules["manifest_from_tests"] = real
        check_in("an unreadable carrier: the section is a line with the door", "`manifest_from_tests.py --help`", text_bad)
        check_in("... and the facts that need no carrier stay", IMPORT_LINE, text_bad)
        check_in("TQ1-16 AK4: ... the wait line too (it is not the carrier's)", WAIT_LINE, text_bad)

        # the cap: the form is in the header, so AT 28 000 and BEYOND it stays and the file fits
        def made(filler):
            write_code(project, "tests/test_cap.py", f"def test_cap():\n    # {'f' * filler}\n    assert True\n")
            return brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0]
        base = len(made(0).encode("utf-8"))
        for beyond in (0, 1, 5_000):
            body = made(brief_pack.CODE_FILE_BYTES - base + beyond)
            check(f"AK5 at the cap +{beyond}: the form stays and the file is within 28 000 bytes",
                  "## Marker form" in body and IMPORT_LINE in body and WAIT_LINE in body
                  and len(body.encode("utf-8")) <= brief_pack.CODE_FILE_BYTES,
                  str(len(body.encode("utf-8"))))

        # AK6: the card's tool line
        line = next(l for l in brief_pack.TOOLING["qa-automator"] if l.startswith("manifest_from_tests.py"))
        check_in("AK6: the tool line names `shape=` and `note=`", "`shape=` and `note=`", line)
        check_not_in("AK6: ... and does not point to a code file that exists only for the window kind", "code file", line)
        check_in("AK6: ... and the import phrase", IMPORT_LINE, line)
        check_in("AK6: the pinned command shape stays (test_brief_pack.py)",
                 "manifest_from_tests.py --task <T> --dispatch <ID> --file <test file> [--file ...] [--dry-run] [--json]", line)
        check_in("AK6: the pinned marker example stays",
                 '@pytest.mark.qa(case="<case id>", then=[1, 2], partition="tc003-zero-matches", obligations=["TS-3-O1"])', line)
    finally:
        cleanup(project)


def k7_delta():
    project, task, c = story(cases=("TC-1", "TC-2"), other=2)
    try:
        review(task, [{"id": "PR-1", "case": "TC-1", "kind": "remark"}, {"id": "PR-2", "case": "-", "kind": "remark"}])
        send(c, task, "S5-qa-automator-1", AUTHOR, scope=["TC-1", "TC-2"])
        put(task, "work/handoffs/S5-qa-automator-1.yaml", "schema_version: 1\nplan_remarks:\n  - id: PR-1\n    row: applied\n    reason: done\n")
        accept_window(c, task, "S5-qa-automator-1")
        send(c, task, "S5-qa-automator-2", AUTHOR, scope=["TC-1", "TC-2"], rework_of="S5-qa-automator-1", agent_id="agent-7",
             repair_cause="test_defect", reason="the assertion is on the wrong field")
        got = build(AUTHOR, "S5-qa-automator-2", write=True)
        delta = [p for p in got["written"] if p.endswith("-delta.md")]
        check_eq("a resumed rework writes a delta", len(delta), 1)
        text = Path(delta[0]).read_text(encoding="utf-8")
        check_in("E4: the delta's fallback line names the full brief", "read the full brief first: qa-factory/artifacts/QA-9/work/briefs/S5-qa-automator-2.md", text)
        check_in("the delta carries the reason of the round", "the assertion is on the wrong field", text)
        check_in("the delta names the remark that has no plan_remarks row", "PR-2 [remark]", text)
        check_not_in("... and not the one that has", "- PR-1 [remark]", text)
        # fix Y F-12 (old -> new: the section "Inputs changed since <parent> started" said "not checked" in every delta; it is dropped,
        # and no heading is left empty)
        check_not_in("F-12: no 'Inputs changed' section (no baseline exists)", "Inputs changed", text)
        check_not_in("F-12: ... and not its constant 'not checked' line", "sha256", text)
        check("F-12: every heading of the delta has a line under it", all(text.split("\n")[i + 2].startswith("- ") for i, ln in enumerate(text.split("\n")) if ln.startswith("## ")), text)
        # fix Y F-7: the parent's form is read through handoff_check.form_view (the form plus its waiting values file), not handoff.parse
        import handoff_check
        from types import SimpleNamespace
        real_view = handoff_check.form_view
        handoff_check.form_view = lambda path: SimpleNamespace(data={"plan_remarks": [{"id": "PR-1", "row": "applied", "reason": "d"}, {"id": "PR-2", "row": "applied", "reason": "d"}]})
        try:
            build(AUTHOR, "S5-qa-automator-2", write=True)
            seen = Path(delta[0]).read_text(encoding="utf-8")
        finally:
            handoff_check.form_view = real_view
        src = Path(brief_pack.__file__).read_text(encoding="utf-8")
        check("F-7: the status filter is controller.DISCOUNTED, not a re-spelled tuple", "not in DISCOUNTED" in src and '"cancelled"' not in src)
        check_not_in("F-7: rows that only form_view sees (the values file) count: PR-2 is no longer absent", "PR-2 [remark]", seen)
        # fix t-1388 F-3: an agent_id that `bind` set on the record (agent_bound_seq) is a fresh agent, not a resume
        st = {"dispatches": {"S5-qa-automator-1": {"role": AUTHOR}}}
        base = {"rework_of": "S5-qa-automator-1", "agent_id": "agent-7"}
        check_eq("F-3: an id that came with the request is a resume", brief_pack._resumed(base, "S5", AUTHOR, st), True)
        check_eq("F-3: an id bound onto the record (agent_bound_seq) is no resume",
                 brief_pack._resumed(dict(base, agent_bound_seq=3), "S5", AUTHOR, st), False)
        accept_window(c, task, "S5-qa-automator-2")
        fresh = harness_send_fresh(c, task)
        check_eq("a rework with no agent_id (a fresh agent) writes no delta", [p for p in build(AUTHOR, fresh, write=True)["written"] if p.endswith("-delta.md")], [])
    finally:
        cleanup(project)


def accept_window(c, task, ident):
    from test_controller_rework_scope import evidence
    c.apply("accept", {"id": ident, "status": "accepted", "stage_complete": False, "unresolved": True, "reason": "the repair round is open",
                       "evidence_refs": [evidence(task, ident + ".txt")], "idempotency_key": ident + "-ok"})


def harness_send_fresh(c, task):
    send(c, task, "S5-qa-automator-3", AUTHOR, scope=["TC-1", "TC-2"], rework_of="S5-qa-automator-2", repair_cause="test_defect", reason="again")
    return "S5-qa-automator-3"


def k8_legacy():
    project = temp_project("qa-bp-legacy-")
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        task.mkdir(parents=True)
        put(task, "pipeline.json", json.dumps({"ticket": TICKET, "size": "S", "environment": "local", "stages": {}, "gates": {}, "halts": []}))
        c = s5_story(task, cases=("TC-1", "TC-2"), with_case_files=True, mark=False)
        harness.use_project(project)
        put(task, SP.PLAN_REL, json.dumps({"schema": 1, "cases": [], "tests": []}))      # a plan file lying about: the form is by records
        with harness.run_mode("driver"):
            send(c, task, "S5-qa-automator-1", AUTHOR, scope=["TC-1", "TC-2"])
        got = build(AUTHOR, "S5-qa-automator-1", write=True)
        text = got["markdown"]
        check_not_in("legacy: the plan is not named", "s5-plan.json", text)
        check_not_in("legacy: no plan slice line", "Plan slice", text)
        check_not_in("legacy: no plan card rows", "s5_plan.py", text)
        check_eq("legacy: no side file but the brief", [Path(p).name for p in got["written"]], ["S5-qa-automator-1.md"])
        check_in("legacy: the window line is the same", "window 1 of 1", text)
    finally:
        cleanup(project)


# The doors-only overflow of the plan critic's brief, measured at G4b (t-1884 m-8, AR-20): the brief may be this large, in bytes, when the
# trimmer reports `doors only`. SHRINK-ONLY: a raise needs a named reason in the verdict, never a quiet edit of this number.
DOORS_ONLY_BRIEF_MAX = 6443   # CI fix G8 (AR-20, a named raise 6403 -> 6443): measured on CI (LF); a Windows run measures lower because its temp paths are shorter (the brief has no CR). Was 6401 at G4b, +2 B at m-1 (t-1884)


def ceiling_verdict(got):
    """(ok, note): a brief under the ceiling is ok; over it, ok ONLY when the trimmer reports `doors only` (nothing non-door is left
    to trim: the doors are never cut, so the overflow is REPORTED) AND the size is within `DOORS_ONLY_BRIEF_MAX`; any other overflow is red."""
    size, reasons = got["budget_bytes"], got["over_ceiling"]
    if size <= brief_pack.BRIEF_MAX_BYTES:
        return True, ""
    if "doors only" in reasons and size <= DOORS_ONLY_BRIEF_MAX:
        return True, f"doors-only overflow: {size} B over a ceiling of {brief_pack.BRIEF_MAX_BYTES} B, over_ceiling={reasons}"
    return False, f"{size} B, over_ceiling={reasons}"


def k9_grouping_hint_line():
    """t-1502 G-1 (K7): the plan critic's line about the grouping hints. On the producer's REAL plan (the call the brief makes), then in a
    full brief of a story whose tests share a file (the line is in the head, and the brief stays under its ceiling)."""
    from test_s5_plan_grouping import GROUPED, REASON, fixture_plan, fixture_story, write_plan
    line = "`s5_plan.py --check` prints 1 grouping hint(s): tests at one level in one file that each prove one case."
    with fixture_story() as (project, task):
        def lines(role, plan=None):
            if plan is not None:
                write_plan(task, plan)
            return brief_pack.plan_dispatch_lines(task, "QA-1", "S5-plan-x-1", role, {}, False, project)["head"]
        critic = lines(CRITIC)
        found = [h for h in critic if "grouping hint" in h]
        check_eq("K7: the producer's real plan: ONE grouping line in the critic's head", len(found), 1)
        check("K7: ... it counts the hints, names the judgement and says 'never a blocker on its own'",
              found and found[0].startswith(line) and "whether each `apart_reason` holds (rubric «On the plan»)" in found[0]
              and found[0].endswith("a test left unmerged is a remark, never a blocker on its own"), str(found))
        check_eq("K7: the author's head has the grouping rule and no critic line", [h for h in lines(AUTHOR) if "grouping hint" in h], [])
        answered = fixture_plan()
        for test in answered["tests"]:
            if test["cases"][0] in GROUPED:
                test["apart_reason"] = REASON
        check_eq("K7: every candidate with its reason: no grouping line", [h for h in lines(CRITIC, answered) if "grouping hint" in h], [])
        put(task, SP.PLAN_REL, "{not json")
        check_eq("K7: a plan that cannot be read: no line (its finding is the plan check's)", [h for h in lines(CRITIC) if "grouping hint" in h], [])
        write_plan(task, fixture_plan())
        real = SP.plan_for_hints
        SP.plan_for_hints = lambda root: (None, "RuntimeError: " + "z" * 200)
        try:
            noted = [h for h in lines(CRITIC) if "grouping hints" in h]
        finally:
            SP.plan_for_hints = real
        check("K7: hints that could not be computed are said, with the words cut at 80", len(noted) == 1 and noted[0].startswith("grouping hints not computed (RuntimeError: ")
              and len(noted[0]) <= len("grouping hints not computed ()") + 80, str(noted))
    # the whole brief: two tests of one file in a story built by the helpers of this file
    project, task, c = story(cases=("TC-1", "TC-2", "TC-3"))
    try:
        plan = SP.load(task)
        for test in plan["tests"]:
            test["file"], test["shape"], test["level"] = "tests/test_same.py", "new", "api"
        atomic_json(task / SP.PLAN_REL, plan)
        got = build(CRITIC, "S5-plan-critic-1")
        check_in("K7: the full brief of the plan critic carries the line in its head", "prints 1 grouping hint(s)", head_of(got["markdown"]))
        ok, note = ceiling_verdict(got)
        check("K7: ... and the brief stays under its ceiling (a doors-only overflow is reported, not failed)", ok, note)
        if note:
            print("REPORT K7:", note)
        # CI fix G4b: the verdict itself, at and beyond the ceiling, with the negative controls
        top = brief_pack.BRIEF_MAX_BYTES
        check("K7 verdict: exactly at the ceiling is green", ceiling_verdict({"budget_bytes": top, "over_ceiling": []})[0], "")
        check("K7 verdict: over with doors only is green and reported",
              ceiling_verdict({"budget_bytes": DOORS_ONLY_BRIEF_MAX, "over_ceiling": ["doors only"]})[0] and
              bool(ceiling_verdict({"budget_bytes": DOORS_ONLY_BRIEF_MAX, "over_ceiling": ["doors only"]})[1]), "")
        check("K7 verdict: one byte past the pinned doors-only size stays RED (the number only shrinks)",
              not ceiling_verdict({"budget_bytes": DOORS_ONLY_BRIEF_MAX + 1, "over_ceiling": ["doors only"]})[0], "")
        check("K7 verdict: over with words at level 1 and doors only is green (nothing non-door is left to trim)",
              ceiling_verdict({"budget_bytes": top + 1, "over_ceiling": ["words at level 1", "doors only"]})[0], "")
        check("K7 verdict: one byte over with only a trimmable non-door reason (no `doors only`) stays RED",
              not ceiling_verdict({"budget_bytes": top + 1, "over_ceiling": ["words at level 1"]})[0], "")
        check("K7 verdict: one byte over with no reason named stays RED",
              not ceiling_verdict({"budget_bytes": top + 1, "over_ceiling": []})[0], "")
    finally:
        cleanup(project)


def k12_helpers_section():
    """TQ1-19 D2-K12 / D2-8: the header section `## Helpers that already exist`: the functions and public methods of the modules the
    window's test files import, at most 60 names (60 without a tail, 61 with `(+1 more: repo map)`), the line that says none was found,
    and the section stays in the header at the cap. Kills M-D2-6 (a section with no `+N`)."""
    project = temp_project("qa-bp-helpers-")
    try:
        harness.use_project(project)
        plan = one_target_plan("tests/test_cap.py::test_cap", file="tests/test_cap.py")
        write_code(project, "tests/test_cap.py", "def test_cap():\n    assert True\n")
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0]
        check_in("D2-8: no import, no module: the section says so", "no helper module found in the imports of this window", text)
        check("D2-K12: the section stands in the header, before the excerpts", 0 <= text.find("## Helpers that already exist") < text.find("## T-1"), text[:400])

        def with_names(total):
            names = "".join(f"def pub_{n}():\n    return {n}\n\n\n" for n in range(total))
            write_code(project, "tests/helpers.py", names + "def _private():\n    return 0\n\n\nclass Page:\n    def public_m(self):\n        return 1\n\n    def _hidden(self):\n        return 2\n")
            write_code(project, "tests/test_cap.py", "from tests.helpers import pub_0\n\n\ndef test_cap():\n    assert True\n")
            return brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0]
        text = with_names(2)
        check_in("the module and its public names", "`tests/helpers.py`: `pub_0`, `pub_1`, `public_m`", text)
        check_not_in("a private name is not listed", "_private", text)
        check_not_in("... nor a private method", "_hidden", text)
        check_not_in("D2-8 at 3 names: no tail", "more: repo map", text)
        text = with_names(59)           # 59 functions + public_m = 60 names
        check_eq("D2-8 AT 60 names: no tail", "more: repo map" in text, False)
        text = with_names(60)           # 61 names
        check_in("D2-8 BEYOND 60 (61): the tail counts the one", "(+1 more: repo map)", text)
        check_not_in("... and the 61st name is not shown", "public_m", text)
        text = with_names(60)
        check("D2-8: the section is a header, so the cap does not drop it", "## Helpers that already exist" in text and len(text.encode("utf-8")) <= brief_pack.CODE_FILE_BYTES)
        # F-7: the brief reads imports as the exit gate does (`copy_detector.imported_files`): a relative import is a module too
        write_code(project, "tests/helpers.py", "def rel_helper():\n    return 1\n")
        write_code(project, "tests/test_cap.py", "from .helpers import rel_helper\n\n\ndef test_cap():\n    assert True\n")
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0]
        check_in("F-7: a relative import is listed, the gate would refuse a copy of it", "`tests/helpers.py`: `rel_helper`", text)
        # F-8: a test file that is not written yet is NAMED, never read as 'no helper'; a `uses` fixture's file is followed
        (project / "tests" / "test_cap.py").unlink()
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-1")[0]
        check_in("F-8: the unwritten file is named as not read", "not read (not written yet, or not parsed): `tests/test_cap.py`", text)
        check_not_in("F-8: ... and the section does not say there is no helper (an unknown is not a fact, FR-41)", "no helper module found", text)
        write_code(project, "tests/conftest.py", "import pytest\nfrom helpers import rel_helper\n\n\n@pytest.fixture\ndef fx():\n    return rel_helper()\n")
        with_fixture = one_target_plan("tests/test_cap.py::test_cap", uses=["fx"], file="tests/test_cap.py")
        text = brief_pack.window_code_file(project, with_fixture, with_fixture["tests"], "D-1")[0]
        check_in("F-8: the imports of the `uses` fixture's file are followed", "`tests/helpers.py`: `rel_helper`", text)
        check_in("F-8: ... and the unwritten test file is still named", "not read (not written yet, or not parsed): `tests/test_cap.py`", text)
    finally:
        cleanup(project)


def shared_world(project, old: dict, fixtures=("client_fx",)):
    """A project with a conftest of `fixtures`, one old test file per entry of `old` ({instance: (fixture it asks for or None, has a
    receipt)}) and the manifest that lists them; the task root the brief is built for."""
    write_code(project, "tests/conftest.py", "import pytest\n\n\n" + "\n\n".join(
        f"@pytest.fixture\ndef {name}():\n    return 1\n" for name in fixtures))
    rows = []
    for iid, (uses, receipted) in old.items():
        write_code(project, f"tests/test_{iid}.py", f"def {iid}({uses or ''}):\n    assert True\n")
        row = {"instance_id": iid, "file": f"tests/test_{iid}.py", "case": "TC-0", "covers": ["TC-0"]}
        if receipted:
            row["sensitivity_proof"] = {"receipt_ref": {"path": f"work/sensitivity-receipts/{iid}.json", "sha256": "0" * 64}}
        rows.append(row)
    task_root = project / "qa-factory" / "artifacts" / "QA-1"
    write_code(project, "qa-factory/artifacts/QA-1/work/automation-manifest.json", json.dumps({"tests": rows}))
    return task_root


def hf8_18_n3_the_window_names_what_its_fixture_edit_makes_stale():
    """C-K7, C-K8, C-6, C-7, C-K13: the header of the code file lists, per EXISTING fixture the window uses, the instances of earlier
    windows that hold a receipt and reach it. Kills (M-C5): instances with no receipt listed; a `new: true` fixture listed."""
    project = temp_project("qa-bp-shared-")
    try:
        harness.use_project(project)
        task_root = shared_world(project, {"test_old_a": ("client_fx", True), "test_old_b": ("client_fx", False),
                                           "test_old_c": (None, True), "test_old_d": ("client_fx", True)})
        write_code(project, "tests/test_new.py", "def test_new(client_fx):\n    assert True\n")
        plan = one_target_plan("tests/test_new.py::test_new", uses=["client_fx"])
        text, omitted = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)
        check_in("C-K7: the section is in the header", "## If you change a shared fixture", text)
        check_in("C-K7: the fixture and the instances of earlier windows with a receipt that reach it",
                 "- `client_fx (tests/conftest.py)` -> `test_old_a`, `test_old_d`", text)
        check_not_in("M-C5: an instance with no receipt is not named", "test_old_b", text)
        check_not_in("an instance that does not reach the fixture is not named", "test_old_c", text)
        check_in("no ban: the consequence is said as one", "the factory proves them again at S6", text)
        check("the section stands in the header, before the excerpts", 0 <= text.find("## If you change a shared fixture") < text.find("## fixture client_fx"),
              text[:400])
        check_not_in("the window's own test is not an 'earlier' instance", "`test_new`", text.split("## fixture client_fx")[0].split("## If you change")[1])
        # no task root (a caller that has none): the section is simply absent, as before
        check_not_in("no task root - no section", "If you change a shared fixture", brief_pack.window_code_file(project, plan, plan["tests"], "D-3")[0])
        # C-K7: a fixture the plan introduces - nothing to say (M-C5)
        new = one_target_plan("tests/test_new.py::test_new", uses=["client_fx"], fixtures=[{"name": "client_fx", "file": "tests/conftest.py", "new": True}])
        check_not_in("C-K7: a `new: true` fixture - no section", "If you change a shared fixture",
                     brief_pack.window_code_file(project, new, new["tests"], "D-3", task_root)[0])
        # C-K8: a window that uses no fixture
        bare = one_target_plan("tests/test_new.py::test_new")
        check_not_in("C-K8: a window with no `uses` - no section", "If you change a shared fixture",
                     brief_pack.window_code_file(project, bare, bare["tests"], "D-3", task_root)[0])
        # C-6: a manifest that cannot be read is one line, no section, no exception; an absent one (the first window) is silence
        write_code(project, "qa-factory/artifacts/QA-1/work/automation-manifest.json", "{not json")
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)[0]
        check_not_in("C-6: an unreadable manifest - no section", "If you change a shared fixture", text)
        check_in("C-6: ...one line says it and what is not listed", "the manifest cannot be read (JSONDecodeError)", text)
        (task_root / "work" / "automation-manifest.json").unlink()
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)[0]
        check("C-6: no manifest yet (the first window) - no section and no line about it",
              "If you change a shared fixture" not in text and "manifest cannot be read" not in text, text[-300:])
        # C-6: a receipt-holding instance whose file does not parse: what it reaches is unknown, said once
        task_root = shared_world(project, {"test_old_a": ("client_fx", True), "test_old_e": ("client_fx", True)})
        write_code(project, "tests/test_test_old_e.py", "def test_old_e(:\n")
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)[0]
        check_in("C-6: the readable instance is still listed", "`test_old_a`", text)
        check_in("C-6: the unreadable one is a line under 'Not found', named", "test_old_e reach could not be read", text)

        # C-7: AT the limit (20) no tail, BEYOND it (21) twenty and `(+1 more)`
        for count, tail in ((20, False), (21, True)):
            old = {f"test_o{n:02d}": ("client_fx", True) for n in range(count)}
            task_root = shared_world(project, old)
            text = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)[0]
            line = next(l for l in text.splitlines() if l.startswith("- `client_fx (tests/conftest.py)`"))
            check_eq(f"C-7 {count} instances: {'twenty and the tail' if tail else 'all twenty, no tail'}",
                     (line.count("`test_o") , "(+1 more)" in line), (20, tail))
    finally:
        cleanup(project)


def k13_base_log_lines():
    """TQ1-18 F-5 / Q-2: the code critic's head carries, per instance of its scope, the attempt id and the log path of the CURRENT run
    row (`case_stamp.run_row_for`), so `base_outcome {outcome, run}` is read from a log nobody searches for. Other roles: nothing; no
    current row: ONE line that says so (FR-41); a log path that cannot be read: the attempt id and the way to it. Kills: a line for
    the author role (`role` gate), a line built with no row (`no_row`), the log read from the wrong key (`log_path`)."""
    import s5_precheck
    project = temp_project("qa-bp-logs-")
    try:
        harness.use_project(project)
        task = project / "qa-factory" / "artifacts" / "QA-1"
        row = {"case": "TC-1", "covers": ["TC-1"], "file": "tests/test_a.py", "instance_id": "test_a", "test_function": "test_a",
               "case_version_links": [{"case_id": "TC-1", "version": "cv_x"}]}
        put(task, "work/automation-manifest.json", json.dumps({"tests": [row], "unresolved": []}))
        real = s5_precheck.scope_cases
        s5_precheck.scope_cases = lambda *_a, **_k: ["TC-1"]
        try:
            check_eq("the author's brief gets no such line", brief_pack.base_log_lines(task, AUTHOR, "S5-w-1"), [])
            lines = brief_pack.base_log_lines(task, CRITIC, "S5-w-1")
            check("no_row: no run report: ONE line that says there is nothing to record from",
                  len(lines) == 1 and "holds no current row" in lines[0], str(lines))
            report = {"results": [{"instance_id": "test_a", "test_id": "tests/test_a.py::test_a", "status": "passed", "attempt_id": "att-1"}]}
            put(task, "work/run-report.json", json.dumps(report))
            lines = brief_pack.base_log_lines(task, CRITIC, "S5-w-1")
            check_in("no block on disk: the attempt id is named and the way to the log", "run `att-1`, its log path could not be read", "\n".join(lines))
            put(task, "work/run-blocks/20261030T000000000000Z-att-1.json", json.dumps({"attempt_id": "att-1", "evidence": [{"summary": "qa-factory/evidence/s.json"}]}))
            put(project, "qa-factory/evidence/s.json", json.dumps({"log": "qa-factory/evidence/sanity.log"}))
            lines = brief_pack.base_log_lines(task, CRITIC, "S5-w-1")
            check_eq("the attempt id and the log path of the instance's current row",
                     lines, ["Run log of `tests/test_a.py::test_a`: run `att-1`, log `qa-factory/evidence/sanity.log`"])
        finally:
            s5_precheck.scope_cases = real
    finally:
        cleanup(project)


def hf8_18_n3_the_section_has_a_byte_budget():
    """C-K13 (B3), the form of 12586: 20 fixtures the window uses, 60 earlier instances reaching them, at the id lengths of the real
    manifest (48, 55, 67; min 48, median 55, max 67) and one beyond (70): the section stays within `SHARED_SECTION_BYTES`, the file
    within `CODE_FILE_BYTES`, and what was cut is COUNTED - `(+N more)` on a fixture line, the count in the `Left out` heading.
    Kills: the budget removed (the file at 55 loses every excerpt, at 70 breaks the cap)."""
    names = [f"fx_{n:02d}_with_a_long_descriptive_name" for n in range(20)]
    asks = ", ".join(names)
    for length in (48, 55, 67, 70):
        project = temp_project("qa-bp-shared-big-")
        try:
            harness.use_project(project)
            old = {f"test_{'x' * (length - 7)}{n:02d}": (asks, True) for n in range(60)}
            check_eq(f"id length {length}", {len(i) for i in old}, {length})
            task_root = shared_world(project, old, fixtures=names)
            write_code(project, "tests/test_new.py", f"def test_new({asks}):\n    assert True\n")
            plan = one_target_plan("tests/test_new.py::test_new", uses=names)
            text, omitted = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)
            size, shown = len(text.encode("utf-8")), text.count("```python")
            section = text.split("## If you change a shared fixture")[1].split("\n## ")[0]
            print(f"C-K13 MEASURED: 20 fixtures x 60 earlier instances, id length {length}: file {size} B of {brief_pack.CODE_FILE_BYTES}, "
                  f"section {len(section.encode('utf-8'))} B of {brief_pack.SHARED_SECTION_BYTES}, excerpts shown {shown}, left out {len(omitted)}")
            check(f"C-K13 ({length}): the file is within CODE_FILE_BYTES", size <= brief_pack.CODE_FILE_BYTES, str(size))
            check(f"C-K13 ({length}): the section is within its budget", len(section.encode("utf-8")) <= brief_pack.SHARED_SECTION_BYTES, str(len(section)))
            check(f"C-K13 ({length}): the excerpts are kept (at least the test's own and half of the fixtures)", shown >= 11, str(shown))
            check_eq(f"C-K13 ({length}): shown + omitted = every excerpt the window asked for", shown + len(omitted), 20 + 1)
            lines = [l for l in text.splitlines() if l.startswith("- `fx_")]
            check(f"C-K13 ({length}): a fixture line that lost names says how many (+N more)", bool(lines) and all("more)" in l for l in lines), str(lines[:1]))
            if omitted:
                check_in(f"C-K13 ({length}): the heading counts the excerpts left out", f"## Left out ({len(omitted)} excerpts;", text)
        finally:
            cleanup(project)


def hf8_18_n3_the_budget_at_and_beyond():
    """B3: `_shared_fixture_lines` AT the budget (a section that fits whole has no tail) and BEYOND it (names cut from the end of each
    fixture's list with `(+N more)`; fixtures that cannot show one name are one last line); never more than `SHARED_SECTION_BYTES`."""
    small = brief_pack._shared_fixture_lines({"fx_a (tests/conftest.py)": ["test_a", "test_b"]})
    check_in("at the budget: a small section is whole", "- `fx_a (tests/conftest.py)` -> `test_a`, `test_b`", "\n".join(small))
    check_not_in("at the budget: no tail", "more", "\n".join(small))
    check_eq("no fixture, no section", brief_pack._shared_fixture_lines({}), [])
    many_names = {f"fx_{n:02d} (tests/conftest.py)": [f"test_{'y' * 60}{i:02d}" for i in range(20)] for n in range(20)}
    text = "\n".join(brief_pack._shared_fixture_lines(many_names))
    check("beyond the budget: the section is within it", len(text.encode("utf-8")) <= brief_pack.SHARED_SECTION_BYTES, str(len(text)))
    check("beyond the budget: every fixture keeps a line with a name and a count of what was cut",
          all(f"fx_{n:02d}" in text for n in range(20)) and text.count("more)") == 20, text[-300:])
    crowd = {f"fx_{n:03d} (tests/conftest.py)": [f"test_{'z' * 60}{i:02d}" for i in range(3)] for n in range(200)}
    text = "\n".join(brief_pack._shared_fixture_lines(crowd))
    check("200 fixtures: within the budget", len(text.encode("utf-8")) <= brief_pack.SHARED_SECTION_BYTES, str(len(text)))
    check("200 fixtures: the last line counts the fixtures not listed", bool(re.search(r"\n- \(\+\d+ more fixtures not listed\)$", text)), text[-120:])


def hf8_18_n3_what_it_could_not_read_is_a_line():
    """F5 (AR-28) and F6: a conftest that does not parse, and a manifest that parses to a list, are ONE line each, never silence; a
    plan path spelled `./tests/conftest.py` or `tests\\conftest.py` still gets its section. Kills: `_notes` of `_fixture_closure`
    dropped; a non-dict manifest as 'no rows'; the raw spelling of the plan's path as the key."""
    project = temp_project("qa-bp-shared-unread-")
    try:
        harness.use_project(project)
        task_root = shared_world(project, {"test_old_a": ("client_fx", True)})
        write_code(project, "tests/test_new.py", "def test_new(client_fx):\n    assert True\n")
        plan = one_target_plan("tests/test_new.py::test_new", uses=["client_fx"])
        # F5: a conftest of an earlier instance's folder that does not parse
        write_code(project, "tests/sub/conftest.py", "def broken(:\n")
        write_code(project, "tests/sub/test_old_s.py", "def test_old_s(client_fx):\n    assert True\n")
        manifest = json.loads((task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        manifest["tests"].append({"instance_id": "test_old_s", "file": "tests/sub/test_old_s.py", "case": "TC-0", "covers": ["TC-0"],
                                  "sensitivity_proof": {"receipt_ref": {"path": "work/sensitivity-receipts/test_old_s.json", "sha256": "0" * 64}}})
        write_code(project, "qa-factory/artifacts/QA-1/work/automation-manifest.json", json.dumps(manifest))
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)[0]
        note = [l for l in text.split("## Not found, not checked")[1].splitlines() if "conftest" in l and "incomplete" in l] if "## Not found" in text else []
        check("F5: a conftest that does not parse is one line, saying the list may be incomplete", len(note) == 1, text[-500:])
        # F5: a manifest that parses but is not an object
        write_code(project, "qa-factory/artifacts/QA-1/work/automation-manifest.json", "[1, 2]")
        text = brief_pack.window_code_file(project, plan, plan["tests"], "D-3", task_root)[0]
        check_in("F5: a manifest that is a list - one line", "the manifest cannot be read (it holds list, not an object)", text)
        check_not_in("F5: ...and no section", "If you change a shared fixture", text)
        # F6: the plan's path spelled other than the one the closure uses
        task_root = shared_world(project, {"test_old_a": ("client_fx", True)})
        for spelling in ("./tests/conftest.py", "tests\\conftest.py", "tests/conftest.py"):
            fixtures = [{"name": "client_fx", "file": spelling}]
            spelled = one_target_plan("tests/test_new.py::test_new", uses=["client_fx"], fixtures=fixtures)
            text = brief_pack.window_code_file(project, spelled, spelled["tests"], "D-3", task_root)[0]
            check_in(f"F6: the plan says `{spelling}` - the section is there, under the one spelling",
                     "- `client_fx (tests/conftest.py)` -> `test_old_a`", text)
    finally:
        cleanup(project)


def k11_budget_is_path_independent():
    """GM3 (AR-4): the budget measure counts a brief the same at any checkout path - the same text built with a 20-character and an
    80-character plugin root weighs the same; an empty root is skipped; a root that is the prefix of another goes second."""
    short, long_ = "C:/work/qa-plugin-x1234", "C:/" + "w" * 77          # 23 and 80 characters
    assert len(short) >= 20 and len(long_) == 80
    def body(root):
        return f"- {root}/references/code-review-rubric.md (9.4 KB)\nrun `python \"{root}/scripts/x.py\"`\n"
    a, b = brief_pack.measured_bytes(body(short), [short]), brief_pack.measured_bytes(body(long_), [long_])
    check_eq("K11: the same text at a 20-char and an 80-char root weighs the same", a, b)
    project, _task, _c = story()
    try:
        # the measure is applied to a copy: a brief the code BUILDS keeps the real plugin path in its text
        built = build(AUTHOR, "S5-plan-author-1")["markdown"]
        check_in("K11: ... and a built brief still carries the real plugin path (the measure does not rewrite the brief)", brief_pack.SCRIPTS, built)
    finally:
        cleanup(project)
    check_eq("K11: an empty or None root is skipped", brief_pack.measured_bytes("abc", ["", None]), 3)
    check_eq("K11: a root that is the prefix of another is replaced longest first",
             brief_pack.measured_bytes("C:/a/b/x C:/a/y", ["C:/a", "C:/a/b"]), len("<plugin>/x <plugin>/y"))
    check_eq("K11: a backslash spelling of the root is replaced too",
             brief_pack.measured_bytes("C:\\a\\b\\x", ["C:/a/b"]), len("<plugin>\\x"))


def main():
    k13_base_log_lines()
    k12_helpers_section()
    k1_plan_dispatch()
    k9_grouping_hint_line()
    k2_plan_over_the_cap()
    k3_window_plan_slice()
    k4_over_cap_and_head()
    k5_code_file()
    k6_code_file_cap()
    hf8_18_n3_the_window_names_what_its_fixture_edit_makes_stale()
    hf8_18_n3_the_section_has_a_byte_budget()
    hf8_18_n3_the_budget_at_and_beyond()
    hf8_18_n3_what_it_could_not_read_is_a_line()
    k10_marker_form()
    k7_delta()
    k8_legacy()
    k11_budget_is_path_independent()
    finish("test_brief_pack_s5_plan")


if __name__ == "__main__":
    main()
