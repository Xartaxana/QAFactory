#!/usr/bin/env python3
"""One test, three cases, one red assert: the reader of "red by the requirement" and the fixtures every reader shares
(HF2-3, GW1-22; spec t-085 rev. 3, part 3a1).

TP1-12586 (22-24.10.2026): the msteams test covers TC-004, TC-005 and TC-006 and stops at TC-004's Then 2. The
generic tests of TC-005 and TC-006 are green. `acceptance.red_by_requirement` is the ONE reader of which instance is red
for which `contradicts_requirement` row (every matching row, N1), `acceptance.row_slice` the ONE reader of what a row's
slice keys mean (N5), `acceptance.red_by_own_row` the ONE "is this its own case's row" predicate.

This file EXPORTS the fixtures the other parts read (3a2, 3c1, 3c2): `shape_a()`, `shape_b()`, `with_stale_rows()`,
`report_bytes()`. Each story is `{manifest, texts, report, runs}`: `texts` maps a case to its markdown (two Thens),
`report` is a run report with `current_results`, `runs` is the map `window_record._terminal_runs` returns.

Keys: K3b/K3 (test_contract), K6 shapes, K6b two rows of two cases, K6c the report source, K7 the adversarial battery,
K8 refusals, K9 error direction, K10 census (test_then_remainder).

Part 3c1 (ledger, delivery check) adds, below the 3a1 keys: `3c1-K1` the whole-case row of a failed case, `3c1-K2` the ledger
states of both shapes (variant (b), the safe default: the owner's word on FA-11 (a) is pending, so no key pins the failure-site
reader), `3c1-K7` the delivery check on a task on disk, `3c1-K9` the words a person reads.
"""
import copy
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import acceptance as AC  # noqa: E402
import contract as C  # noqa: E402
import ledger as L  # noqa: E402

MS = "test_move_ms_teams_integration_to_other_project"
G5 = "test_generic_integration_leaves_source_project_after_move"
G6 = "test_generic_integration_leaves_source_project_after_move_tc006"
MS_FILE = "tests/test_move.py"
CASES = ("TC-004", "TC-005", "TC-006")
RED_ROW = {"case": "TC-004", "reason": "contradicts_requirement", "instance_ids": [MS], "thens": [2],
           "detail": "the msteams integration is not moved to the other project"}


def _ms_ref(case: str, then: int, refs: str) -> str:
    """`pinned`: the author pinned two clauses to their own lines; `default`: every clause is the span of the function."""
    pinned = {("TC-004", 2): "14-16", ("TC-005", 1): "11-12"} if refs == "pinned" else {}
    return f"{MS_FILE}:{pinned.get((case, then), '10-30')}"


def _covered(case: str, then: int, iid: str, ref: str) -> dict:
    return {"case": case, "then": then, "instance_id": iid, "assertion_ref": ref, "status": "covered"}


def _blocked(case: str, then: int) -> dict:
    return {"case": case, "then": then, "instance_id": MS, "assertion_ref": None, "status": "unresolved",
            "reason": "blocked_by_check", "blocking_check": "TC-004",
            "detail": f"check {case} Then {then} on msteams once TC-004 is fixed"}


def _row(iid: str, status: str) -> dict:
    return {"instance_id": iid, "test_id": f"{MS_FILE}::{iid}", "status": status}


def _story(shape: str, refs: str) -> dict:
    tests = [{"instance_id": MS, "file": MS_FILE, "covers": list(CASES), "partitions": ["P-msteams"], "status": "red"},
             {"instance_id": G5, "file": "tests/test_generic.py", "covers": ["TC-005"], "partitions": ["P-generic"],
              "status": "green"},
             {"instance_id": G6, "file": "tests/test_generic.py", "covers": ["TC-006"], "partitions": ["P-generic"],
              "status": "green"}]
    bindings = [_covered("TC-004", n, MS, _ms_ref("TC-004", n, refs)) for n in (1, 2)]
    for case, generic in (("TC-005", G5), ("TC-006", G6)):
        bindings += [_covered(case, n, generic, "tests/test_generic.py:5-9") for n in (1, 2)]
        bindings += [(_covered(case, n, MS, _ms_ref(case, n, refs)) if shape == "b" else _blocked(case, n))
                     for n in (1, 2)]
    manifest = {"tests": tests, "then_bindings": bindings, "unresolved": [copy.deepcopy(RED_ROW)]}
    texts = {case: f"---\nid: {case}\nstatus: Approved\n---\n## Then\n1. The first result of {case} is shown.\n"
                   f"2. The second result of {case} is shown.\n" for case in CASES}
    results = [dict(_row(MS, "failed"), case="TC-004", covers=list(CASES), attempt_id="a1"),
               dict(_row(G5, "passed"), covers=["TC-005"], attempt_id="a1"),
               dict(_row(G6, "passed"), covers=["TC-006"], attempt_id="a1")]
    runs = {row["instance_id"]: (row, {"results": [row]}, Path("work/run-blocks/20261024T000000Z-a1.json"))
            for row in map(copy.deepcopy, results)}
    return {"manifest": manifest, "texts": texts, "report": {"current_results": results}, "runs": runs}


def shape_a(refs: str = "default") -> dict:
    """The blocked shape: TC-005 / TC-006 Then 1-2 on the msteams test are `blocked_by_check` rows (blocking_check TC-004)."""
    return _story("a", refs)


def shape_b(refs: str = "default") -> dict:
    """The carried-over shape: the Thens of TC-005 / TC-006 sit BEFORE the red assert in the msteams test, covered, no blocked rows."""
    return _story("b", refs)


def with_stale_rows(story: dict, cases: list) -> dict:
    """A copy of `story` with the live 12586 stale form appended for each case: a partition row, no `thens` (t-1216 section 5)."""
    out = copy.deepcopy(story)
    for case in cases:
        out["manifest"]["unresolved"].append({"case": case, "reason": "contradicts_requirement",
                                              "partitions": ["P-msteams"], "detail": "stale: the old form of the row"})
    return out


def report_bytes(site: str = "rel:15") -> bytes:
    """A pytest junit report of the msteams test failing at `site` (`rel:<line>`, `rel` is the test file)."""
    where = site.replace("rel", MS_FILE, 1)
    return (f'<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="3" failures="1">'
            f'<testcase classname="tests.test_move" name="{MS}"><failure message="assert False">'
            f'    def {MS}():\n&gt;       assert moved\nE       assert False\n\n{where}: AssertionError</failure></testcase>'
            f'<testcase classname="tests.test_generic" name="{G5}"/>'
            f'<testcase classname="tests.test_generic" name="{G6}"/></testsuite></testsuites>').encode("utf-8")


def items() -> list:
    return [{"instance_id": i} for i in (MS, G5, G6)]


def red(story: dict, **kw) -> dict:
    manifest = story["manifest"]
    return AC.red_by_requirement(manifest, items(), AC.story_scope(manifest), **kw)


def with_status(story: dict, iid: str, status: str) -> dict:
    out = copy.deepcopy(story)
    for row in out["report"]["current_results"]:
        if row["instance_id"] == iid:
            row["status"] = status
    row, block, path = out["runs"][iid]
    out["runs"][iid] = (dict(row, status=status), block, path)
    return out


# --- the fixtures are what they say ------------------------------------------------------------------------------

def the_fixtures() -> None:
    for name, story in (("A", shape_a()), ("B", shape_b())):
        m = story["manifest"]
        check_eq(f"fixture {name}: scope", AC.story_scope(m), {"TC-004": [MS], "TC-005": [MS, G5], "TC-006": [MS, G6]})
        check_eq(f"fixture {name}: two Thens per case in the texts",
                 {c: sum(1 for line in t.splitlines() if line[:2] in ("1.", "2.")) for c, t in story["texts"].items()},
                 {c: 2 for c in CASES})
        blocked = [b for b in m["then_bindings"] if b.get("reason") == "blocked_by_check"]
        check_eq(f"fixture {name}: blocked rows", len(blocked), 4 if name == "A" else 0)
        on_ms = [(b["case"], b["then"]) for b in m["then_bindings"] if b["instance_id"] == MS and b["status"] == "covered"]
        check_eq(f"fixture {name}: covered on the msteams test", on_ms,
                 [("TC-004", 1), ("TC-004", 2)] + ([("TC-005", 1), ("TC-005", 2), ("TC-006", 1), ("TC-006", 2)]
                                                    if name == "B" else []))
        check_eq(f"fixture {name}: the report and the runs agree on who failed",
                 ([r["instance_id"] for r in story["report"]["current_results"] if r["status"] == "failed"],
                  [i for i, (r, _b, _p) in story["runs"].items() if r["status"] == "failed"]), ([MS], [MS]))
    pinned, default = shape_b("pinned")["manifest"], shape_b()["manifest"]
    ref = lambda m, case, then: next(b["assertion_ref"] for b in m["then_bindings"]  # noqa: E731
                                     if (b["case"], b["then"], b["instance_id"]) == (case, then, MS))
    check_eq("fixture: pinned refs", (ref(pinned, "TC-004", 2), ref(pinned, "TC-005", 1), ref(pinned, "TC-005", 2)),
             (f"{MS_FILE}:14-16", f"{MS_FILE}:11-12", f"{MS_FILE}:10-30"))
    check_eq("fixture: default refs are all the span", {b["assertion_ref"] for b in default["then_bindings"]
                                                         if b["instance_id"] == MS}, {f"{MS_FILE}:10-30"})
    stale = with_stale_rows(shape_b(), ["TC-005"])
    check_eq("fixture: a stale row is appended, the original is untouched",
             ([u["case"] for u in stale["manifest"]["unresolved"]], len(shape_b()["manifest"]["unresolved"])),
             (["TC-004", "TC-005"], 1))
    root = ET.fromstring(report_bytes("rel:52"))
    check_in("fixture: the report bytes parse and name the helper line", f"{MS_FILE}:52",
             ET.tostring(root, encoding="unicode"))


# --- K6: both shapes, three sources --------------------------------------------------------------------------------

def k6_shapes() -> None:
    for name, story in (("A", shape_a()), ("B", shape_b())):
        m = story["manifest"]
        before = json.dumps(m, sort_keys=True)
        want = {MS: [m["unresolved"][0]]}
        check_eq(f"K6 {name}: structural (strict=False)", red(story, strict=False), want)
        check_eq(f"K6 {name}: block source (strict=True, runs: msteams failed)", red(story, runs=story["runs"]), want)
        check_eq(f"K6 {name}: report source (current result failed)", red(story, report=story["report"]), want)
        check_eq(f"K6 {name}: no side effects on the manifest", json.dumps(m, sort_keys=True), before)


# --- K6b: every matching row, N1 ---------------------------------------------------------------------------------

def k6b_every_row() -> None:
    story = with_stale_rows(shape_b(), ["TC-005"])
    m = story["manifest"]
    both = [m["unresolved"][0], m["unresolved"][1]]
    got = red(story, strict=False)
    check_eq("K6b: shape B + a stale TC-005 row -> msteams is red by BOTH rows, in the manifest's order", got, {MS: both})
    check_eq("K6b: ... the same from the blocks", red(story, runs=story["runs"]), {MS: both})
    check_eq("K6b: ... and from the report", red(story, report=story["report"]), {MS: both})
    check_eq("K6b: red_by_own_row TC-004 / TC-005 / TC-006",
             [AC.red_by_own_row(got, MS, c) for c in CASES], [True, True, False])
    check_eq("K6b: the generic instances are not red", [AC.red_by_own_row(got, i, "TC-005") for i in (G5, G6)], [False, False])
    check_eq("K6b: shape A + a stale TC-005 row: msteams holds no covered TC-005 Then, so only TC-004's row",
             red(with_stale_rows(shape_a(), ["TC-005"]), strict=False), {MS: [m["unresolved"][0]]})
    three = with_stale_rows(shape_b(), ["TC-005", "TC-006"])
    check_eq("K6b: three rows of three cases, all returned", [r["case"] for r in red(three, strict=False)[MS]], list(CASES))
    check_eq("K6b: red_by_own_row on unreadable input is False",
             (AC.red_by_own_row(None, MS, "TC-004"), AC.red_by_own_row({MS: "x"}, MS, "TC-004"),
              AC.red_by_own_row(got, MS, ""), AC.red_by_own_row({MS: [{"case": ""}]}, MS, ""),
              AC.red_by_own_row(got, "nobody", "TC-004")), (False,) * 5)


# --- K6c: the report is the only source when it is given (N3) -----------------------------------------------------

def k6c_report_source() -> None:
    story = shape_b()
    want = {MS: [story["manifest"]["unresolved"][0]]}
    for status in ("passed", "error", "expected_product_failure", "skipped"):
        check_eq(f"K6c: current result {status} + a row -> not red", red(with_status(story, MS, status),
                 report=with_status(story, MS, status)["report"]), {})
    check_eq("K6c: msteams not in the report -> not red", red(story, report={"current_results": [
        r for r in story["report"]["current_results"] if r["instance_id"] != MS]}), {})
    for odd in ({}, [], "x", 5, {"current_results": "x"}, {"current_results": [None, 3]}):
        check_eq(f"K6c: report {odd!r} -> not red", red(story, report=odd), {})
    passed = with_status(story, MS, "passed")
    check_eq("K6c: report passed, runs say failed, strict=True -> the report is older/newer: not red",
             red(story, report=passed["report"], runs=story["runs"], strict=True), {})
    check_eq("K6c: ... and the other way, the runs say passed and the report failed -> red",
             red(story, report=story["report"], runs=passed["runs"], strict=True), want)
    refused: list = []
    red(passed, report=passed["report"], refused=refused)
    check_eq("K6c: report given, refused stays empty", refused, [])
    odd = copy.deepcopy(story)
    odd["manifest"]["unresolved"][0]["instance_ids"] = ["someone_else"]
    red(odd, report=odd["report"], refused=refused)
    check_eq("K6c: ... even for a red instance whose row names another (no refusal outside the blocks mode)", refused, [])
    red(odd, strict=False, refused=refused)
    check_eq("K6c: ... nor in the structural mode", refused, [])


# --- K7: the adversarial battery ----------------------------------------------------------------------------------

def _variant(edit) -> dict:
    story = copy.deepcopy(shape_b())
    edit(story["manifest"])
    return story


def _entry(story: dict, iid: str = MS) -> dict:
    return next(t for t in story["manifest"]["tests"] if t["instance_id"] == iid)


def k7_battery() -> None:
    def set_row(**kw):
        def edit(m):
            m["unresolved"][0] = dict({"case": "TC-004", "reason": "contradicts_requirement"}, **kw)
        return edit

    def no_partitions(m):
        m["unresolved"][0] = {"case": "TC-004", "reason": "contradicts_requirement", "partitions": ["P-msteams"]}
        m["tests"][0].pop("partitions")

    def other_partitions(m):
        m["unresolved"][0] = {"case": "TC-004", "reason": "contradicts_requirement", "partitions": ["P-a"]}
        m["tests"][0]["partitions"] = ["P-b"]

    def bound_to_one(m):
        m["unresolved"][0]["thens"] = [3]

    def unbound(m):
        m["then_bindings"] = [b for b in m["then_bindings"] if b["case"] != "TC-004"]
        m["unresolved"][0].pop("thens")

    table = [
        ("a row of another case", set_row(case="TC-009", instance_ids=[MS]), "other_case", "TC-004"),
        ("a row naming another instance", set_row(instance_ids=[G5]), "names_other", "TC-004"),
        ("a partition row, an instance with no partitions", no_partitions, "no_partitions", "TC-004"),
        ("P-a against P-b", other_partitions, "other_partition", "TC-004"),
        ("thens [3], bound to Then 1 only", bound_to_one, "", "TC-004"),
        ("no covered binding at all", unbound, "", "TC-004"),
    ]
    for label, edit, code, case in table:
        story = _variant(edit)
        m = story["manifest"]
        if label.startswith("thens [3]"):
            m["then_bindings"] = [b for b in m["then_bindings"] if not (b["case"] == "TC-004" and b["then"] == 2)]
        check_eq(f"K7 {label}: not red (structural)", red(story, strict=False), {})
        check_eq(f"K7 {label}: row_slice says {code or 'nothing (the binding is what fails)'}",
                 AC.row_slice(m["unresolved"][0], _entry(story), case), code)
        for src in ({"runs": story["runs"]}, {"report": story["report"]}):
            check_eq(f"K7 {label}: not red from {sorted(src)[0]} either", red(story, **src), {})
    # the labels of one partition: the raw labels differ, the keys do not (m5)
    story = _variant(lambda m: m["unresolved"][0].update(partitions=["msteams"], instance_ids=[], thens=[2]))
    check_eq("K7: `msteams` against `P-msteams` is ONE partition: red",
             sorted(red(story, strict=False)), [MS])
    check_eq("K7: ... row_slice agrees", AC.row_slice(story["manifest"]["unresolved"][0], _entry(story), "TC-004"), "")
    # (v-b): the latest run decides, the structure does not
    story = shape_b()
    for label, runs, want in (("the latest run passed", with_status(story, MS, "passed")["runs"], {}),
                              ("only an error", with_status(story, MS, "error")["runs"], {}),
                              ("no run at all", {}, {}), ("runs that are no map", [1], {}), ("runs None, no root", None, {})):
        check_eq(f"K7 (v-b): {label} -> not red", red(story, runs=runs), want)


# --- K8: refusals (F7) --------------------------------------------------------------------------------------------

def k8_refusals() -> None:
    door = "manifest_put.py"
    # (a) a green sibling of the same case, a row about the red one only: no refusal for the green one
    story = shape_b()
    m = story["manifest"]
    m["tests"].append({"instance_id": "test_generic_tc004", "file": "tests/test_generic.py", "covers": ["TC-004"],
                       "partitions": ["P-generic"], "status": "green"})
    story["runs"]["test_generic_tc004"] = (_row("test_generic_tc004", "passed"), {}, Path("x.json"))
    refused: list = []
    got = AC.red_by_requirement(m, items() + [{"instance_id": "test_generic_tc004"}], AC.story_scope(m),
                                runs=story["runs"], refused=refused)
    check_eq("K8 a: the green sibling is not red and is not refused", (sorted(got), refused), ([MS], []))
    # (b) a red instance, a row about another instance: one `names_other` refusal with the road
    other = shape_b()
    other["manifest"]["unresolved"][0]["instance_ids"] = ["someone_else"]
    refused = []
    check_eq("K8 b: not red", red(other, runs=other["runs"], refused=refused), {})
    check_eq("K8 b: one refusal, kind names_other, for the red instance", [(k, i) for k, i, _ in refused],
             [("names_other", MS)])
    check_in("K8 b: the sentence names the road", door, refused[0][2])
    check_not_in("K8 b: ... and never the marker", "qa_unresolved", refused[0][2])
    check_in("K8 b: ... and the case, the names and the instance", "someone_else", refused[0][2])
    # (c) a red instance, no contradicts_requirement row about its cases: nothing to refuse
    for label, rows in (("no row at all", []), ("a row about another case only",
                                                [{"case": "TC-009", "reason": "contradicts_requirement"}]),
                        ("a row of another reason", [{"case": "TC-004", "reason": "blocked_by_env", "detail": "x"}])):
        story = shape_b()
        story["manifest"]["unresolved"] = rows
        refused = []
        check_eq(f"K8 c: {label}: not red", red(story, runs=story["runs"], refused=refused), {})
        check_eq(f"K8 c: {label}: nothing refused", refused, [])
    # the other kinds, each with the road and no marker, one per instance
    def variant(edit):
        s = copy.deepcopy(shape_b())
        edit(s["manifest"])
        return s
    kinds = {
        "no_partitions": variant(lambda m: (m["unresolved"].__setitem__(0, {"case": "TC-004", "reason": "contradicts_requirement",
                                                                           "partitions": ["P-msteams"]}), m["tests"][0].pop("partitions"))),
        "other_partition": variant(lambda m: m["unresolved"].__setitem__(0, {"case": "TC-004", "reason": "contradicts_requirement",
                                                                            "partitions": ["P-a"]})),
        "no_then": variant(lambda m: m["unresolved"][0].update(thens=[3])),
    }
    for kind, s in kinds.items():
        refused = []
        red(s, runs=s["runs"], refused=refused)
        check_eq(f"K8: {kind}: one refusal for the red instance", [(k, i) for k, i, _ in refused], [(kind, MS)])
        check_in(f"K8: {kind}: the road", "manifest_put.py --task <T> --fragment <file>", refused[0][2])
        check_not_in(f"K8: {kind}: no marker", "qa_unresolved", refused[0][2])
    unbound = variant(lambda m: (m["then_bindings"].__delitem__(slice(None, None)), m["unresolved"][0].pop("thens")))
    refused = []
    red(unbound, runs=unbound["runs"], refused=refused)
    check_eq("K8: no_then without a `thens` key and no binding", [k for k, _i, _t in refused], ["no_then"])
    check_in("K8: ... its sentence says the row names no Then", "names no Then", refused[0][2])


# --- K9: the error direction --------------------------------------------------------------------------------------

def k9_direction() -> None:
    import window_record
    story = shape_b()
    m = story["manifest"]
    scope = AC.story_scope(m)
    check_eq("K9: manifest None / list / str -> {}", [AC.red_by_requirement(x, items(), scope, strict=False)
                                                      for x in (None, [], "x", 5)], [{}] * 4)
    check_eq("K9: scope empty / None / list -> {}", [AC.red_by_requirement(m, items(), s, strict=False)
                                                     for s in ({}, None, [1])], [{}] * 3)
    check_eq("K9: items None / garbage -> {}", [AC.red_by_requirement(m, i, scope, strict=False)
                                                for i in (None, [None, 3, "x", {}], [{"instance_id": "nobody"}])], [{}] * 3)
    check_eq("K9: no contradicts row -> {} (the empty outcome)",
             AC.red_by_requirement(dict(m, unresolved=[]), items(), scope, strict=False), {})
    check_eq("K9: story_scope on a non-object / no tests -> {}", [AC.story_scope(x) for x in (None, [], {}, {"tests": "x"})], [{}] * 4)
    # runs that cannot be read: the reader of the blocks raises
    real = window_record._terminal_runs

    def boom(_root):
        raise OSError("blocks unreadable")
    window_record._terminal_runs = boom
    root = temp_dir("qa-red-reader-")
    try:
        check_eq("K9: the block reader raises -> {}", AC.red_by_requirement(m, items(), scope, root=root), {})
    finally:
        window_record._terminal_runs = real
        cleanup(root)

    class Broken(dict):
        def get(self, *_a):
            raise OSError("unreadable")
    check_eq("K9: a run map that raises on read -> {}", red(story, runs=Broken(a=1)), {})
    # the real reader, on a tmp story: a failed block makes it red, a passed one does not
    root = temp_dir("qa-red-reader-")
    try:
        blocks = root / "work" / "run-blocks"
        blocks.mkdir(parents=True)
        for status, want in (("failed", [MS]), ("passed", [])):
            (blocks / "20261024T000000Z-b1.json").write_text(json.dumps(
                {"purpose": "initial", "results": [{"instance_id": MS, "status": status}]}), encoding="utf-8")
            check_eq(f"K9: the real block reader, latest run {status}", sorted(AC.red_by_requirement(m, items(), scope, root=root)), want)
    finally:
        cleanup(root)


# --- 3c1: the ledger reads each case by its OWN runs ----------------------------------------------------------------

def plan_state(story: dict, case: str, report: dict | None = None, manifest: dict | None = None) -> tuple:
    """`ledger.plan_row_state` of the plan row `TS-<n>` that holds the one case `case`."""
    row = {"ts": "TS-" + case[-1], "disposition": "automate"}
    return L.plan_row_state(row, story["manifest"] if manifest is None else manifest,
                            story["report"] if report is None else report, {}, {row["ts"]: [case]})


def _without_binding(story: dict, case: str, iid: str) -> dict:
    out = copy.deepcopy(story)
    out["manifest"]["then_bindings"] = [b for b in out["manifest"]["then_bindings"]
                                        if not (b["case"] == case and b["instance_id"] == iid)]
    return out


def k2_ledger_states() -> None:
    blocked = L.BLOCKED_STATE
    check_eq("K2: the state is the ledger's vocabulary", C.is_ledger_state(blocked), True)
    # (a) Shape A: the Thens of TC-005/006 on the stopped test are `blocked_by_check` rows
    a = shape_a()
    got = {c: plan_state(a, c) for c in CASES}
    check_eq("K2 (a) Shape A: TC-004, the case that owns the red, is failed", got["TC-004"][0], "failed:untriaged")
    for case in ("TC-005", "TC-006"):
        state, detail = got[case]
        check_eq(f"K2 (a) Shape A: {case} -> not_executed:blocked_by_check (its own test is green)", state, blocked)
        check_eq(f"K2 (a) Shape A: {case} detail, per Then, the blocker named by its case",
                 detail, f"{case} Then 1: behind TC-004; its other Thens passed; "
                         f"{case} Then 2: behind TC-004; its other Thens passed")
        check_not_in(f"K2 (a) Shape A: {case} detail prints no instance id", "test_", detail)
    # (b) Shape B (the safe default, variant (b)): the Thens sit before the red assert, covered - still not proven
    b = shape_b()
    got = {c: plan_state(b, c) for c in CASES}
    check_eq("K2 (b) Shape B: TC-004 failed", got["TC-004"][0], "failed:untriaged")
    for case in ("TC-005", "TC-006"):
        state, detail = got[case]
        check_eq(f"K2 (b) Shape B: {case} -> not_executed:blocked_by_check", state, blocked)
        check_eq(f"K2 (b) Shape B: {case} detail says it is not proven and where the test stopped", detail,
                 f"{case} Then 1: not proven - the test stopped at TC-004 Then 2; "
                 f"{case} Then 2: not proven - the test stopped at TC-004 Then 2")
        check_not_in(f"K2 (b) Shape B: {case} detail prints no instance id", "test_", detail)
    # the row names no Then: the text invents no number
    nothen = copy.deepcopy(b)
    nothen["manifest"]["unresolved"][0].pop("thens")
    check_eq("K2 (b): a row with no `thens` -> `stopped at TC-004`, no Then number", plan_state(nothen, "TC-005")[1],
             "TC-005 Then 1: not proven - the test stopped at TC-004; TC-005 Then 2: not proven - the test stopped at TC-004")
    # (c) N1: the stale TC-005 row of the live 12586 shape. TC-005's own row + the red -> TC-005 is failed (its own bug)
    stale = with_stale_rows(shape_b(), ["TC-005"])
    got = {c: plan_state(stale, c) for c in CASES}
    check_eq("K2 (c): shape B + a stale TC-005 row: TC-004 failed", got["TC-004"][0], "failed:untriaged")
    check_eq("K2 (c): ... TC-005 failed too (its own row + the red: a case's own row never hides its own bug)",
             got["TC-005"][0], "failed:untriaged")
    check_eq("K2 (c): ... TC-006 (no row of its own) is still behind the red", got["TC-006"][0], blocked)
    # (d) an instance red for TC-004 that has NO binding to TC-005: TC-005 keeps the failed it gets from that instance
    unbound = _without_binding(shape_b(), "TC-005", MS)
    check_eq("K2 (d): the red instance has no binding to TC-005 -> TC-005 failed (the unknown never makes it green)",
             plan_state(unbound, "TC-005")[0], "failed:untriaged")
    check_eq("K2 (d): ... and the other case, which is bound, is behind the red", plan_state(unbound, "TC-006")[0], blocked)
    # (e) N3: the CURRENT result of the msteams test is `passed` while the manifest still holds the row
    passed = with_status(shape_b(), MS, "passed")
    check_eq("K2 (e): current passed + a TC-004 row: TC-004 is claimed red and nobody saw it fail",
             plan_state(passed, "TC-004")[0], "not_executed:contradicts_requirement")
    check_eq("K2 (e): ... TC-005 is read by its own runs: green", plan_state(passed, "TC-005")[0], "passed_green")
    # the allowed error direction on `error` / `expected_product_failure`: never a pass
    # HF3-7 C-K2 (F-5 (b), FR-10, B3): `expected_product_failure` has no producer (the run-report validator refuses it), so it
    # is a word outside the vocabulary: it reads "not executed, the run recorded <word>" in the plan row, as the trace table
    # reads `not run` - never `failed:untriaged` (that was `rollup_status` reading it as a failure), never `passed_green`.
    # TC-005 and TC-006 have the word on the shared test and a `passed` on their own generic test: the rollup does NOT fold
    # that into `partial` (B3), so the row says what the run recorded. The expectation changed from `failed:untriaged` on the
    # requirement of the finding (FR-10: summary, trace and ledger agree; FR-41/FR-59: the unknown is not a failure, not a pass).
    word = "expected_product_failure"
    for status, want5 in (("error", "error"),
                          (word, f"not_executed:the run recorded {word} for this row's cases")):
        odd = with_status(shape_b(), MS, status)
        check_eq(f"K2: current {status} is not red by the reader; TC-005 reads the run's word, never green",
                 plan_state(odd, "TC-005")[0], want5)
        check_eq(f"K2: ... TC-004 with a row and a {status} run", plan_state(odd, "TC-004")[0],
                 "not_executed:contradicts_requirement")
    odd = with_status(shape_b(), MS, word)
    check_eq("C-K2: ... TC-006 (the word on the shared test, a pass of its own) reads the same, not `partial`",
             plan_state(odd, "TC-006")[0], f"not_executed:the run recorded {word} for this row's cases")
    check_eq("C-K2: ... and its detail names the case", plan_state(odd, "TC-005")[1], "TC-005")
    check_eq("C-K2: a word nobody knows reads alike", plan_state(with_status(shape_b(), MS, "weird-word"), "TC-005")[0],
             "not_executed:the run recorded weird-word for this row's cases")


def k2_edges() -> None:
    blocked = L.BLOCKED_STATE
    # control: no red, no row, no binding -> nothing changes, a green case is green
    plain = shape_b()
    plain["manifest"]["unresolved"] = []
    plain["report"] = {"current_results": [dict(r, status="passed") for r in plain["report"]["current_results"]]}
    check_eq("K2 control: empty E(C) -> passed_green, as before", [plan_state(plain, c)[0] for c in CASES], ["passed_green"] * 3)
    # a blocked row whose blocker is no longer red (the msteams test passed, the row stayed): read as it stands, never a pass
    stale_row = with_status(shape_a(), MS, "passed")
    stale_row["manifest"]["unresolved"] = []
    state, detail = plan_state(stale_row, "TC-005")
    check_eq("K2 edge: a blocked row whose blocker went green is still `not_executed:blocked_by_check`", state, blocked)
    check_in("K2 edge: ... and says what it waits for", "TC-005 Then 1: behind TC-004", detail)
    check_eq("K2 edge: ... the case with no such row is green", plan_state(stale_row, "TC-004")[0], "passed_green")
    # the new reason on a case with no run: blocked does not stand in for "no result"
    norun = shape_a()
    norun["report"] = {"current_results": []}
    check_in("K2 edge: no run at all -> `no result recorded`, not blocked", "no result recorded",
             plan_state(norun, "TC-005")[0])
    # the case's own runs are all gone but its Thens stand behind the red: blocked, not "no result recorded"
    own_gone = shape_b()
    own_gone["report"] = {"current_results": [r for r in own_gone["report"]["current_results"] if r["instance_id"] != G6]}
    check_eq("K2 edge: TC-006 has no run of its own left, its Thens are behind the red", plan_state(own_gone, "TC-006")[0], blocked)
    # blocked_by_check named by an INSTANCE id: the detail reads as the case(s) that instance is red for
    by_instance = shape_a()
    for b in by_instance["manifest"]["then_bindings"]:
        if b.get("reason") == "blocked_by_check":
            b["blocking_check"] = MS
    check_in("K2 edge: a blocker named by instance id reads as its case", "TC-005 Then 1: behind TC-004;",
             plan_state(by_instance, "TC-005")[1])
    check_not_in("K2 edge: ... and the instance id is not printed", MS, plan_state(by_instance, "TC-005")[1])
    nobody = shape_a()
    for b in nobody["manifest"]["then_bindings"]:
        if b.get("reason") == "blocked_by_check":
            b["blocking_check"] = G5
    check_in("K2 edge: an instance that is not red names no case -> `another check`", "behind another check;",
             plan_state(nobody, "TC-005")[1])


def _behind(story: dict, case: str) -> list:
    """`ledger._behind_words` of one case, built the way `plan_row_state` builds its inputs (for a case whose own run is
    not `passed` the plan row reads `failed`/`error` before this sentence is ever asked for, so only a direct call sees it)."""
    m, report = story["manifest"], story["report"]
    red_ = L.red_instances(m, report)
    blocked = L._blocked_rows(m)
    return L._behind_words(m, report, red_, L._shadowed(m, red_, blocked, [case]), blocked, [case])


def k2_other_thens_passed() -> None:
    """HF2-0 R2: `; its other Thens passed` is said only when the case's OWN run passed (the red instance left out)."""
    suffix = "; its other Thens passed"
    # (a) own run passed (shape A, the green generic test): the suffix is true and stays
    check_eq("K2 R2 (a): own run passed -> the suffix stays, per Then",
             _behind(shape_a(), "TC-005"), [f"TC-005 Then 1: behind TC-004{suffix}", f"TC-005 Then 2: behind TC-004{suffix}"])
    # (b) NO run of its own (the generic test has no row): nothing passed, the suffix is absent entirely
    norun = shape_a()
    norun["report"] = {"current_results": [r for r in norun["report"]["current_results"] if r["instance_id"] != G5]}
    state, detail = plan_state(norun, "TC-005")
    check_eq("K2 R2 (b): no own run -> still blocked", state, L.BLOCKED_STATE)
    check_eq("K2 R2 (b): no own run -> `<C> Then <n>: behind <R>`, no suffix", detail,
             "TC-005 Then 1: behind TC-004; TC-005 Then 2: behind TC-004")
    check_not_in("K2 R2 (b): ... the words `passed` are not there", "passed", detail)
    check_eq("K2 R2 (b): ... the neighbour whose own run passed keeps the suffix",
             plan_state(norun, "TC-006")[1], f"TC-006 Then 1: behind TC-004{suffix}; TC-006 Then 2: behind TC-004{suffix}")
    # (c) own run failed / errored: the suffix is omitted (the plan row reads the failure elsewhere)
    for status in ("failed", "error"):
        check_eq(f"K2 R2 (c): own run {status} -> no suffix", _behind(with_status(shape_a(), G5, status), "TC-005"),
                 ["TC-005 Then 1: behind TC-004", "TC-005 Then 2: behind TC-004"])
    # (d) the mixed form: Then 1 blocked, Then 2 covered on the red instance - the same predicate decides both sentences
    mixed = shape_a()
    mixed["manifest"]["then_bindings"] = [
        _covered("TC-005", 2, MS, _ms_ref("TC-005", 2, "default"))
        if (b["case"], b["then"], b.get("reason")) == ("TC-005", 2, "blocked_by_check") else b
        for b in mixed["manifest"]["then_bindings"]]
    stopped = "TC-005 Then 2: not proven - the test stopped at TC-004 Then 2"
    check_eq("K2 R2 (d): mixed form, own run passed -> the suffix beside `not proven` is true",
             plan_state(mixed, "TC-005")[1], f"TC-005 Then 1: behind TC-004{suffix}; {stopped}")
    nomix = copy.deepcopy(mixed)
    nomix["report"] = {"current_results": [r for r in nomix["report"]["current_results"] if r["instance_id"] != G5]}
    state, detail = plan_state(nomix, "TC-005")
    check_eq("K2 R2 (d): mixed form, no own run -> no suffix next to `not proven`", detail,
             f"TC-005 Then 1: behind TC-004; {stopped}")
    check_eq("K2 R2 (d): ... and the state is blocked, not `no result recorded`", state, L.BLOCKED_STATE)
    check_eq("K2 R2 (d): mixed form, own run failed -> no suffix", _behind(with_status(mixed, G5, "failed"), "TC-005"),
             ["TC-005 Then 1: behind TC-004", stopped])


def k1_whole_case_row() -> None:
    # FA-7 (A2): a `contradicts_requirement` row of ANY slice reads the run of its case
    whole = shape_b()
    whole["manifest"]["unresolved"] = [{"case": "TC-004", "reason": "contradicts_requirement", "detail": "not moved"}]
    check_eq("K1: a whole-case row + a failed run -> failed:*", plan_state(whole, "TC-004")[0], "failed:untriaged")
    no_run = copy.deepcopy(whole)
    no_run["report"] = {"current_results": [r for r in no_run["report"]["current_results"] if r["instance_id"] != MS]}
    check_eq("K1: ... without a run -> not_executed:contradicts_requirement", plan_state(no_run, "TC-004")[0],
             "not_executed:contradicts_requirement")
    # a slice row, the same
    check_eq("K1: a slice row (instance_ids) + a failed run -> failed:*", plan_state(shape_b(), "TC-004")[0], "failed:untriaged")
    # m11: TC-005's own row names ANOTHER instance (G5, no run); the red msteams test belongs to TC-004's row and is in E(TC-005)
    other = shape_b()
    other["manifest"]["unresolved"].append({"case": "TC-005", "reason": "contradicts_requirement", "instance_ids": [G5]})
    other["report"] = {"current_results": [r for r in other["report"]["current_results"] if r["instance_id"] != G5]}
    check_eq("K1 edge: its own row is about an instance nobody ran; the neighbour's red is not its failure",
             plan_state(other, "TC-005")[0], "not_executed:contradicts_requirement")


# --- 3c1: the delivery check on a task on disk -----------------------------------------------------------------------

PLAN_HEAD = """---
task: QA-1
created: 2026-10-24
rows_total: 3
candidates: 3
planned: 3
---

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
"""


def on_disk(story: dict, top: Path, detail: bool = True) -> Path:
    """A task directory for `story`: the `after-checks` fixture with its plan (TS-4..6, one case each), its three case files
    (a title each), the story's manifest and its run report. `detail=False` strips the author's words from the blocked rows."""
    task = top / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    plan = PLAN_HEAD + "".join(
        f"| TS-{c[-1]} | {c} holds | R-{c[-1]} | h | money | P1 | expected-contract | requirement:R-{c[-1]} | "
        f"`automate` - api | new | api | boundary-value analysis |\n" for c in CASES)
    (task / "test-plan.md").write_text(plan, encoding="utf-8")
    cases = task / "work" / "test-cases" / "checkout"
    for old in cases.glob("TC-*.md"):
        old.unlink()
    for case in CASES:
        (cases / f"{case}.md").write_text(
            f"---\nid: {case}\ntitle: The check {case} of the moved integration\narea: checkout\npriority: P1\nstatus: Approved\n"
            f"channel: auto\nreuse_decision: new\nupdated: 2026-10-24\ntask: QA-1\ncovers: [R-{case[-1]}]\n---\n\n"
            f"Requirements: R-{case[-1]}\nPlan row: TS-{case[-1]}\n\n## Steps\n\n| # | Action | Expected |\n|---|---|---|\n"
            f"| 1 | do it | the result of {case} is shown |\n", encoding="utf-8")
    manifest = copy.deepcopy(story["manifest"])
    for test in manifest["tests"]:
        test.update(critic_verdict="approved", case=test["covers"][0])
    if not detail:
        for b in manifest["then_bindings"]:
            if b.get("reason") == "blocked_by_check":
                b.pop("detail", None)
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = dict(story["report"], execution_status="failed", results=story["report"]["current_results"])
    (task / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
    (task / "work" / "triage.json").write_text(json.dumps({"schema_version": 2, "task_id": "QA-1", "triage": []}), encoding="utf-8")
    return task


def k7_delivery_on_disk() -> None:
    import check_delivery as D
    import delivery_verdict as DV
    top = temp_dir("qa-mixed-then-")
    try:
        doc = D.assess(on_disk(shape_a(), top / "a"))
        rows = {r["ref"]: r for r in doc["rows"] if r["kind"] == "plan_row"}
        check_eq("K7 A: ledger rows TS-4 / TS-5 / TS-6", [rows[t]["state"] for t in ("TS-4", "TS-5", "TS-6")],
                 ["failed:untriaged", L.BLOCKED_STATE, L.BLOCKED_STATE])
        check_eq("K7 A: the verdict is `no`", doc["delivery_verdict"], "no")
        check("K7 A: and TC-004 is what holds it", any("TC-004" in r for r in doc["reasons"]), str(doc["reasons"]))
        items = {i["ref"]: i for i in doc["left_items"] if i.get("counts")}
        for case in ("TC-005", "TC-006"):
            check("K7 A: " + f"{case} is left with the person as blocked_by_check", "blocked_by_check" in (items.get(case) or {}).get("kinds", []),
                  str(items.get(case)))
            check_eq(f"K7 A: {case} carries the author's words", items[case]["how"], f"check {case} Then 1 on msteams once TC-004 is fixed")
        doc = D.assess(on_disk(shape_b(), top / "b"))
        rows = {r["ref"]: r for r in doc["rows"] if r["kind"] == "plan_row"}
        check_eq("K7 B: ledger rows (variant (b))", [rows[t]["state"] for t in ("TS-4", "TS-5", "TS-6")],
                 ["failed:untriaged", L.BLOCKED_STATE, L.BLOCKED_STATE])
        check_eq("K7 B: the verdict is `no`", doc["delivery_verdict"], "no")
        items = {i["ref"]: i for i in doc["left_items"] if i.get("counts")}
        check_eq("K7 B: TC-005 and TC-006 are left with the person (from the ledger record, no blocked row exists)",
                 sorted(c for c in items if "blocked_by_check" in items[c]["kinds"]), ["TC-005", "TC-006"])
        # HF2-0 R1: shape B has no `blocked_by_check` row, and its line must not be empty (P21, FR-1): the covered Thens of the
        # case on the red instance are what the person checks, and the item carries the sibling default `how`
        for case in ("TC-005", "TC-006"):
            check_eq(f"K7 B R1: {case} to_check lists its covered Thens on the red instance", items[case]["to_check"],
                     "Then 1; Then 2")
            check_eq(f"K7 B R1: {case} how is the default words, the blocker named by its case and title", items[case]["how"],
                     "check after TC-004 (The check TC-004 of the moved integration) is fixed")
        # an item with a `how` from another record keeps it; a case with no covered Then on a red instance names itself
        task = on_disk(shape_b(), top / "b2")
        facts = D.gather(task)
        rec = {"text": "", "kind": "blocked_by_check", "case": "TC-005", "ref": "TC-005", "source": "ledger", "requirements": []}
        check_eq("K7 B R1: a `how` already on the item is kept", D.build_left_items([dict(rec, how="ask the owner")], facts)[0]["how"],
                 "ask the owner")
        check_eq("K7 B R1: the default is what the siblings of the block do (`not item['how']`)",
                 D.build_left_items([rec], facts)[0]["how"],
                 "check after TC-004 (The check TC-004 of the moved integration) is fixed")
        nothen = copy.deepcopy(shape_b())
        for b in nothen["manifest"]["then_bindings"]:
            if b["case"] == "TC-005" and b["instance_id"] == MS:
                b.pop("then")
        facts = D.gather(on_disk(nothen, top / "b3"))
        got = D.build_left_items([rec], facts)[0]
        check_eq("K7 B R1: covered bindings with no Then -> to_check names the case, never an empty string", got["to_check"], "TC-005")
        check_eq("K7 B R1: ... and `how` still gets the default", got["how"],
                 "check after the check this one depends on is fixed")
        # AR-27: the kind has an owner of the contract's list and the verdict word is a word, not `unknown`
        check_eq("K7: the kind of the state", DV.kind_of_state(L.BLOCKED_STATE, DV.load_kinds()[0]), "blocked_by_check")
        check_eq("K7: its verdict and owner", (DV.verdict_of_kind("blocked_by_check"), DV.owner_of_kind("blocked_by_check")),
                 ("after_checks", "product"))
        check("K7: the owner is one of the contract's", DV.owner_of_kind("blocked_by_check") in C.DELIVERY_REASON_OWNERS)
        check_eq("K7: word_of reads an after_checks ledger as a word", DV.word_of({"delivery_ready": False, "delivery_verdict": "after_checks"}),
                 "after_checks")
    finally:
        cleanup(top)


def k9_words() -> None:
    """3c1-K9 (D8, FR-6): the T3 words a person reads in "Left with you", through `human_text.problems`; no instance id."""
    import check_delivery as D
    import human_text
    top = temp_dir("qa-mixed-then-words-")
    try:
        task = on_disk(shape_a(), top, detail=False)
        records = D.blocked_records(task)
        check_eq("K9: one record per blocked Then (2 cases x 2 Thens)", sorted((r["case"], r["then"]) for r in records),
                 [("TC-005", 1), ("TC-005", 2), ("TC-006", 1), ("TC-006", 2)])
        want = "check after TC-004 (The check TC-004 of the moved integration) is fixed"
        check_eq("K9: T3 verbatim, the case with its title", {r["how"] for r in records}, {want})
        check_eq("K9: human_text names no broken rule in T3", human_text.problems(want, kind="report"), [])
        check_not_in("K9: no instance id in the words", MS, " ".join(r["how"] for r in records))
        # the blocker named by an instance id reads as the case that instance is red for; the author's `detail` stays verbatim
        shutil.rmtree(top / "QA-1")
        by_instance = shape_a()
        for b in by_instance["manifest"]["then_bindings"]:
            if b.get("reason") == "blocked_by_check":
                b["blocking_check"] = MS
        records = D.blocked_records(on_disk(by_instance, top, detail=False))
        check_eq("K9: an instance blocker reads as its case", {r["how"] for r in records}, {want})
        # a title that cannot be read; a blocker that is red for nothing
        (top / "QA-1" / "work" / "test-cases" / "checkout" / "TC-004.md").unlink()
        check_eq("K9: no case file for the blocker -> the words say what it is", {r["how"] for r in D.blocked_records(top / "QA-1")},
                 {"check after the check this one depends on (TC-004) is fixed"})
        nobody = shape_a()
        for b in nobody["manifest"]["then_bindings"]:
            if b.get("reason") == "blocked_by_check":
                b["blocking_check"] = G5
        shutil.rmtree(top / "QA-1")
        check_eq("K9: an instance that is red for no case -> no id, no case", {r["how"] for r in D.blocked_records(on_disk(nobody, top, detail=False))},
                 {"check after the check this one depends on is fixed"})
    finally:
        cleanup(top)


def main() -> None:
    the_fixtures()
    k6_shapes()
    k6b_every_row()
    k6c_report_source()
    k7_battery()
    k8_refusals()
    k9_direction()
    k2_ledger_states()
    k2_edges()
    k2_other_thens_passed()
    k1_whole_case_row()
    k7_delivery_on_disk()
    k9_words()
    finish("test_mixed_then_outcomes")


if __name__ == "__main__":
    main()
