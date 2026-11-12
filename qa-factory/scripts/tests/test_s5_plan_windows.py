#!/usr/bin/env python3
"""SC1-14 FJ-B: after the plan review the S5 windows are cut by the groups of the plan, a written window is its author's chain,
a case whose test reaches a written window grows it, and a fresh window that splits a test is refused (spec t-1314 sections 2-3).

The cut is `controller.pack_windows` / `Controller.s5_windows_for` (the groups are `s5_plan.case_groups`, built on `test_adjacency`);
the windows already written are `Controller._written_windows`; the gate is (11) `_window_split_problems`; the progress line counts
the cut's windows. Every key names the mutation it kills (spec t-1314 section 5, FJ-B: MJ1-MJ15, MJ21-MJ23, MJ33, MJ35, MJ36, MJ43-MJ46).
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, s5_plan_ready, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CT  # noqa: E402
import s5_plan as SP  # noqa: E402
import story_progress as PROG  # noqa: E402
import waiver as W  # noqa: E402
from event_store import atomic_json  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_controller_rework_scope import evidence  # noqa: E402
from test_s5_plan import put, s5_story  # noqa: E402
from test_s5_plan_check import test_row  # noqa: E402
from test_s5_plan_controller import probe, send  # noqa: E402

os.environ.pop("QA_FACTORY_RUN_MODE", None)      # a desktop process: the plan form is the default of an S5 with no record
AUTHOR, CRITIC = "qa-automator", "qa-code-critic"
ALIVE = lambda *_args: {"state": "alive", "evidence": ["its transcript was written 9s ago"]}  # noqa: E731
CASES6 = tuple(f"TC-{n}" for n in range(1, 7))


def old_cut(cases, is_ui, ui_cases=2, other_cases=4):
    """The cut by cases as it was before the plan cut existed (a copy of the old body, the control of `split_windows`)."""
    out = []
    for surface, size, chosen in (("other", max(1, int(other_cases)), [c for c in cases if not is_ui(c)]),
                                  ("ui", max(1, int(ui_cases)), [c for c in cases if is_ui(c)])):
        for start in range(0, len(chosen), size):
            out.append({"index": len(out) + 1, "surface": surface, "scope": chosen[start:start + size]})
    return out


def grp(cases, surface="other"):
    return {"cases": list(cases), "surface": surface}


def shape(windows):
    return [(w["surface"], w["scope"], w.get("over_cap", False), w.get("cap")) for w in windows]


# --- the pure cut ---------------------------------------------------------------------------------------------------------

def k1_pack():
    ui = {"TC-001", "TC-002", "TC-003", "TC-004", "TC-005"}
    cases = [f"TC-{n:03d}" for n in range(1, 11)]
    for caps in ((2, 4), (1, 1), (3, 8)):
        check_eq(f"split_windows is the old cut (caps {caps})", CT.split_windows(cases, lambda c: c in ui, *caps),
                 old_cut(cases, lambda c: c in ui, *caps))
    check_eq("split_windows is the old cut: an empty scope has no windows", CT.split_windows([], lambda c: True), [])
    check_eq("split_windows is the old cut: the keys of a window are index, surface, scope",
             sorted(CT.split_windows(["a"], lambda c: False)[0]), ["index", "scope", "surface"])

    at_cap = CT.pack_windows([grp(["a", "b", "c", "d"]), grp(["u", "v"], "ui")], 2, 4)
    check_eq("a group at the cap fits: one plain window each, no over_cap key",
             shape(at_cap), [("other", ["a", "b", "c", "d"], False, None), ("ui", ["u", "v"], False, None)])
    over = CT.pack_windows([grp(["a", "b", "c", "d", "e"]), grp(["f"])], 2, 4)
    check_eq("a group over the cap is one window of its own, over_cap", shape(over),
             [("other", ["a", "b", "c", "d", "e"], True, 4), ("other", ["f"], False, None)])
    check_eq("a group over the cap: the numbers run on", [w["index"] for w in over], [1, 2])
    check_eq("a UI group over the cap is kept whole too", shape(CT.pack_windows([grp(["u", "v", "w"], "ui")], 2, 4)),
             [("ui", ["u", "v", "w"], True, 2)])
    mixed = CT.pack_windows([grp(["u", "v"], "ui"), grp(["a"]), grp(["w"], "ui"), grp(["b"])], 2, 4)
    check_eq("non-UI windows come first, then UI", [(w["index"], w["surface"], w["scope"]) for w in mixed],
             [(1, "other", ["a", "b"]), (2, "ui", ["u", "v"]), (3, "ui", ["w"])])
    fit = CT.pack_windows([grp(["a", "b", "c"]), grp(["d", "e", "f"]), grp(["g"]), grp(["h", "i"])], 2, 4)
    check_eq("first fit: a small group fills an earlier window", [w["scope"] for w in fit],
             [["a", "b", "c", "g"], ["d", "e", "f"], ["h", "i"]])
    check_eq("first fit: an over-cap window takes nothing more",
             [w["scope"] for w in CT.pack_windows([grp(list("abcde")), grp(["f"])], 2, 4)], [list("abcde"), ["f"]])
    check_eq("pack_windows numbers from `start`", [w["index"] for w in CT.pack_windows([grp(["a"]), grp(["u"], "ui")], 2, 4, start=3)], [3, 4])


def k2_groups():
    plan = {"tests": [{"id": "T-1", "cases": ["TC-1", "TC-2"], "level": "api"}, {"id": "T-2", "cases": ["TC-2", "TC-3"], "level": "api"},
                      {"id": "T-4", "cases": ["TC-4"], "level": "e2e-ui"}, {"id": "T-5", "cases": ["TC-5"], "level": "weird"},
                      {"id": "T-6", "cases": ["TC-6", "TC-9"], "level": "api"}]}
    cases = ["TC-1", "TC-2", "TC-3", "TC-4", "TC-5", "TC-6", "TC-7", "TC-8"]
    is_ui = lambda case: case in ("TC-1", "TC-5", "TC-7")      # noqa: E731
    groups = SP.case_groups(plan, cases, is_ui)
    check_eq("the cases one test covers are one group, a chain of tests joins (T-1, T-2), in scope order",
             [g["cases"] for g in groups], [["TC-1", "TC-2", "TC-3"], ["TC-4"], ["TC-5"], ["TC-6"], ["TC-7"], ["TC-8"]])
    check_eq("a group names its tests", [g["tests"] for g in groups][:3], [["T-1", "T-2"], ["T-4"], ["T-5"]])
    surfaces = {g["cases"][0]: g["surface"] for g in groups}
    check_eq("a group's surface is its tests' level: an api group stays other although S3 calls TC-1 UI", surfaces["TC-1"], "other")
    check_eq("a group's surface is its tests' level: an e2e-ui test makes the group UI although S3 does not", surfaces["TC-4"], "ui")
    check_eq("unknown test level cuts as UI (the S3 row says UI)", surfaces["TC-5"], "ui")
    s3 = lambda level: {"case": None, "s3": {"level": level}}     # noqa: E731
    odd = {"cases": [dict(s3("api"), case="TC-A"), dict(s3(None), case="TC-B")],
           "tests": [{"id": "T-A", "cases": ["TC-A"], "level": "weird"}, {"id": "T-B", "cases": ["TC-B"], "level": ""}]}
    tri = lambda case: {"TC-A": False, "TC-B": None}[case]     # noqa: E731  (`Controller._is_ui_case`: False is a known non-UI level, None unknown)
    got = {g["cases"][0]: g["surface"] for g in SP.case_groups(odd, ["TC-A", "TC-B"], tri)}
    check_eq("unknown test level with a non-UI S3 row cuts as other", got["TC-A"], "other")
    check_eq("unknown test level and unknown S3 level cut as UI", got["TC-B"], "ui")
    stale = dict(odd, cases=[dict(s3("e2e-ui"), case="TC-A"), dict(s3("e2e-ui"), case="TC-B")])
    check_eq("the S3 level is read from `is_ui` alone: the plan row's own copy of it decides nothing (M3)",
             {g["cases"][0]: g["surface"] for g in SP.case_groups(stale, ["TC-A", "TC-B"], tri)}, got)
    check_eq("a case with no test is a window member by its S3 level: UI", surfaces["TC-7"], "ui")
    check_eq("a case with no test is a window member by its S3 level: not UI", surfaces["TC-8"], "other")
    check_eq("a test case outside the scope ties nothing and is not a group", [g["cases"] for g in groups if "TC-9" in g["cases"]], [])
    mixed = SP.case_groups({"tests": [{"id": "T-1", "cases": ["a", "b"], "level": "api"}, {"id": "T-2", "cases": ["b", "c"], "level": "e2e-ui"}]},
                           ["a", "b", "c"], lambda case: False)
    check_eq("a mixed group is UI", mixed[0]["surface"], "ui")
    check_eq("test_adjacency: the other cases of a test, every case has a key",
             SP.test_adjacency(plan, ["TC-1", "TC-2", "TC-4"]), {"TC-1": {"TC-2"}, "TC-2": {"TC-1"}, "TC-4": set()})
    for label, broken in (("a plan that is not a mapping", None), ("tests not a list", {"tests": "x"}),
                          ("rows that are not rows", {"tests": ["x", 3, None]}), ("cases not a list", {"tests": [{"id": "T", "cases": "ab"}]}),
                          ("cases of a wrong type", {"tests": [{"id": "T", "cases": [1, ["a"], {"a": 1}, "a", "b"]}]})):
        got = SP.test_adjacency(broken, ["a", "b"])
        check_eq(f"test_adjacency: {label} does not raise", sorted(got), ["a", "b"])
        check_eq(f"case_groups: {label} does not raise", [g["cases"] for g in SP.case_groups(broken, ["a", "b"], lambda c: False)][0][:1], ["a"])
    check_eq("test_neighbours of a case are the cases its tests share (without itself, wherever the test lists them)",
             SP.test_neighbours(plan, ["TC-2"]), {"TC-1", "TC-3"})
    check_eq("test_neighbours: a neighbour outside the scope still counts", SP.test_neighbours(plan, ["TC-6"]), {"TC-9"})
    check_eq("test_neighbours: the cases asked are not their own neighbours", SP.test_neighbours(plan, ["TC-1", "TC-2"]), {"TC-3"})
    check_eq("test_neighbours: nothing shared, nothing returned", SP.test_neighbours(plan, ["TC-4"]), set())


# --- the story: written windows, growth, the cut as stage-scope gives it ------------------------------------------------

def caps(root, ui=2, other=4):
    put(root, "qa-factory/config.json", json.dumps({"dispatch": {"ui_window_cases": ui, "api_window_cases": other}}))


def rec(identifier, scope, status="accepted", role=AUTHOR, **extra):
    return dict({"id": identifier, "stage": "S5", "role": role, "status": status, "scope": list(scope)}, **extra)


def st(*records):
    return {"dispatches": {r["id"]: r for r in records}}


def plan_of(*groups):
    return {"schema": 1, "tests": [{"id": f"T-{n}", "cases": list(g), "level": "api"} for n, g in enumerate(groups, 1)]}


def cut_of(c, plan, state, scope=CASES6):
    mapping = c._case_rows(c.state())[0]
    return c.s5_windows_for(plan, state, list(scope), mapping)


def k3_written(root):
    c = s5_story(root, cases=CASES6)
    caps(root, 2, 4)
    scope = list(CASES6)
    written = lambda *records: c._written_windows(st(*records), scope)      # noqa: E731
    one = written(rec("A1", ["TC-1", "TC-2"]), rec("K1", ["TC-1", "TC-2", "TC-3"], role=CRITIC))
    check_eq("a fresh critic does not make a window: only the author's record is a window", [(w["root"], w["scope"]) for w in one],
             [("A1", ["TC-1", "TC-2"])])
    check_eq("a fresh critic does not make a window: a critic alone makes none", written(rec("K1", ["TC-1"], role=CRITIC)), [])
    check_eq("the plan dispatch is not a window", written(rec("P", scope, request_binding={"purpose": CT.S5_PLAN})), [])
    retried = written(rec("A1", ["TC-1", "TC-2"], "superseded"), rec("A2", ["TC-1"], "running", parent_retry="A1"))
    check_eq("a retried window stays written: the chain holds the root's scope though only the retry lives",
             [(w["root"], w["members"], w["scope"]) for w in retried], [("A1", ["A1", "A2"], ["TC-1", "TC-2"])])
    check_eq("a relaunch and a rework are members too",
             [(w["root"], w["members"]) for w in written(rec("A1", ["TC-1"], "stale"), rec("A2", ["TC-1"], "returned_unaccepted", relaunch_of="A1"),
                                                           rec("A3", ["TC-1"], rework_of="A2"))], [("A1", ["A1", "A2", "A3"])])
    taken = written(rec("A2", ["TC-3"]), rec("R", ["TC-3", "TC-1"], rework_of="A2"), rec("A1", ["TC-1", "TC-2"]))
    check_eq("a rework that touches another window's cases does not take them (roots first, then the other members)",
             [(w["root"], w["scope"]) for w in taken], [("A2", ["TC-3"]), ("A1", ["TC-1", "TC-2"])])
    check_eq("a window's cases leave when they leave the scope, and an empty window is dropped",
             [(w["root"], w["scope"]) for w in c._written_windows(st(rec("A1", ["TC-1", "TC-9"]), rec("A2", ["TC-8"])), scope)],
             [("A1", ["TC-1"])])
    check_eq("a discounted window is cut again: no live member, no written window",
             written(rec("A1", ["TC-1", "TC-2"], "stale"), rec("A2", ["TC-3"], "superseded")), [])
    check_eq("a record that cannot be read is no window and raises nothing",
             c._written_windows({"dispatches": {"x": "junk", "y": {"stage": "S5", "role": AUTHOR, "status": "accepted", "scope": "TC-1"}}}, scope), [])
    check_eq("a state that is not a mapping has no written window", c._written_windows(None, scope), [])


def k4_cut(root):
    c = s5_story(root, cases=CASES6)
    caps(root, 2, 2)
    plan = plan_of(["TC-1", "TC-3"], ["TC-2"], ["TC-4", "TC-5", "TC-6"])
    windows, cut = cut_of(c, plan, st())
    check_eq("a group over the cap is one window of its own, over_cap (stage-scope shape)", shape(windows),
             [("other", ["TC-1", "TC-3"], False, None), ("other", ["TC-2"], False, None), ("other", ["TC-4", "TC-5", "TC-6"], True, 2)])
    check_eq("the cut says nothing grown", cut["grown"], [])
    shuffled = {"schema": 1, "tests": [dict(t, cases=list(reversed(t["cases"]))) for t in reversed(plan["tests"])]}
    check_eq("the same plan gives the same windows (tests shuffled)", cut_of(c, shuffled, st())[0], windows)
    no_plan, none = cut_of(c, None, st())
    check_eq("no plan, no written window: no cut, the old cut by cases", (none, no_plan),
             (None, old_cut(list(CASES6), lambda case: False, 2, 2)))
    check_eq("an empty scope: no windows, no cut", c.s5_windows_for(plan, st(), [], {}), ([], None))
    is_ui = c._is_ui_case(c._case_rows(c.state())[0])
    check_eq("the S3 level is tri-state: a case the plan has no row for is unknown, not 'not UI'", is_ui("TC-404"), None)
    check("the S3 level is tri-state: a case of the plan answers a bool or unknown", is_ui("TC-1") in (True, False, None), str(is_ui("TC-1")))
    check_eq("s5_windows_for with no scope reads the stage scope's own (one reader, M2)",
             c.s5_windows_for(plan, c.state())[0], cut_of(c, plan, c.state())[0])

    # a written window is never re-cut, whatever the cap or the plan now say
    state = st(rec("A1", ["TC-1", "TC-2", "TC-3"]))
    windows, cut = cut_of(c, plan_of(["TC-1"], ["TC-2"], ["TC-3"]), state)
    check_eq("a written window is never re-cut (it is above the cap and says so)", shape(windows)[0], ("other", ["TC-1", "TC-2", "TC-3"], True, 2))
    check_eq("a written window is never re-cut: the free cases are cut after it, numbered on", [(w["index"], w["scope"]) for w in windows[1:]],
             [(2, ["TC-4", "TC-5"]), (3, ["TC-6"])])
    check("a written window that was not grown has no `grown` key", "grown" not in windows[0] and cut["grown"] == [])

    # a case whose test reaches a written window grows it
    state = st(rec("A1", ["TC-1", "TC-2"]))
    caps(root, 2, 4)
    grown_plan = plan_of(["TC-1", "TC-2"], ["TC-2", "TC-3"], ["TC-4"])
    windows, cut = cut_of(c, grown_plan, state)
    check_eq("a new case whose test reaches a written window grows it", (windows[0]["scope"], windows[0].get("grown")),
             (["TC-1", "TC-2", "TC-3"], ["TC-3"]))
    check_eq("window_cut names the grown windows", cut["grown"], [1])
    check_eq("a grown window under the cap has no over_cap", (windows[0].get("over_cap"), windows[0].get("cap")), (None, None))
    caps(root, 2, 2)
    windows, _cut = cut_of(c, grown_plan, state)
    check_eq("a grown window over the cap says over_cap (cap 2, three cases)", (windows[0].get("over_cap"), windows[0].get("cap")), (True, 2))
    check_eq("a grown window: the rest is cut after it (cap 2)", [w["scope"] for w in windows[1:]], [["TC-4", "TC-5"], ["TC-6"]])
    caps(root, 2, 4)
    covered = state["dispatches"].copy()
    covered["R"] = rec("R", ["TC-1", "TC-2", "TC-3"], "running", rework_of="A1")
    windows, cut = cut_of(c, grown_plan, {"dispatches": covered})
    check_eq("grown clears once the author's rework covers W'", (windows[0]["scope"], windows[0].get("grown"), cut["grown"]),
             (["TC-1", "TC-2", "TC-3"], None, []))
    covered["R"]["status"] = "superseded"
    windows, cut = cut_of(c, grown_plan, {"dispatches": covered})
    check_eq("grown returns when that rework is discounted", (windows[0].get("grown"), cut["grown"]), (["TC-3"], [1]))
    windows, cut = cut_of(c, plan_of(["TC-1", "TC-2"], ["TC-3"], ["TC-4"]), state)
    check_eq("a new case of its own gets a new window", ([w["scope"] for w in windows], cut["grown"]),
             ([["TC-1", "TC-2"], ["TC-3", "TC-4", "TC-5", "TC-6"]], []))
    two = st(rec("A1", ["TC-1"]), rec("A2", ["TC-2"]))
    windows, cut = cut_of(c, plan_of(["TC-3", "TC-2"], ["TC-3", "TC-1"]), two)
    check_eq("a case tied to two written windows joins the earlier", ([w["scope"] for w in windows[:2]], cut["grown"]),
             ([["TC-1", "TC-3"], ["TC-2"]], [1]))
    windows, cut = cut_of(c, grown_plan, st(rec("A1", ["TC-1", "TC-2"], "stale")))
    check_eq("a discounted window is cut again from the plan", ([w["scope"] for w in windows], cut["grown"]),
             ([["TC-1", "TC-2", "TC-3", "TC-4"], ["TC-5", "TC-6"]], []))


# --- stage-scope on disk ---------------------------------------------------------------------------------------------------

def planned_story(root, cases, groups, ui=(), config=(2, 4)):
    """A story on the plan form with a reviewed plan whose tests are `groups` (one test per group), the review stamped on it."""
    c = s5_story(root, cases=cases, with_case_files=True, plan_extra={case: {"level": "e2e-ui"} for case in ui})
    caps(root, *config)
    s5_plan_ready(c, root, list(cases))
    set_tests(root, groups, ui)
    return c


def set_tests(root, groups, ui=()):
    plan = SP.load(root)
    rows = {row["case"]: row for row in plan["cases"]}
    plan["tests"] = [test_row(f"T-{n}", g, [f"{case}#{t['n']}" for case in g for t in rows[case]["thens"]],
                              level="e2e-ui" if any(case in ui for case in g) else "api") for n, g in enumerate(groups, 1)]
    atomic_json(root / SP.PLAN_REL, plan)
    SP.stamp_review(root, "S5-plan-critic-1")


def write_window(c, root, ident, scope, accept=True, role=AUTHOR, **extra):
    send(c, root, ident, role, scope=scope, **extra)
    if accept:
        c.apply("accept", {"id": ident, "status": "accepted", "stage_complete": False, "unresolved": True, "reason": "the repair round is open",
                           "evidence_refs": [evidence(root, ident + ".txt")], "idempotency_key": ident + "-ok"})


def k5_stage_scope(base):
    cases = CASES6[:4]
    root = base / "plain"
    root.mkdir()
    c = s5_story(root, cases=cases, with_case_files=True)
    caps(root, 2, 2)
    scope = c.stage_scope("S5")
    check("no plan, no written window: no window_cut key", "window_cut" not in scope, str(scope.get("window_cut")))
    check_eq("no plan: the old cut by cases", [w["scope"] for w in scope["windows"]], [["TC-1", "TC-2"], ["TC-3", "TC-4"]])
    put(root, SP.PLAN_REL, "{half a plan")
    scope = c.stage_scope("S5")
    check_eq("an unreadable plan cuts by cases and says why", ([w["scope"] for w in scope["windows"]], scope["window_cut"]["grown"]),
             ([["TC-1", "TC-2"], ["TC-3", "TC-4"]], []))
    check_in("an unreadable plan cuts by cases and says why: the reason", "cannot be read", scope["window_cut"]["why"])

    root = base / "planned"
    root.mkdir()
    c = planned_story(root, cases, [["TC-1", "TC-3"], ["TC-2"], ["TC-4"]], config=(2, 2))
    scope = c.stage_scope("S5")
    check_eq("planned: the windows follow the plan groups", [w["scope"] for w in scope["windows"]], [["TC-1", "TC-3"], ["TC-2", "TC-4"]])
    check("planned: a plan on disk gives the window_cut key", scope["window_cut"]["grown"] == [], str(scope["window_cut"]))
    check_eq("planned: the old keys of a window are still there", sorted(scope["windows"][0]), ["accepted_by", "index", "scope", "surface"])

    # legacy: the same plan file, a live window and no plan record -> the earlier form, plan ignored
    legacy_state = dict(c.state(), dispatches={"W": rec("W", ["TC-1"], "running")})
    legacy = c.stage_scope("S5", legacy_state)
    check_eq("legacy windows ignore the plan", ([w["scope"] for w in legacy["windows"]], "window_cut" in legacy),
             ([["TC-1", "TC-2"], ["TC-3", "TC-4"]], False))
    s6 = c.stage_scope("S6")
    check_eq("S6 windows unchanged (the plan's group is ignored, no window_cut)",
             ([(w["surface"], w["scope"]) for w in s6["windows"]], "window_cut" in s6),
             ([(w["surface"], w["scope"]) for w in old_cut(list(s6["scope"]), lambda case: False, 2, 2)], False))

    # a window is written, then the plan grows it
    write_window(c, root, "S5-qa-automator-1", ["TC-1", "TC-3"])
    write_window(c, root, "S5-qa-code-critic-1", ["TC-1", "TC-3"], role=CRITIC)
    critic_last = {"id": "k2", "stage": "S5", "role": CRITIC, "scope": ["TC-2", "TC-4"], "status": "accepted"}
    check_eq("the last window critic closes S5 on the plan cut: window 1 has both roles, window 2 is the critic's own",
             c._closes_stage(critic_last, c.state()), True)
    check_eq("the last window critic closes S5 on the plan cut: ... but not while window 1 lacks its critic",
             c._closes_stage(critic_last, dict(c.state(), dispatches={k: v for k, v in c.state()["dispatches"].items()
                                                                       if k != "S5-qa-code-critic-1"})), False)
    set_tests(root, [["TC-1", "TC-3", "TC-2"], ["TC-4"]])
    scope = c.stage_scope("S5")
    check_eq("window_cut names the grown windows (on disk)", (scope["window_cut"]["grown"], scope["windows"][0]["scope"], scope["windows"][0]["grown"]),
             ([1], ["TC-1", "TC-3", "TC-2"], ["TC-2"]))
    check_eq("a grown window keeps S5 open: its accepted dispatches do not cover W'", scope["windows"][0]["accepted_by"], {})
    check_eq("a grown window keeps S5 open: the last window's critic does not close it",
             c._closes_stage(dict(critic_last, scope=["TC-4"]), c.state()), False)

    # progress counts the plan windows, a grown window once
    answer = PROG.progress(root, now=time.time(), liveness=ALIVE)
    check_eq("progress counts the plan windows", (answer["position"]["windows_total"], answer["position"]["window"]), (2, 1))
    set_tests(root, [["TC-1", "TC-3", "TC-2"], ["TC-4"]])
    request = c.build_rework_request("S5", AUTHOR, ["TC-1", "TC-3", "TC-2"], "case TC-2 added", cause="ticket_changed")
    c.apply("dispatch", request)
    answer = PROG.progress(root, now=time.time(), liveness=ALIVE)
    check_eq("progress counts a grown window once", (answer["position"]["window"], answer["position"]["windows_total"]), (1, 2))
    after = c.stage_scope("S5")
    check_eq("progress counts a grown window once: the rework joined the window's chain, which is no longer grown",
             (after["windows"][0]["scope"], "grown" in after["windows"][0], after["window_cut"]["grown"]), (["TC-1", "TC-2", "TC-3"], False, []))


# --- the gate (11) ----------------------------------------------------------------------------------------------------------

def k6_gate(root):
    cases = ("TC-1", "TC-2", "TC-3")
    c = planned_story(root, cases, [["TC-1", "TC-2"], ["TC-3"]])
    fresh = lambda scope, **extra: probe(c, dict({"id": "S5-qa-automator-9", "stage": "S5", "role": AUTHOR, "scope": list(scope)}, **extra))   # noqa: E731
    text = fresh(["TC-1"])
    check_in("a window that splits a test is refused", "splits the cases of test(s) T-1 (TC-1, TC-2): a test is written in one window", text)
    check_in("a window that splits a test is refused: the door is stage-scope", "controller.py --operation stage-scope", text)
    check_in("a window that splits a test is refused: the word that passes it", "plan before windows", text)
    check_not_in("a scope of whole groups passes", "splits", fresh(["TC-1", "TC-2"]))
    check_not_in("a scope of whole groups passes: the other group", "splits", fresh(["TC-3"]))
    check_not_in("a scope of whole groups passes: all of them", "splits", fresh(list(cases)))
    check_not_in("a rework of a window is not refused for splitting a group", "splits", fresh(["TC-1"], rework_of="S5-qa-automator-1"))
    check_not_in("a retry of a window is not refused for splitting a group", "splits", fresh(["TC-1"], parent_retry="S5-qa-automator-1"))
    check_eq("a plan with no test asks nothing of the scope",
             c._window_split_problems({"scope": ["TC-1"]}, {"schema": 1, "cases": [], "tests": []}, c.state()), [])
    cut = c.stage_scope("S5")["windows"]
    check_eq("fixture: the cut hands out one window of the three cases", [w["scope"] for w in cut], [list(cases)])
    check_eq("a scope equal to a window of the cut always passes (the gate is tied to the one producer)",
             c._window_split_problems({"scope": list(cases)}, SP.load(root), c.state()), [])
    counted = []
    real = c._planned_cut
    c._planned_cut = lambda state: counted.append(1) or real(state)      # Q-a: the cut and the chains are read once per validate call
    fresh(["TC-1"])
    del c._planned_cut
    check_eq("(11) and (12) read the cut once per validate call", len(counted), 1)
    # B1: a plan row kept for a case that left the scope (T-2 lists TC-3 and TC-9) must not make (11) refuse the controller's own cut
    plan = SP.load(root)
    plan["cases"].append(dict(next(row for row in plan["cases"] if row["case"] == "TC-3"), case="TC-9"))
    plan["tests"][1]["cases"] = ["TC-3", "TC-9"]
    atomic_json(root / SP.PLAN_REL, plan)
    SP.stamp_review(root, "S5-plan-critic-1")
    check_eq("fixture: the stage scope and the cut do not hold TC-9", [w["scope"] for w in c.stage_scope("S5")["windows"]], [list(cases)])
    check_not_in("a row kept for a case that left the scope does not make (11) refuse the cut", "splits", fresh(list(cases)))
    check_in("a real split inside the scope still refuses", "splits the cases of test(s) T-1 (TC-1, TC-2)", fresh(["TC-1"]))
    pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
    W.apply_stage_override(pipeline, "S5", "plan before windows", "go on with this window", W.now_iso())
    put(root, "pipeline.json", json.dumps(pipeline))
    check_not_in("a person's word passes a split window", "splits", fresh(["TC-1"]))


def main():
    os.environ.pop("QA_FACTORY_RUN_MODE", None)
    k1_pack()
    k2_groups()
    base = temp_dir("qa-s5-fjb-")
    try:
        for name, call in (("written", k3_written), ("cut", k4_cut), ("gate", k6_gate)):
            root = base / name
            root.mkdir()
            call(root)
        k5_stage_scope(base)
    finally:
        cleanup(base)
    finish("test_s5_plan_windows")


if __name__ == "__main__":
    main()
