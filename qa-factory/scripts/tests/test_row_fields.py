#!/usr/bin/env python3
"""HF2-12a (EP1-18 (a), TP1-12586): the fields every `tests[]` row owes are known BEFORE the work.

On 12586 the automator learned `profile_id` from the critic and the window fields from the conductor: two extra
dispatches for a list the code already knew. `window_record.REQUIRED_ROW_FIELDS` is now that list (one carrier, AR-13),
`window_record.row_field_gaps` answers what a row still lacks, and `s5_precheck.check_row_fields` names every missing
(row, field) pair in ONE finding at the S5 exit.

Keys: K1 the carrier; K2 the predicate (the cases of spec section 3 as amended by section 12: whitespace is a value,
`obligation_refs` only where the plan owes one); K4 the finding (scope, one finding, no truncation, no word lifts it,
the config and the plan reach it through `run`). K3 (the window reads the carrier) lives in `test_window_record.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import execution_request as ER  # noqa: E402
import s5_precheck as P  # noqa: E402
import window_record as WR  # noqa: E402
import test_s5_precheck as TP  # noqa: E402  (its story builder and its printer: reused, not copied)

FIELDS = ("assertion_id", "defect_location", "change_disposition", "change_basis_ref", "obligation_refs", "profile_id")
TAG = "manifest:-:row-fields-missing"
FULL = {"instance_id": "t[a]", "file": "tests/test_validate.py", "assertion_id": "tests/test_validate.py:12",
        "defect_location": "src/validate.py:40", "change_disposition": "new_or_changed",
        "change_basis_ref": "manifest:TC-500"}
OWED = [{"obligation_id": "TS-1-O1", "decision": "new"}]


def profile(pid: str, test_root: str, **over) -> dict:
    return {"profile_id": pid, "roots": {"test": test_root}, **over}


SHARED = {"profiles": [profile("api", "tests"), profile("ui", "tests")]}


def without(row: dict, *names) -> dict:
    return {k: v for k, v in row.items() if k not in names}


def k1_the_carrier() -> None:
    carrier = WR.REQUIRED_ROW_FIELDS
    check_eq("K1: exactly the six fields, in this order", tuple(carrier), FIELDS)
    check_eq("K1: every entry is a RowField with the six attributes",
             {tuple(v._fields) for v in carrier.values()}, {("what", "when", "values", "filled_by", "origin_door", "window")})
    check_eq("K1: `when` per field", {k: v.when for k, v in carrier.items()},
             {"assertion_id": "always", "defect_location": "always", "change_disposition": "always",
              "change_basis_ref": "always", "obligation_refs": "plan_obligation", "profile_id": "shared_root"})
    check_eq("K1: `filled_by` - the marker writes `obligation_refs`, the automator the rest",
             {k: v.filled_by for k, v in carrier.items()},
             {k: ("marker" if k == "obligation_refs" else "automator") for k in FIELDS})
    check_eq("K1: `window` - the window copies five of them, not `profile_id`",
             {k: v.window for k, v in carrier.items()}, {k: k != "profile_id" for k in FIELDS})
    check_eq("K1: the only closed set is the disposition's", {k: v.values for k, v in carrier.items() if v.values},
             {"change_disposition": ("new_or_changed", "unchanged")})
    check("K1: every field says what it holds, and every door is a command the role has",
          all(v.what and v.origin_door for v in carrier.values()))
    check_in("K1: the marker field's door is the marker, not a fragment", "qa(obligations=",
             carrier["obligation_refs"].origin_door)
    check_in("K1: the other doors are the fragment road", "manifest_put.py --task <T> --fragment <file>",
             carrier["profile_id"].origin_door)


def k2_the_predicate() -> None:
    row = dict(FULL, obligation_refs=[{"obligation_id": "TS-1-O1", "obligation_hash": "h"}], profile_id="api")
    check_eq("K2 (a): a full row (profile, obligations, plan, config all given) -> []",
             WR.row_field_gaps(row, SHARED, OWED), [])
    check_eq("K2 (a): ...and with no config and no plan too", WR.row_field_gaps(FULL), [])
    check_eq("K2 (b): no `assertion_id` -> exactly that one", WR.row_field_gaps(without(FULL, "assertion_id")),
             [("assertion_id", "missing")])
    check_eq("K2 (b): the carrier's order is the answer's order",
             [f for f, _ in WR.row_field_gaps({"file": "x.py"})],
             ["assertion_id", "defect_location", "change_disposition", "change_basis_ref"])
    for value in (None, ""):
        check_eq(f"K2 (c): {value!r} is missing (a placeholder never reads as a value, FR-59)",
                 WR.row_field_gaps(dict(FULL, defect_location=value)), [("defect_location", "missing")])
    check_eq("K2 (c): a string of spaces is a VALUE: the window copies `str(x or '')` and keeps it, so does acceptance",
             WR.row_field_gaps(dict(FULL, assertion_id="  ", change_basis_ref="\t")), [])
    check_eq("K2 (c): `[]` / `{}` in a text field are not 'missing' here (only `obligation_refs` reads them so)",
             WR.row_field_gaps(dict(FULL, assertion_id=[], defect_location={})), [])
    check_eq("K2 (d): a value outside the closed set",
             WR.row_field_gaps(dict(FULL, change_disposition="changed")),
             [("change_disposition", "not one of new_or_changed, unchanged")])
    check_eq("K2 (d): `unchanged` is a value; the closed set is exact (a capital is not one)",
             [WR.row_field_gaps(dict(FULL, change_disposition=v)) for v in ("unchanged", "Unchanged")],
             [[], [("change_disposition", "not one of new_or_changed, unchanged")]])

    one = {"profiles": [profile("api", "tests"), profile("ui", "ui_tests")]}
    check_eq("K2 (d'): one profile owns the file -> `profile_id` is not demanded", WR.row_field_gaps(FULL, one), [])
    shared = WR.row_field_gaps(FULL, SHARED)
    check_eq("K2 (e): two profiles on one root and no profile named -> demanded, field `profile_id`",
             [f for f, _ in shared], ["profile_id"])
    check_in("K2 (e): ...the problem names the file and BOTH profiles",
             "its file tests/test_validate.py lies under the test root that profiles api, ui share", shared[0][1])
    check_eq("K2 (f): the old spelling `profile` is in place", WR.row_field_gaps(dict(FULL, profile="ui"), SHARED), [])
    check_eq("K2 (f): `profile_id` named -> in place", WR.row_field_gaps(dict(FULL, profile_id="ui"), SHARED), [])
    unknown = WR.row_field_gaps(dict(FULL, profile_id="zzz"), SHARED)
    check_eq("K2 (g): an unknown profile -> the text of `unknown_profile_refusal`, from the one reader",
             unknown, [("profile_id", ER.unknown_profile_refusal(SHARED, "zzz", ER.NAMED_BY_ROW))])

    # (h) inputs on the safe side (C3): never demand what the run does not refuse
    selected_out = {"profiles": [profile("api", "tests"), profile("ui", "tests", selected=False)]}
    safe = {
        "cfg None": None, "cfg {}": {}, "cfg a string": "profiles", "cfg a list": [SHARED],
        "no `profiles`": {"artifact_root": "x"}, "`profiles` a string": {"profiles": "api"},
        "profiles with no ids": {"profiles": [{"roots": {"test": "tests"}}, {"roots": {"test": "tests"}}]},
        "roots a string (would raise)": {"profiles": [{"profile_id": "a", "roots": "tests"},
                                                      {"profile_id": "b", "roots": "tests"}]},
        "second profile sits out (selected: false)": selected_out,
        "profiles on different roots": {"profiles": [profile("api", "tests"), profile("ui", "other")]},
    }
    for label, cfg in safe.items():
        check_eq(f"K2 (h): {label} -> `profile_id` not demanded", WR.row_field_gaps(FULL, cfg), [])
    check_eq("K2 (h): a file outside every root -> not demanded",
             WR.row_field_gaps(dict(FULL, file="elsewhere/test_x.py"), SHARED), [])
    check_eq("K2 (h): a row with no file -> not demanded", WR.row_field_gaps(without(FULL, "file"), SHARED), [])
    check_eq("K2 (h): `change_disposition: unchanged` is no gap", WR.row_field_gaps(dict(FULL, change_disposition="unchanged")), [])
    for file in ("Tests\\test_validate.py", "TESTS/test_validate.py", "./tests//test_validate.py"):
        check_eq(f"K2 (h): the path {file!r} is judged by the run's own key (`profiles_owning`), on this platform",
                 [f for f, _ in WR.row_field_gaps(dict(FULL, file=file), SHARED)],
                 ["profile_id"] if len(ER.profiles_owning(SHARED, file)) > 1 else [])

    # (i) a typo is named, not guessed at
    typo = WR.row_field_gaps(dict(without(FULL, "assertion_id"), assertionId="tests/t.py:1"))
    check_eq("K2 (i): `assertionId` -> missing, with the hint that names both spellings", typo,
             [("assertion_id", "missing (the row carries `assertionId`; the field is spelled `assertion_id`)")])
    check_eq("K2 (i): `Change-Disposition` is the same typo",
             WR.row_field_gaps(dict(without(FULL, "change_disposition"), **{"Change-Disposition": "unchanged"})),
             [("change_disposition", "missing (the row carries `Change-Disposition`; the field is spelled "
                                     "`change_disposition`)")])
    check_eq("K2 (i): a key that is no spelling of the field adds nothing",
             WR.row_field_gaps(dict(without(FULL, "assertion_id"), assertion="x")), [("assertion_id", "missing")])
    check_in("K2 (i): `profileId` on a row that owes a profile is hinted too", "the row carries `profileId`",
             WR.row_field_gaps(dict(FULL, profileId="api"), SHARED)[0][1])

    # (j) not a row
    for junk in ([], [FULL], None, "row", 5):
        check_eq(f"K2 (j): {type(junk).__name__} is not a row -> []", WR.row_field_gaps(junk, SHARED, OWED), [])

    # (m)-(p) obligation_refs: only where the plan owes an automated obligation, read as acceptance reads it
    bare = dict(FULL)
    check_eq("K2 (m): the plan owes an obligation and the row has no `obligation_refs` -> missing",
             WR.row_field_gaps(bare, None, OWED), [("obligation_refs", "missing")])
    check_eq("K2 (n): no plan, an empty plan (a legacy plan lists none), or a plan of `manual-*` only -> not demanded",
             [WR.row_field_gaps(bare, None, plan) for plan in (None, [], [{"obligation_id": "o", "decision": "manual-run"}],
                                                               [{"decision": "new"}], ["junk"])],
             [[], [], [], [], []])
    check_eq("K2 (n): one automated obligation beside a manual one still owes the field",
             WR.row_field_gaps(bare, None, [{"obligation_id": "m", "decision": "manual-run"}] + OWED),
             [("obligation_refs", "missing")])
    check_eq("K2 (o): a valid object beside junk is in place (non-dicts are skipped, as `build` skips them)",
             WR.row_field_gaps(dict(FULL, obligation_refs=[{"obligation_id": "o1"}, "junk"]), None, OWED), [])
    for label, refs in (("an empty id", [{"obligation_id": ""}]), ("an empty list", []), ("None", None),
                        ("a string", "o1"), ("junk only", ["junk", 3]), ("a dict", {"obligation_id": "o1"})):
        check_eq(f"K2 (p): {label} -> missing", WR.row_field_gaps(dict(FULL, obligation_refs=refs), None, OWED),
                 [("obligation_refs", "missing")])
    repeated = WR.row_field_gaps(dict(FULL, obligation_refs=[{"obligation_id": "o1"}, {"obligation_id": "o1"}]), None, OWED)
    check_eq("K2 (p): the same id twice is the acceptance's `obligation_binding` gap, said in its own words",
             [(f, "repeated" in p) for f, p in repeated], [("obligation_refs", True)])
    check_eq("K2 (p): ...and so is an empty id beside a good one",
             [f for f, _ in WR.row_field_gaps(dict(FULL, obligation_refs=[{"obligation_id": "o1"}, {}]), None, OWED)],
             ["obligation_refs"])
    everything = WR.row_field_gaps({"file": "tests/test_validate.py"}, SHARED, OWED)
    check_eq("K2: all six at once come in the carrier's order", [f for f, _ in everything], list(FIELDS))


# ---- K4: the finding -------------------------------------------------------------------------------------------

def row(i, case="TC-500", **over) -> dict:
    return {"instance_id": f"t{i}", "case": case, "covers": [case], "file": "tests/test_validate.py",
            "status": "green", **over}


def filled(i, case="TC-500", **over) -> dict:
    return row(i, case, **{k: v for k, v in FULL.items() if k not in ("instance_id", "file")}, **over)


def story(root: Path, rows: list, scope=("TC-500",), *, plan_obligations=None, unresolved=(), running=True) -> Path:
    manifest = {"tests": rows, "unresolved": list(unresolved)}
    task = TP.make_story(root, manifest)
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S5-qa-automator-1": {
        "id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "scope": list(scope),
        "status": "running" if running else "accepted"}}}), encoding="utf-8")
    if plan_obligations is not None:
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": [
            {"id": "TS-1", "schema_version": 2, "coverage_obligations": plan_obligations}]}), encoding="utf-8")
    return task


def scope_of(task: Path, *cases) -> None:
    (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S5-qa-automator-1": {
        "id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "scope": list(cases),
        "status": "running"}}}), encoding="utf-8")


def direct(task: Path, cases=("TC-500",), dispatch="S5-qa-automator-1", cfg=None, plan=None) -> tuple:
    manifest = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
    findings, notes = [], []
    P.check_row_fields(task, manifest, list(cases), findings, notes, dispatch, cfg=cfg, plan=plan)
    return findings, notes


def ours(result: dict) -> list:
    return [f for f in result["findings"] if f["id"] == TAG]


def k4_one_finding() -> None:
    root = temp_project("qa-rowfields-")
    use_project(root)
    try:
        # (a) three rows x two fields -> ONE finding, six pairs
        three = [row(i, change_disposition="unchanged", change_basis_ref="b") for i in (1, 2, 3)]
        task = story(root, three)
        found, notes = direct(task)
        check_eq("K4 (a): three rows missing two fields each -> ONE finding", [f["id"] for f in found], [TAG])
        message = found[0]["message"]
        check_in("K4 (a): the message counts rows and pairs", "3 tests[] row(s) of this window miss 6 field(s)", message)
        check_in("K4 (a): ...and lists each row with its fields, in the manifest's order",
                 "t1: assertion_id, defect_location (missing); t2: assertion_id, defect_location (missing); "
                 "t3: assertion_id, defect_location (missing)", message)
        check_eq("K4 (a): the family is `manifest` (outside PASSABLE) and the level a repair",
                 (found[0]["check"], found[0]["level"], "manifest" in P.PASSABLE), ("manifest", "repair", False))
        fix = found[0]["fix"]
        check_in("K4 (a): the fix names the form and the fragment road that works today, with the task",
                 "manifest_put.py --task QA-500 --fragment <file>", fix)
        check_in("K4 (a): ...the form `manifest_from_tests.py` prints", "`manifest_from_tests.py` prints", fix)
        check_in("K4 (a): ...the legend of the named fields", "`assertion_id`: " + WR.REQUIRED_ROW_FIELDS["assertion_id"].what, fix)
        check_not_in("K4 (a): ...and only of the named fields", "`change_disposition`:", fix)
        check_in("K4 (a): ...and says an empty field counts as missing", "present but empty counts as missing", fix)
        check_eq("K4 (a): no note when the scope is there", notes, [])

        # (b) everything in place -> no finding; (c) the real door fills it -> no finding on the repeat
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [filled(1), filled(2)]}),
                                                                encoding="utf-8")
        check_eq("K4 (b): every field in place -> no finding", direct(task), ([], []))
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [row(1), row(2)]}), encoding="utf-8")
        check_eq("K4 (c): before the fragment: one finding", len(direct(task)[0]), 1)
        fragment = {"tests": [{"instance_id": f"t{i}", "assertion_id": f"a:{i}", "defect_location": f"s:{i}",
                               "change_disposition": "new_or_changed", "change_basis_ref": "manifest:TC-500"}
                              for i in (1, 2)]}
        done = TP.put(root, "QA-500", fragment)
        check_eq("K4 (c): the fragment road the fix names is accepted by `manifest_put.py`", done.returncode, 0)
        check_eq("K4 (c): ...and the repeat finds nothing", direct(task), ([], []))

        # (d) a row outside the scope is not named
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": [row(1), row(2, case="TC-501")]}), encoding="utf-8")
        found, _ = direct(task, cases=("TC-500", "TC-501"))
        check_in("K4 (d): the row of the scoped case is named", "t1:", found[0]["message"])
        check_not_in("K4 (d): the row of a case outside the dispatch scope is not", "t2", found[0]["message"])
        check_eq("K4 (d): a manifest of one out-of-scope case gives nothing",
                 direct(task, cases=("TC-501",))[0], [])

        # (e) no scope: a note, no finding. dispatch None, an id the state does not know, a scope the state lacks
        for label, dispatch in (("no dispatch id", None), ("an unknown dispatch id", "S5-qa-automator-9")):
            found, notes = direct(task, dispatch=dispatch)
            check_eq(f"K4 (e): {label} -> no finding, one note", (found, notes),
                     ([], ["row fields not checked: no single dispatch scope"]))
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": []}), encoding="utf-8")
        check_eq("K4 (e): ...but a story with no test row has nothing unchecked: no note (its printed line stays as it was)",
                 direct(task, cases=(), dispatch=None), ([], []))
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": [row(1), row(2, case="TC-501")]}), encoding="utf-8")
        (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S5-qa-automator-1": {
            "id": "S5-qa-automator-1", "stage": "S5", "scope": []}}}), encoding="utf-8")
        check_eq("K4 (e): a dispatch with an empty scope is no scope either", direct(task)[1],
                 ["row fields not checked: no single dispatch scope"])
        (task / "state" / "controller.json").unlink()
        check_eq("K4 (e): no controller state at all -> the note, no raise", direct(task)[1],
                 ["row fields not checked: no single dispatch scope"])
    finally:
        cleanup(root)


def k4_many_and_few() -> None:
    root = temp_project("qa-rowfields-many-")
    use_project(root)
    try:
        rows = [row(i) for i in range(40)]
        task = story(root, rows)
        found, _ = direct(task, cfg=SHARED)
        check_eq("K4 (f): 40 rows x 5 fields -> ONE finding", [f["id"] for f in found], [TAG])
        message = found[0]["message"]
        check_in("K4 (f): ...with every pair (200), no truncation", "40 tests[] row(s) of this window miss 200 field(s)", message)
        check_eq("K4 (f): ...and every row named", [f"t{i}:" in message for i in range(40)], [True] * 40)
        check_not_in("K4 (f): ...with no ellipsis", "...", message.replace("tests[] row(s)", ""))
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": []}), encoding="utf-8")
        check_eq("K4 (g): 0 rows -> no finding", direct(task)[0], [])
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [row(1)]}), encoding="utf-8")
        check_eq("K4 (g): 1 row -> one finding", len(direct(task)[0]), 1)
        # a row proving two cases is named once
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": [row(1, covers=["TC-500", "TC-501"])]}), encoding="utf-8")
        check_in("K4: a row that proves two scoped cases is counted once", "1 tests[] row(s) of this window miss 4 field(s)",
                 direct(task, cases=("TC-500", "TC-501"))[0][0]["message"])
        # the plan: demanded only for a case whose plan row owes an automated obligation
        plan = [("TS-1", OWED[0])]
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": [filled(1, plan_row="TS-1"), filled(2, case="TC-501", plan_row="TS-9")]}),
            encoding="utf-8")
        scope_of(task, "TC-500", "TC-501")
        found, _ = direct(task, cases=("TC-500", "TC-501"), plan=plan)
        check_in("K4 (m): the plan row of the case owes an obligation -> `obligation_refs` is named, for that row only",
                 "t1: obligation_refs (missing)", found[0]["message"])
        check_not_in("K4 (m): ...a row of a case whose plan row is another one is not", "t2", found[0]["message"])
        fix = found[0]["fix"]
        check_in("K4 (m): the fix for a marker field names the marker, not a fragment", 'qa(obligations=["<plan obligation id>"])', fix)
        check_not_in("K4 (m): ...and offers no fragment for it", "--fragment", fix)
        check_eq("K4 (n): no plan given (a legacy plan lists none) -> not demanded", direct(task, plan=None)[0], [])
        check_eq("K4 (n): a `manual-*` obligation -> not demanded",
                 direct(task, plan=[("TS-1", {"obligation_id": "o", "decision": "manual-run"})])[0], [])
        scope_of(task, "TC-500")
        # a case handed to the person owes no binding (as check_obligations): not demanded
        (task / "work" / "automation-manifest.json").write_text(json.dumps({
            "tests": [filled(1, plan_row="TS-1")],
            "unresolved": [{"case": "TC-500", "reason": "handed_to_person", "detail": "the person runs it"}]}),
            encoding="utf-8")
        check_eq("K4 (n): a handed case owes no obligation_refs here", direct(task, plan=plan)[0], [])
        # both fields at once: the fix offers the fragment for the one and the marker for the other
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": [row(1, plan_row="TS-1")]}), encoding="utf-8")
        both = direct(task, plan=plan)[0][0]["fix"]
        check_eq("K4 (m): a row missing both kinds gets both doors", ("--fragment" in both, "qa(obligations=" in both),
                 (True, True))
    finally:
        cleanup(root)


def k4_through_run() -> None:
    """The finding as `run` produces it: with the project's config and the plan (m9: a call without `cfg` would miss
    the profile), before `passed_by_word` (m6), and printed as one line."""
    import waiver as W
    root = temp_project("qa-rowfields-run-")
    use_project(root)
    try:
        cfg_path = root / "qa-factory" / "config.json"
        base = json.loads(cfg_path.read_text(encoding="utf-8"))
        rows = [filled(1), filled(2, profile_id="ui")]
        task = story(root, rows)
        check_eq("K4 (r): no profiles in config.json -> `profile_id` is not demanded, the run is clean of our finding",
                 ours(P.run(task, "S5-qa-automator-1")), [])
        cfg_path.write_text(json.dumps(dict(base, profiles=SHARED["profiles"])), encoding="utf-8")
        result = P.run(task, "S5-qa-automator-1")
        found = ours(result)
        check_eq("K4 (r): two profiles on one root through `run()` -> the finding names `profile_id`, for the row that "
                 "names none", [len(found), "t1: profile_id (its file tests/test_validate.py lies under the test root that "
                 "profiles api, ui share)" in found[0]["message"] if found else None], [1, True])
        check_not_in("K4 (r): ...and not for the row that names `ui`", "t2", found[0]["message"] if found else "")
        check_eq("K4 (r): the test root of a story whose config cannot be read demands nothing",
                 ours(_run_with_config(root, task, "{not json")), [])

        # (s) a plan reaches the finding through run()
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": [
            {"id": "TS-1", "schema_version": 2, "coverage_obligations": OWED}]}), encoding="utf-8")
        (task / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": [filled(1, profile_id="api", plan_row="TS-1")]}), encoding="utf-8")
        found = ours(P.run(task, "S5-qa-automator-1"))
        check_in("K4 (s): the plan row of the case owes an obligation -> `obligation_refs` through `run()`",
                 "t1: obligation_refs (missing)", found[0]["message"] if found else "")

        # (h) no word lifts it: `*`, its own tag, the judge
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [row(1, profile_id="api")]}),
                                                                encoding="utf-8")
        for block in ("*", "row-fields", "row-fields-missing", "manifest"):
            pipeline = {"task": "QA-500"}
            W.apply_stage_override(pipeline, "S5", block, "the person lets it stand", W.now_iso())
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            check_eq(f"K4 (h): the recorded word {block!r} does not lift the finding",
                     len(ours(P.run(task, "S5-qa-automator-1"))), 1)
        (task / "pipeline.json").unlink()
        import judge
        kept = P.passed_by_judge(task, [P._finding("manifest", "", "m", "f", "row-fields-missing")], [], [], {}, {})
        check_eq("K4 (h): the judge (provider none) leaves it", [f["id"] for f in kept], [TAG])
        check_eq("K4 (h): ...and the tag is in neither list of what a word or a judge may pass",
                 (P.ROW_FIELDS_TAG in P.WORD_PASSABLE_TAGS, P.ROW_FIELDS_TAG in P.NEVER_JUDGED_TAGS, judge is not None),
                 (False, False, True))

        # (i) the report prints it as one line
        text = TP.printed(P.run(task, "S5-qa-automator-1"))
        lines = [line for line in text.splitlines() if line.startswith("- ") and "row-fields-missing" in line]
        check_eq("K4 (i): `report` prints the finding on ONE line, with its id in the label", len(lines), 1)
        check("K4 (i): ...which starts like every other finding line",
              lines[0].startswith("- [manifest " + TAG + "] 1 tests[] row(s)"), lines[0][:80])
        check_in("K4 (i): ...and no recorded word, `*` included, is offered for it",
                 "no recorded word, `*` included, passes any other finding", text)
        check_eq("K4 (i): the run is not ok", P.run(task, "S5-qa-automator-1")["ok"], False)
        # the order: the finding is raised before the per-case checks, so an early return of one of them cannot hide it
        check_eq("K4: an unscoped run (the exit gate with two running dispatches) raises nothing and says so",
                 ([f for f in P.run(task)["findings"] if f["id"] == TAG],
                  "row fields not checked: no single dispatch scope" in P.run(task)["notes"]), ([], True))
    finally:
        cleanup(root)


def _run_with_config(root: Path, task: Path, text: str) -> dict:
    path = root / "qa-factory" / "config.json"
    saved = path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    try:
        return P.run(task, "S5-qa-automator-1")
    finally:
        path.write_text(saved, encoding="utf-8")


def the_carrier_names_are_spelled_once() -> None:
    """Census (K5) as a test: the four window names stand in ONE tuple of the package's scripts that own them; the
    window, the pre-check and the marker read the carrier. `contract.WINDOW_INSTANCE_FIELDS` is the known exception:
    it is the item's whole shape, not the row's field list."""
    import re
    scripts = Path(__file__).resolve().parents[1]
    pattern = re.compile(r'"defect_location", "change_disposition"')
    hits = {name: len(pattern.findall((scripts / name).read_text(encoding="utf-8")))
            for name in ("window_record.py", "s5_precheck.py", "manifest_from_tests.py")}
    check_eq("K5: the four names are spelled once in window_record.py (the carrier) and nowhere else of the three",
             hits, {"window_record.py": 1, "s5_precheck.py": 0, "manifest_from_tests.py": 0})
    check_eq("K5 control: the same pattern finds the known exception in contract.py",
             len(pattern.findall((scripts / "contract.py").read_text(encoding="utf-8"))), 1)


def main() -> None:
    k1_the_carrier()
    k2_the_predicate()
    k4_one_finding()
    k4_many_and_few()
    k4_through_run()
    the_carrier_names_are_spelled_once()
    finish("row fields")


if __name__ == "__main__":
    main()
