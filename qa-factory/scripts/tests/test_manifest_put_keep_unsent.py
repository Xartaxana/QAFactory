#!/usr/bin/env python3
"""`manifest_put` keeps what a fragment did not send (RN1-22, spec t-1699 node N2; LOCAL-1 run 3, 02-03.11.2026).

The incident: the role's hand fragment `S5-qa-automator-4-b.json` carried a `tests[]` row COPIED from the manifest, with its
`generated_from`. `manifest_put` read that as the writer's re-run, so `then_bindings` was replaced by the fragment's 3 rows
(TC_016) and 26 rows of the other windows were lost; `deviations` / `plan_remarks` of an earlier window went the same way. The
role re-sent the full lists as its workaround (`-4-c.json`, 29 rows). The fixtures are those real files, byte copies
(`fixtures/local1-manifest/SOURCE.md`).

Keys: K-N2-1a/b/c the writer's array replaces only what the writer wrote about; K-N2-2a/b a Then of a named unit the fragment
did not send stays, and only `retract: [then_bindings]` takes it out; K-N2-3a..d top-level lists accumulate (FK-6 a), a
`tests[]` patch of two keys keeps the rest; K-N2-4a..c a malformed `retract` is refused in `run` and ignored by `merge`.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract as C  # noqa: E402
import manifest_put as MP  # noqa: E402
from test_manifest_projection import Stand  # noqa: E402

FIX = harness.FIXTURES / "local1-manifest"
TC16, TC07, TC08, TC09, TC10 = ("LOCAL-1_TC_%03d" % n for n in (16, 7, 8, 9, 10))


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def rows_of(manifest: dict, case: str, instance=None) -> list:
    return [r for r in manifest["then_bindings"] if r["case"] == case and (instance is None or r["instance_id"] == instance)]


def words(rows) -> list:
    return sorted(MP._then_words(r) for r in rows)


def keys(rows) -> list:
    return sorted(MP._key(r) for r in rows)


def raises(fn, *args) -> bool:
    try:
        fn(*args)
    except Exception:
        return True
    return False


# --- N2-1: the writer's array replaces only the writer's units -----------------------------------------------------------

def k_n2_1a_the_copied_row_is_scoped() -> None:
    fb, fc = load("frag-4-b.json"), load("frag-4-c.json")
    kept = [r for r in fc["then_bindings"] if r["case"] != TC16]
    check_eq("K-N2-1a premise: frag-4-b is a writer fragment (a copied `generated_from`) and sends 3 rows: before RN1-22 the "
             "array became those 3", (MP._writer_tests(fb["tests"]), len(fb["then_bindings"]), len(kept)), (True, 3, 26))
    current = {"tests": [t for t in load("manifest-run3.json")["tests"]], "then_bindings": copy.deepcopy(kept)}
    merged, _ = MP.merge(copy.deepcopy(current), fb)
    check_eq("K-N2-1a: the 26 rows of the other windows stand and the 3 rows of the fragment join them: 29 rows",
             len(merged["then_bindings"]), 29)
    check_eq("K-N2-1a: ... the array is the one the role re-sent by hand (frag-4-c)", keys(merged["then_bindings"]), keys(fc["then_bindings"]))
    check_eq("K-N2-1a: ... the 26 stand where they stood, before the incoming rows",
             merged["then_bindings"][:26], kept)
    check_eq("K-N2-1a: ... and the print names nothing taken out", MP.removed_then_lines(current, fb), [])


def k_n2_1b_the_moved_instance() -> None:
    run3 = load("manifest-run3.json")
    x = next(t for t in run3["tests"] if t["case"] == TC07)
    moved = dict(x, case=TC08, covers=[TC08], marker=TC08, generated_from=["tests/api/cart/add-to-cart.spec.ts"])
    own_08 = rows_of(run3, TC08)
    new_row = {"case": TC08, "then": 4, "instance_id": x["instance_id"], "assertion_ref": "tests/api/cart/add-to-cart.spec.ts:1",
               "status": "covered"}
    fragment = {"tests": [moved], "then_bindings": own_08 + [new_row]}
    old_07 = rows_of(run3, TC07, x["instance_id"])
    check_eq("K-N2-1b premise: the manifest holds three TC_007 rows on X", len(old_07), 3)
    merged, _ = MP.merge(copy.deepcopy(run3), fragment)
    check_eq("K-N2-1b: the old TC_007 rows on X are gone", rows_of(merged, TC07, x["instance_id"]), [])
    check_eq("K-N2-1b: ... the print names them", sorted(MP.removed_then_lines(run3, fragment)), words(old_07))
    others = [r for r in run3["then_bindings"] if r["case"] not in (TC07, TC08)]
    check_eq("K-N2-1b: ... every row of a case the fragment did not write about stands as it was",
             [r for r in merged["then_bindings"] if r["case"] not in (TC07, TC08)], others)
    check_eq("K-N2-1b: ... and TC_008 is the array the fragment sent",
             keys(rows_of(merged, TC08)), keys(own_08 + [new_row]))
    hand = dict(fragment, tests=[{k: v for k, v in moved.items() if k != MP.WRITER_MARK}])
    merged, _ = MP.merge(copy.deepcopy(run3), hand)
    check_eq("K-N2-1b CONTROL: the same rows from a hand fragment (no `generated_from`) leave the TC_007 rows",
             len(rows_of(merged, TC07, x["instance_id"])), 3)


def k_n2_1b2_unresolved_cases_are_in_scope() -> None:
    run3 = load("manifest-run3.json")
    other = next(t for t in run3["tests"] if t["case"] == TC09)
    unresolved = [{"case": TC10, "reason": "impossible", "detail": "no channel"}]
    fragment = {"tests": [dict(other, generated_from=["tests/api/cart/add-to-cart.spec.ts"])], "unresolved": unresolved,
                "then_bindings": []}
    merged, _ = MP.merge(copy.deepcopy(run3), fragment)
    check_eq("K-N2-1b (c): a case the writer wrote an `unresolved[]` row for is in its scope: its old rows are replaced",
             (rows_of(merged, TC10), rows_of(merged, TC09, other["instance_id"])), ([], []))
    check_eq("K-N2-1b (c): ... any other case stands",
             [r for r in merged["then_bindings"] if r["case"] not in (TC10, TC09)],
             [r for r in run3["then_bindings"] if r["case"] not in (TC10, TC09)])
    check_eq("K-N2-1b (c): ... no writer mark, no scope: the same fragment as a hand one takes nothing",
             len(MP.merge(copy.deepcopy(run3), {"unresolved": unresolved, "then_bindings": []})[0]["then_bindings"]),
             len(run3["then_bindings"]))


def k_n2_1c_the_writer_over_itself() -> None:
    import hashlib
    import manifest_from_tests as MFT
    root = harness.temp_project("qa-n2-1c-")
    try:
        harness.use_project(root)
        config = root / "qa-factory" / "config.json"
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["case_id_form"] = "{ticket}_TC_{nnn}"
        config.write_text(json.dumps(cfg), encoding="utf-8")
        C.case_config_reset()
        task = root / "qa-factory" / "artifacts" / "LOCAL-1"
        (task / "work" / "test-cases").mkdir(parents=True)
        (task / "state").mkdir(parents=True)
        run3 = load("manifest-run3.json")
        cases = sorted({t["case"] for t in run3["tests"]})
        links = []
        for cid in cases:
            path = task / "work" / "test-cases" / f"{cid}.md"
            path.write_text(f"---\nid: {cid}\ntitle: {cid}\npriority: P1\nstatus: Draft\nchannel: auto\nupdated: 2026-11-03\n"
                            f"task: LOCAL-1\nplan_row: TS-1\n---\n\nRequirements: R-1\nPlan row: TS-1\n\n## Then\n1. a\n2. b\n3. c\n",
                            encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            links.append({"case_id": cid, "version": "cv_" + digest[:20], "content_hash": digest, "path": f"work/test-cases/{cid}.md"})
        (task / "state" / "story-case-links.json").write_text(
            json.dumps({"schema_version": 2, "task_id": "LOCAL-1", "links": links}), encoding="utf-8")
        (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S5-qa-automator-1": {
            "id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "status": "running", "scope": cases}}}), encoding="utf-8")
        (task / "work").mkdir(exist_ok=True)
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": [{"id": "TS-1", "disposition": "automate",
                                                                            "coverage_obligations": []}]}), encoding="utf-8")
        spec = root / "tests" / "api" / "cart" / "add-to-cart.spec.ts"
        spec.parent.mkdir(parents=True)
        spec.write_bytes((FIX / "add-to-cart.spec.ts").read_bytes())
        files = MFT._files(["tests/api/cart/add-to-cart.spec.ts"], root)
        fragment = MFT.build(MFT.Story("LOCAL-1", task), files, "S5-qa-automator-1", project=root)["fragment"]
    finally:
        harness.cleanup(root)
    check_eq("K-N2-1c premise: the writer's own fragment for add-to-cart.spec.ts is 11 rows, each with `generated_from`",
             (len(fragment.get("tests") or []), all(MP.WRITER_MARK in t for t in fragment["tests"])), (11, True))
    bindings = copy.deepcopy(run3["then_bindings"])
    current = {"tests": copy.deepcopy(run3["tests"]), "then_bindings": copy.deepcopy(bindings)}
    once, _ = MP.merge(copy.deepcopy(current), fragment)
    check_eq("K-N2-1c: the writer's fragment (it sends no Then: TS has no marker) leaves the array as it was",
             once["then_bindings"], bindings)
    twice, _ = MP.merge(copy.deepcopy(once), fragment)
    check_eq("K-N2-1c: ... merged over itself it changes nothing (tests[] and the array)",
             (twice["tests"], twice["then_bindings"]), (once["tests"], once["then_bindings"]))
    with_array = dict(fragment, then_bindings=copy.deepcopy(bindings))
    again, _ = MP.merge(copy.deepcopy(once), with_array)
    check_eq("K-N2-1c: ... and with the array it wrote about sent too, the array is identical, in order",
             again["then_bindings"], bindings)


# --- N2-2: a Then inside a named unit is erased only by `retract` ----------------------------------------------------------

def unit_story() -> tuple:
    run3 = load("manifest-run3.json")
    x = next(t for t in run3["tests"] if t["case"] == TC07)["instance_id"]
    unit = rows_of(run3, TC07, x)
    two = next(r for r in unit if r["then"] == 2)
    return run3, x, unit, dict(two, assertion_ref="tests/api/cart/add-to-cart.spec.ts:77")


def k_n2_2a_unsent_then_stays() -> None:
    run3, x, unit, two = unit_story()
    check_eq("K-N2-2a premise: the unit (TC_007, X) holds Thens 1, 2, 3", sorted(r["then"] for r in unit), [1, 2, 3])
    fragment = {"then_bindings": [two]}
    merged, _ = MP.merge(copy.deepcopy(run3), fragment)
    now = rows_of(merged, TC07, x)
    check_eq("K-N2-2a: Thens 1, 2, 3 stand, Then 2 replaced where it stood",
             ([r["then"] for r in now], two in now), ([r["then"] for r in unit], True))
    check_eq("K-N2-2a: ... nothing is printed as taken out", MP.removed_then_lines(run3, fragment), [])
    lines = MP.kept_then_lines(run3, fragment)
    check_eq("K-N2-2a: ... 'kept' lines are for Thens 1 and 3, with the door",
             (len(lines), sorted(l.split(" (")[0] for l in lines)),
             (2, sorted(f"kept {MP._then_words(r)}" for r in unit if r["then"] != 2)))
    check_in("K-N2-2a: ... and each says how to take it out", 'send "retract": ["then_bindings"] with the unit\'s full rows', lines[0])
    check_eq("K-N2-2a: ... the other units are untouched",
             [r for r in merged["then_bindings"] if not (r["case"] == TC07 and r["instance_id"] == x)],
             [r for r in run3["then_bindings"] if not (r["case"] == TC07 and r["instance_id"] == x)])
    with Stand() as stand:
        check_eq("K-N2-2a run: the manifest is seeded", stand.put({"then_bindings": run3["then_bindings"]})[0], 0)
        code, out, _err = stand.put(fragment)
        check_eq("K-N2-2a run: it commits", code, 0)
        printed = [l for l in out.splitlines() if l.startswith("kept ")]
        check_eq("K-N2-2a run: ... prints a 'kept' line for Then 1 and for Then 3", len(printed), 2)
        check_eq("K-N2-2a run: ... and the projection holds all three Thens",
                 sorted(r["then"] for r in rows_of(stand.manifest(), TC07, x)), [1, 2, 3])


def k_n2_2b_retract_takes_it_out() -> None:
    run3, x, unit, two = unit_story()
    fragment = {"then_bindings": [two], "retract": ["then_bindings"]}
    merged, _ = MP.merge(copy.deepcopy(run3), fragment)
    check_eq("K-N2-2b: with `retract` only Then 2 is left of the unit", rows_of(merged, TC07, x), [two])
    check_eq("K-N2-2b: ... the print names Thens 1 and 3, and no 'kept' line",
             (sorted(MP.removed_then_lines(run3, fragment)), MP.kept_then_lines(run3, fragment)),
             (words([r for r in unit if r["then"] != 2]), []))
    check_eq("K-N2-2b: ... the key is never stored", "retract" in merged, False)
    check_eq("K-N2-2b: ... the other units are untouched",
             [r for r in merged["then_bindings"] if not (r["case"] == TC07 and r["instance_id"] == x)],
             [r for r in run3["then_bindings"] if not (r["case"] == TC07 and r["instance_id"] == x)])
    empty, _ = MP.merge(copy.deepcopy(run3), {"then_bindings": [two], "retract": []})
    check_eq("K-N2-2b E9: `retract: []` is no sign: the unit keeps its three Thens", len(rows_of(empty, TC07, x)), 3)
    old_event = MP.fold([{"type": "manifest_seed", "sequence": 1, "idempotency_key": "s", "payload": {"manifest": run3}},
                         {"type": "manifest_patch", "sequence": 2, "idempotency_key": "k", "payload": {"fragment": {"then_bindings": [two]}}}])
    check_eq("K-N2-2b E12: an old journal that holds the hand fragment folds by the new rule (rows kept, nothing raised)",
             (len(rows_of(old_event, TC07, x)), "unprojected_events" in old_event), (3, False))
    check_eq("K-N2-2b E10: a retract of a key the fragment does not send changes nothing and `run` says so",
             (MP.merge(copy.deepcopy(run3), {"runs": [{"label": "w"}], "retract": ["then_bindings"]})[0]["then_bindings"],
              MP.retract_idle_lines({"runs": [], "retract": ["then_bindings", "deviations", "then_bindings"]})),
             (run3["then_bindings"],
              ["retract names then_bindings, which this fragment does not send: nothing changed",
               "retract names deviations, which this fragment does not send: nothing changed"]))
    with Stand() as stand:
        stand.put({"then_bindings": run3["then_bindings"]})
        code, out, _err = stand.put({"runs": [{"label": "w"}], "retract": ["deviations"]})
        check_in("K-N2-2b E10 run: the line is printed", "retract names deviations, which this fragment does not send: nothing changed", out)
        code, out, _err = stand.put(fragment)
        check_eq("K-N2-2b run: the retract send commits and prints the rows it took out",
                 (code, "then_bindings rows taken out by this send" in out, "kept " in out), (0, True, False))


# --- N2-3: top-level lists accumulate ----------------------------------------------------------------------------------------

def k_n2_3_lists_accumulate() -> None:
    fb, fc = load("frag-4-b.json"), load("frag-4-c.json")
    other = next(d for d in fc["deviations"] if "TC_001" in d["test"])
    merged, _ = MP.merge({"deviations": [other]}, {"deviations": fb["deviations"]})
    check_eq("K-N2-3a: frag-4-b's `deviations` over another window's row gives 2 rows", merged["deviations"], [other, fb["deviations"][0]])
    again, _ = MP.merge(copy.deepcopy(merged), {"deviations": fb["deviations"]})
    check_eq("K-N2-3a: ... the same row sent again is not added twice", again["deviations"], merged["deviations"])

    # t-1748 Q3: a `deviations` row has no `id`; its unit is `test`: a re-sent row with a corrected reason replaces the old one
    fixed = dict(fb["deviations"][0], reason="corrected reason")
    again, _ = MP.merge(copy.deepcopy(merged), {"deviations": [fixed]})
    check_eq("Q3: the same `test` re-sent with a new reason stands ALONE in place (2 rows, not 3)",
             (len(again["deviations"]), again["deviations"][1], sum(1 for d in again["deviations"] if d["test"] == fixed["test"])),
             (2, fixed, 1))
    check_eq("Q3 control: another list with no unit key still adds a different row (`probe` rows are not keyed by `test`)",
             len(MP._accumulate([{"test": "a", "x": 1}], [{"test": "a", "x": 2}])), 2)

    stored = copy.deepcopy(fc["plan_remarks"])
    pr1 = dict(next(r for r in fb["plan_remarks"] if r["id"] == "PR-1"), reason="reuses ShopActor.changeLine (revised in window 3)")
    check_eq("K-N2-3b premise: PR-1 stands first in the stored list, and its reason is not the re-sent one",
             stored[0]["id"] == "PR-1" and stored[0]["reason"] != pr1["reason"], True)
    merged, _ = MP.merge({"plan_remarks": stored}, {"plan_remarks": [pr1, fb["plan_remarks"][1]]})
    got = merged["plan_remarks"]
    check_eq("K-N2-3b: a re-sent PR-1 leaves ONE PR-1 row, in place, with the new reason",
             ([r["id"] for r in got].count("PR-1"), got[0]), (1, pr1))
    check_eq("K-N2-3b: ... no row was added or lost, and the rest stand", (len(got), got[1:2] == stored[1:2], len(stored)), (len(stored), True, len(stored)))

    merged, _ = MP.merge({"deviations": [other]}, {"deviations": fb["deviations"], "retract": ["deviations"]})
    check_eq("K-N2-3c: `retract: [deviations]` leaves the fragment's list only", merged["deviations"], fb["deviations"])
    merged, _ = MP.merge({"deviations": [other]}, {"deviations": fb["deviations"], "retract": []})
    check_eq("K-N2-3c E9: `retract: []` replaces nothing whole", len(merged["deviations"]), 2)
    check_eq("K-N2-3c: a first send (nothing stored) is the fragment's list whole", MP.merge({}, {"deviations": fb["deviations"]})[0]["deviations"],
             fb["deviations"])
    check_eq("K-N2-3 E13: a list over a scalar, and a scalar over a list: the fragment's value wins",
             (MP.merge({"probe": "x"}, {"probe": [1]})[0]["probe"], MP.merge({"probe": [1]}, {"probe": "x"})[0]["probe"],
              MP.merge({"probe": {"a": 1}}, {"probe": {"b": 2}})[0]["probe"]), ([1], "x", {"b": 2}))
    check_eq("K-N2-3: a row with no `id` that is not equal is added; an `id`-less equal one is not",
             (len(MP._accumulate([{"a": 1}], [{"a": 2}])), len(MP._accumulate([{"a": 1}], [{"a": 1}])), MP._accumulate([1], [1, 2])),
             (2, 1, [1, 2]))


def k_n2_3d_a_two_key_patch_keeps_the_rest() -> None:
    run3 = load("manifest-run3.json")
    first = run3["tests"][0]
    patch = {"instance_id": first["instance_id"], "status": "green"}
    merged, _ = MP.merge(copy.deepcopy(run3), {"tests": [patch]})
    row = next(t for t in merged["tests"] if t["instance_id"] == first["instance_id"])
    check_eq("K-N2-3d: the patch row is the only one that changed (11 tests stand)", len(merged["tests"]), len(run3["tests"]))
    for key in first:
        if key in patch:
            continue
        check_eq(f"K-N2-3d [{key}]: a patch of instance_id + status keeps the key", row.get(key), first[key])
    check_eq("K-N2-3d: ... and the status is the patch's", row["status"], "green")


# --- N2-4: `retract` refusals ------------------------------------------------------------------------------------------------

def k_n2_4_refusals() -> None:
    run3, _x, _unit, two = unit_story()
    cases = [("a", "then_bindings", "must be a list of top-level key names"),
             ("b", ["tests"], "retracted_instances"),
             ("c", [1], "is not a key name"),
             ("d", ["unresolved"], "retracted_unresolved"),
             ("e", ["obligation_bindings"], "retracted_obligations")]
    with Stand() as stand:
        stand.put({"then_bindings": run3["then_bindings"]})
        for label, retract, door in cases:
            fragment = {"then_bindings": [two], "retract": retract}
            before = (stand.journal(), stand.manifest())
            code, _out, err = stand.put(fragment)
            check_eq(f"K-N2-4{label} run: {retract!r} is refused before the commit", (code, (stand.journal(), stand.manifest())),
                     (MP.EXIT_BAD_FRAGMENT, before))
            check_in(f"K-N2-4{label} run: ... and the refusal says what to write instead", door, err)
            check(f"K-N2-4{label} merge: the same fragment raises nothing and stores no `retract`",
                  not raises(MP.merge, copy.deepcopy(run3), fragment) and "retract" not in MP.merge(copy.deepcopy(run3), fragment)[0])
        code, _out, err = stand.put({"then_bindings": [two], "retract": ["then_bindings", 7, "tests"]})
        check_eq("K-N2-4 run: two faults in one list are both named", (code, "retracted_instances" in err, "not a key name" in err),
                 (MP.EXIT_BAD_FRAGMENT, True, True))
    merged, _ = MP.merge(copy.deepcopy(run3), {"then_bindings": [two], "retract": "then_bindings"})
    check_eq("K-N2-4 merge: a bare string is no sign (the unit keeps its three Thens)", len(rows_of(merged, TC07)), 3)


def main() -> None:
    k_n2_1a_the_copied_row_is_scoped()
    k_n2_1b_the_moved_instance()
    k_n2_1b2_unresolved_cases_are_in_scope()
    k_n2_1c_the_writer_over_itself()
    k_n2_2a_unsent_then_stays()
    k_n2_2b_retract_takes_it_out()
    k_n2_3_lists_accumulate()
    k_n2_3d_a_two_key_patch_keeps_the_rest()
    k_n2_4_refusals()
    finish("test_manifest_put_keep_unsent")


if __name__ == "__main__":
    main()
