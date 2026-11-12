#!/usr/bin/env python3
"""RD1-2 remainder (t-1698, D2-B): one case-key rule (`contract.case_matches`) and one red-row rule (`case_stamp.is_red_row`).

A manifest row, a ledger cell and a run result may spell one case three ways (`TC-002`, `web/TC-002`, `api/TC-002`); a raw
`in` or dict lookup read them as different cases and a story that had its test and its decision read "neither in
tests[] nor in unresolved[]" (the LOCAL-1 stand-gap cases; B-357). Every site below must join by identity, and the
identity must stay strict: two different areas are two cases, `TC-1` is not `TC-10`, two blanks are not one case.

Keys (spec t-1698 section 2.5): K-B1..K-B9 one per site, K-B10 the adversarial inputs, one check id each.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import GOOD, SCRIPTS, check, check_eq, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as D  # noqa: E402
import check_traceability as T  # noqa: E402
import contract as C  # noqa: E402
import factory_dashboard as FD  # noqa: E402
import ledger as L  # noqa: E402
import stand_gaps as SG  # noqa: E402
import test_delivery_ownership as TDO  # noqa: E402
import traceability as TR  # noqa: E402

TC_FORM = {"case_id_form": "TC_{nnn}"}      # LOCAL-1 writes `TC_022`, not the default `TC-NNN`


def run(*rows: dict) -> dict:
    """A run report whose current results are `rows` (each gets its own instance id so none collides)."""
    return {"current_results": [dict(r, instance_id=r.get("instance_id") or f"i{n}", test_id=r.get("test_id") or f"t{n}")
                                for n, r in enumerate(rows)]}


def chain(case: str, **kw) -> tuple:
    kw.setdefault("row", {"disposition": "automate"})
    kw.setdefault("manifest", {})
    kw.setdefault("report", {})
    return T._case_chain(case, **kw)


def k_b1_unresolved_link_by_identity() -> None:
    manifest = {"unresolved": [{"case": "TC-002", "reason": "blocked_by_env"}]}
    outcome, _detail, gap = chain("web/TC-002", manifest=manifest)
    check_eq("K-B1: link `TC-002`, case `web/TC-002` -> the unresolved branch fires", (outcome, gap),
             ("", "unresolved:blocked_by_env"))
    check_eq("K-B1: the bare case still reads it (compatibility)", chain("TC-002", manifest=manifest)[2],
             "unresolved:blocked_by_env")
    # the same site, the `tests[]` half of the chain: a test that links the bare id proves the area case
    tests = {"tests": [{"file": "t.py", "case": "TC-003"}]}
    check_eq("K-B1: a test linking `TC-003` is found for `web/TC-003` (no `not_in_manifest`)", chain("web/TC-003", manifest=tests)[2],
             "no_result")


def k_b2_run_results_lookup() -> None:
    passed = run({"case": "TC-002", "status": "passed"})
    check_eq("K-B2: `TC-002` passed, case `web/TC-002` -> executed_passed", chain("web/TC-002", report=passed)[0],
             "executed_passed")
    mixed = run({"case": "web/TC-2", "status": "failed"}, {"case": "TC-2", "status": "passed"})
    check_eq("K-B2: `web/TC-2` failed plus `TC-2` passed -> failed (exact key)", chain("web/TC-2", report=mixed)[0],
             "executed_failed")
    check_eq("K-B2: ... and the bare case rolls both up -> failed, a green alias never hides a red",
             chain("TC-2", report=mixed)[0], "executed_failed")
    results = C.run_results(mixed)
    check_eq("K-B2: case_lookup of `api/TC-2` reads the bare row's green, not the red of `web/TC-2` (D2-B3: no stored alias)",
             C.case_lookup(results, "api/TC-2"), "passed")
    check_eq("K-B2: the bare lookup rolls the matching keys up toward red (exact_wins=False)", C.case_lookup(results, "TC-2", exact_wins=False), "failed")
    check_eq("K-B2: an exact key wins over the roll-up", C.case_lookup({"web/TC-2": "passed", "TC-2": "failed"}, "web/TC-2"), "passed")
    check_eq("K-B2: no key names it -> None", C.case_lookup(results, "web/TC-9"), None)
    check_eq("K-B2: old caller without cfg (E-B5): the outcome is the same", T.outcome_for_case(
        "web/TC-002", {"disposition": "automate"}, {}, passed)[0], "executed_passed")


def k_b3_impossible_by_identity() -> None:
    report = {"impossible": [{"case": "TC-005", "reason": "no stand for it"}]}
    outcome, detail, _gap = chain("api/TC-005", report=report)
    check_eq("K-B3: an impossible row `TC-005` is the outcome of case `api/TC-005`", outcome, "impossible")
    check("K-B3: and its reason (not a rolled-up lowercased word) is the detail", detail.endswith("no stand for it"), detail)


def k_b4_handed_by_identity() -> None:
    handed = frozenset({"TC_022"})
    row = {"disposition": "manual-agent"}
    check_eq("K-B4: handed `TC_022` against `area/TC_022` -> unresolved:handed_to_person",
             chain("area/TC_022", row=row, handed=handed, cfg=TC_FORM)[2], "unresolved:handed_to_person")
    check_eq("K-B4: handed `area/TC_022` against the bare plan case",
             chain("TC_022", row=row, handed=frozenset({"area/TC_022"}), cfg=TC_FORM)[2], "unresolved:handed_to_person")
    check_eq("K-B4 control: a case nobody took by hand keeps its gap", chain("area/TC_023", row=row, handed=handed, cfg=TC_FORM)[2],
             "not_in_manifest")
    check_eq("K-B4 control: only a manual-agent row reads the hand-off", chain("area/TC_022", handed=handed, cfg=TC_FORM)[2],
             "not_in_manifest")


def story_with(tweak) -> Path:
    root = temp_project("qa-factory-case-key-")
    art = root / "qa-factory" / "artifacts" / "QA-1"
    shutil.copytree(GOOD, art)
    manifest_path = C.artifact(art, "automation-manifest.json")
    manifest = C.load_json(manifest_path)
    tweak(art, manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return root


def neither(art: Path, case: str) -> list:
    return [r for r in D.completeness_reasons(art) if "neither in" in r and f"case {case} " in r]


def k_b5_completeness() -> None:
    def to_unresolved(art, manifest):
        manifest["tests"] = [t for t in manifest.get("tests", []) if "TC-001" not in json.dumps(t)]
        manifest["unresolved"] = [{"case": "checkout/TC-001", "reason": "blocked_by_env"}]

    root = story_with(to_unresolved)
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        check_eq("K-B5: the unresolved row `checkout/TC-001` names the bare case `TC-001`", neither(art, "TC-001"), [])
    finally:
        cleanup(root)

    def two_areas(art, manifest):
        other = C.artifact(art, "test-cases") / "other"
        other.mkdir(parents=True, exist_ok=True)
        text = (C.artifact(art, "test-cases") / "checkout" / "TC-001.md").read_text(encoding="utf-8")
        (other / "TC-001.md").write_text(text.replace("checkout", "other"), encoding="utf-8")

    root = story_with(two_areas)
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        keys = sorted(C.case_index(art))
        check("K-B5 setup: two areas make area-qualified index keys", "checkout/TC-001" in keys and "other/TC-001" in keys, str(keys))
        check_eq("K-B5: the bare id the manifest links proves the area-qualified case `checkout/TC-001`",
                 neither(art, "checkout/TC-001"), [])
    finally:
        cleanup(root)

    def nothing(art, manifest):
        manifest["tests"] = [t for t in manifest.get("tests", []) if "TC-001" not in json.dumps(t)]
        manifest["unresolved"] = [{"case": "TC-002", "reason": "blocked_by_env"}]

    root = story_with(nothing)
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        check("K-B5 control: a case with neither a test nor a row is still named", len(neither(art, "TC-001")) == 1,
              str(D.completeness_reasons(art)))
    finally:
        cleanup(root)


def plan_state(case: str, rows: list) -> tuple:
    manifest = {"unresolved": rows}
    return L.plan_row_state({"ts": "TS-1", "disposition": "automate", "reason": ""}, manifest, {}, {}, {"TS-1": [case]})


def k_b6_ledger_unresolved_lookup() -> None:
    env = lambda case: {"case": case, "reason": "blocked_by_env"}      # noqa: E731
    state = plan_state("web/TC-002", [env("TC-002")])
    check("K-B6: B-357's bare record names the area case -> env_blocked", state[0].startswith("env_blocked"), str(state))
    three = plan_state("web/TC-002", [env("TC-002"), env("api/TC-002"), env("web/TC-002")])
    check("K-B6: the three records of B-357 (`TC-002`, `api/TC-002`, `web/TC-002`) -> env_blocked", three[0].startswith("env_blocked"), str(three))
    other = plan_state("web/TC-002", [env("api/TC-002")])
    check("K-B6 control: another area's record does not name it", not other[0].startswith("env_blocked"), str(other))
    # two rows, different reasons, one case: the branch reached first answers - the last row never wins silently
    both = [env("TC-002"), {"case": "web/TC-002", "reason": "pending_implementation"}]
    check_eq("K-B6: blocked_by_env then pending_implementation -> the earlier branch (pending_implementation)",
             plan_state("web/TC-002", both)[0], "pending_implementation")
    check_eq("K-B6: ... whatever the row order", plan_state("web/TC-002", list(reversed(both)))[0], "pending_implementation")
    check_eq("K-B6: one row nothing changes: an exact key still answers", plan_state("TC-002", [env("TC-002")])[0].split(":")[0],
             "env_blocked")


def k_b7_colliding_current_results() -> None:
    report = {"current_results": [{"test_id": "t_a", "case": "TC-001", "status": "failed"},
                                  {"test_id": "t_b", "case": "TC-001", "status": "passed"}]}
    current = C.current_instance_results(report)
    check_eq("K-B7: two `test_id`-only rows of one case are both present", len(current), 2)
    check_eq("K-B7: the first keeps its plain key (no non-colliding key changes)",
             [k for k, row in current.items() if row["test_id"] == "t_a"] and "|" not in
             [k for k, row in current.items() if row["test_id"] == "t_a"][0], True)
    check_eq("K-B7: the later row is re-keyed `<key>|<test_id>`", sorted(k.split("|", 1)[1] for k in current if "|" in k), ["t_b"])
    check_eq("K-B7: run_results rolls them up to failed (a red never lost behind a green)", C.run_results(report)["TC-001"], "failed")
    reversed_report = {"current_results": list(reversed(report["current_results"]))}
    check_eq("K-B7: ... whichever order they arrive in", C.run_results(reversed_report)["TC-001"], "failed")
    nameless = C.current_instance_results({"current_results": [{"case": "TC-001", "status": "failed"},
                                                               {"case": "TC-001", "status": "passed"},
                                                               {"case": "TC-001", "status": "passed"}]})
    check_eq("K-B7 (E-B4): rows with no test_id at all go to `key#n`, none lost", (len(nameless), sorted(k.rsplit("#", 1)[-1] for k in nameless if "#" in k)),
             (3, ["2", "3"]))
    same = C.current_instance_results({"current_results": [{"test_id": "t", "case": "TC-001", "status": "passed"}] * 3})
    check_eq("K-B7: the same test_id three times -> plain, `|t`, `#2`", len(same), 3)
    distinct = C.current_instance_results({"current_results": [{"instance_id": "x", "case": "TC-001", "status": "passed"},
                                                               {"instance_id": "y", "case": "TC-001", "status": "failed"}]})
    check_eq("K-B7 control: distinct instance ids keep their keys", sorted(distinct), ["x", "y"])


def k_b8_case_failed_by_red_row() -> None:
    root = temp_project("qa-factory-case-key-story-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        story = TR.Story(root, art)

        def failed(*rows) -> bool:
            story.report = run(*rows)
            story.results = C.current_instance_results(story.report)
            return story._case_failed("TC-001")

        check("K-B8: a `partial` row with a red raw_status is a red run of the case",
              failed({"case": "TC-001", "status": "partial", "raw_status": "failed"}))
        check("K-B8: ... through the case's area key too", failed({"case": "checkout/TC-001", "status": "partial", "raw_status": "error"}))
        check("K-B8 control: a `partial` with a green raw_status is not red", not failed({"case": "TC-001", "status": "partial", "raw_status": "passed"}))
        check("K-B8 control: a superseded row is history, not red",
              not failed({"case": "TC-001", "status": "partial", "raw_status": "failed", "superseded": True}))
        check("K-B8 control: another case's red row is not this case's",
              not failed({"case": "TC-010", "status": "partial", "raw_status": "failed"}))
        check("K-B8 control: a plain failed row still reads red (unchanged)", failed({"case": "TC-001", "status": "failed"}))
        check("K-B8 control: no row, not red", not failed())
    finally:
        cleanup(root)


def k_b9_dashboard_projection() -> None:
    manifest = {"tests": [{"file": "tests/t.py", "test_function": "test_a", "case": "TC-001", "status": "green"}]}

    def status(*runs, manifest=manifest) -> str:
        out = FD.story_projection({"manifest": manifest, "report": {"results": list(runs)}}, {}, {}, [], [])
        return out["rows"][0]["status"]

    base = {"test_id": "tests/t.py::test_a", "case": "TC-001"}
    check("K-B9: a partial row with manifest green is not `passed`", status(dict(base, status="partial", raw_status="passed")) != "passed")
    check_eq("K-B9: a partial row the run observed red is `failed`", status(dict(base, status="partial", raw_status="failed")), "failed")
    check_eq("K-B9: no run row, manifest green -> `not recorded`, never `passed`", status(), "not recorded")
    red = {"tests": [dict(manifest["tests"][0], status="red")]}
    check_eq("K-B9: the manifest's own `red` stays `failed`", status(manifest=red), "failed")
    check_eq("K-B9: a terminal run word is read as it stands", status(dict(base, status="passed")), "passed")


def k_b10_adversarial() -> None:
    check_eq("K-B10a: `web/TC-7` vs `api/TC-7` stay unmatched (lookup)", C.case_lookup({"api/TC-7": "failed"}, "web/TC-7"), None)
    check_eq("K-B10a: ... and in the chain", chain("web/TC-7", manifest={"unresolved": [{"case": "api/TC-7", "reason": "blocked_by_env"}]})[2],
             "not_in_manifest")
    check_eq("K-B10b: `TC-1` vs `TC-10` stay unmatched (lookup)", C.case_lookup({"TC-10": "failed"}, "TC-1"), None)
    check_eq("K-B10b: ... and in the chain", chain("TC-1", manifest={"unresolved": [{"case": "TC-10", "reason": "blocked_by_env"}]})[2],
             "not_in_manifest")
    check_eq("K-B10c: `PC-1@TC-10` vs `TC-1` stay unmatched", C.case_lookup({"PC-1@TC-10": "failed"}, "TC-1"), None)
    check_eq("K-B10c: ... and `TC-1` against a key that only ends in it", C.case_lookup({"XTC-1": "failed"}, "TC-1"), None)
    check_eq("K-B10d: two blank strings are not one case (lookup)", C.case_lookup({"": "failed"}, ""), None)
    check_eq("K-B10d: ... nor two whitespace strings", C.case_lookup({" ": "failed"}, " "), None)
    check_eq("K-B10d: ... and a blank case in the chain finds no unresolved row",
             chain("", manifest={"unresolved": [{"case": "", "reason": "blocked_by_env"}]})[2], "not_in_manifest")
    def only_other_area(art, manifest):
        other = C.artifact(art, "test-cases") / "other"
        other.mkdir(parents=True, exist_ok=True)
        text = (C.artifact(art, "test-cases") / "checkout" / "TC-001.md").read_text(encoding="utf-8")
        (other / "TC-001.md").write_text(text.replace("checkout", "other"), encoding="utf-8")
        for test in manifest.get("tests", []):
            if "TC-001" in json.dumps(test):
                test["case"] = "other/TC-001"
                test.pop("covers", None)

    root = story_with(only_other_area)
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        check_eq("K-B10a: ... and in _completeness: `checkout/TC-001` is not tested by the test of `other/TC-001`",
                 len(neither(art, "checkout/TC-001")), 1)
        check_eq("K-B10a: ... while `other/TC-001` is", neither(art, "other/TC-001"), [])
    finally:
        cleanup(root)
    check("K-B10d: ... nor in the ledger",not plan_state("", [{"case": "", "reason": "blocked_by_env"}])[0].startswith("env_blocked"))
    check_eq("K-B10e: no mapping at all -> None", C.case_lookup(None, "TC-1"), None)
    check_eq("K-B10f: a compound cell is split by case_ids: its parts match", C.case_lookup(C.run_results(run({"case": "TC-001/TC-002", "status": "failed"})),
                                                                                     "TC-002"), "failed")


def k_b_pin_automated_survives_a_later_red() -> None:
    """F-8 (b), B-310 (b): the stamp `Automated` a case got while its run was green is not taken away by a LATER red run - the
    stamp only ever writes. The case is simply not stamped again (and not left as ready) until the run is green. Pin only:
    `case_stamp` is edited only when this is red."""
    import test_case_stamp as TS      # the stamp's own helpers (its main() is guarded)
    import case_stamp as S
    root = temp_project("qa-factory-case-key-stamp-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-961"
        source = task / "work" / "test-cases" / "core" / "TC-961.md"
        TS.write_case(source, "TC-961", "QA-961")
        TS.pin_all(task, root)
        TS.write_json(task / "work" / "automation-manifest.json",
                      TS.manifest(TS.entry("TC-961", "test_a", probe=TS.GREEN_PROBE)))
        TS.run_green(task, "test_a")
        check_eq("F-8 b setup: a green run stamps the case", S.stamp(task)["stamped"], ["TC-961"])
        check_eq("F-8 b setup: its file says Automated", C.case_status(source), "Automated")
        TS.write_json(task / "work" / "run-report.json", {"current_results": [{"instance_id": "test_a", "status": "failed"}]})
        later = S.stamp(task)
        check_eq("F-8 b: a later red run does not take the stamp away", C.case_status(source), "Automated")
        check("F-8 b: ... and the red case is not reported stamped again", "TC-961" not in later["stamped"], str(later))
    finally:
        cleanup(root)


# --- K-B2-*: D2-B2, the places D2-B listed as analogs (an exact text membership where the rule is `case_matches`) ---------

def k_b2_1_world_gaps_by_identity() -> None:
    """check_delivery._fill_case_ownership `case in gaps`: a case the world blocks (`impossible`) is not the reducer's doubt,
    whichever way the two spell it. A miss lifts the case to `factory` - the forbidden direction."""
    cases = {"TC-117": (["R-117"], "TS-117")}
    current = [TDO.ghost("g117", "TC-117")]
    for label, spelled in (("area key against bare case", "lift/TC-117"), ("bare key", "TC-117")):
        with TDO.LiftStory(cases, current, report={"impossible": [{"case": spelled, "reason": "no such surface"}]}) as story:
            check_eq(f"K-B2-1: impossible row `{spelled}` ({label}): the case stays the product's, not lifted",
                     sorted(story.lift()["factory_cases"]), [])
    with TDO.LiftStory(cases, current) as story:
        check_eq("K-B2-1 positive control: no world gap -> the ghost-only case IS lifted", sorted(story.lift()["factory_cases"]),
                 ["TC-117"])
    # F3 (t-1753): the ONE predicate `contract.names_case` behind every "is this case among these keys" read
    check("F3 (E-B1): a blank case names nothing", not C.names_case({"TC-1", ""}, ""), "blank matched")
    check("F3 (E-B1): a blank key names nothing", not C.names_case(["", " "], "TC-1"), "blank key matched")
    check("F3 (E-B3): `web/TC-1` is not among `api/TC-1`", not C.names_case({"api/TC-1"}, "web/TC-1"), "areas matched")
    check("F3: `web/TC-1` is among `TC-1`", C.names_case({"TC-1"}, "web/TC-1"), "bare key missed")
    check("F3: and a bare case among `web/TC-1`", C.names_case(["web/TC-1"], "TC-1"), "area key missed by a bare case")
    check("F3: `TC-1` is not `TC-10`", not C.names_case({"TC-10"}, "TC-1"), "prefix matched")
    check("F3: the keys of a dict are read", C.names_case({"web/TC-1": 1}, "web/TC-1"), "dict keys missed")
    check("F3: no keys (None, empty) name nothing", not C.names_case(None, "TC-1") and not C.names_case([], "TC-1"), "empty matched")
    check("F3: project form `TC_{nnn}` (the story's cfg)", C.names_case({"TC_1"}, "web/TC_1", TC_FORM), "project form missed")
    # F6 (t-1753): `lifted_cases` compares the named cases to the factory's by the identity match, not by raw equality
    lift = {"factory_cases": {"web/TC-1": ["join_failed"]}, "plan_rows": {"TS-1": {"web/TC-1"}}, "requirements": {"R-1": {"web/TC-1"}},
            "cfg": {}}
    ctx = {"case_lift": lift}
    check_eq("F6: a bare `TC-1` reason against the factory case `web/TC-1` is lifted", D.lifted_cases("TC-1 is not proven", ctx), ["TC-1"])
    check_eq("F6: the plan row `TS-1` resolves to `web/TC-1`, which is the factory's", D.lifted_cases("TS-1 is not proven", ctx), ["web/TC-1"])
    check_eq("F6 control (E-B3): `api/TC-1` is another case: not lifted", D.lifted_cases("api/TC-1 is not proven", ctx), [])
    check_eq("F6 control: `TC-10` is not `TC-1`", D.lifted_cases("TC-10 is not proven", ctx), [])
    check_eq("F6: an id that resolves to nothing leaves the owner alone", D.lifted_cases("TS-9 and TC-1", ctx), [])
    check_eq("F6: one helper resolves ids for both readers (None = an unresolved id)",
             (D._named_cases("TS-1", lift, {}), D._named_cases("TS-9", lift, {}), D._named_cases("api/TC-2", lift, {}, with_areas=True)),
             (["web/TC-1"], None, ["api/TC-2"]))
    check("F6: case_defect_maps reuses the lift's maps when it holds them",
          D.case_defect_maps(Path("no-such-dir"), {}, lift) == {"plan_rows": lift["plan_rows"], "requirements": lift["requirements"]})


def sg_carries(gaps: list, accepted: set, cases: list, decided=None) -> list:
    """The `stand gap: <case>` keys `write_carries` tries to write (a failing `run` stops it right after the waiver call)."""
    calls = []

    def run(script, *args):
        calls.append(args)
        return 1, "stop"

    entries = [{"gap": g, "option": "accept", "line": "x"} for g in gaps if str(g["id"]) in accepted]
    SG.write_carries(Path("."), "T", gaps, entries, cases, decided or {}, set(), run, lambda text, name: Path("w.txt"),
                     say=lambda *_a, **_k: None)
    return [a[a.index("--block") + 1] for a in calls]


def k_b2_2_stand_gap_carry_by_identity() -> None:
    g1 = {"id": "PC-1", "case_id": "TC-1"}
    g2 = {"id": "PC-2", "case_id": "web/TC-1"}
    check_eq("K-B2-2: PC-1 accepted, PC-2 (same case, spelled `web/TC-1`) NOT accepted -> no carry for the case",
             sg_carries([g1, g2], {"PC-1"}, ["TC-1"]), [])
    check_eq("K-B2-2: both accepted -> the carry is written under each spelling gate B may read it by",
             sg_carries([g1, g2], {"PC-1", "PC-2"}, ["TC-1"]), ["stand gap: TC-1", "stand gap: web/TC-1"])
    other = {"id": "PC-2", "case_id": "api/TC-1"}
    check_eq("K-B2-2 (E-B3): PC-2 belongs to `api/TC-1`, PC-1 to `web/TC-1` -> two cases, the carry of the first stands",
             sg_carries([{"id": "PC-1", "case_id": "web/TC-1"}, other], {"PC-1"}, ["web/TC-1"]), ["stand gap: web/TC-1"])
    check_eq("K-B2-2 positive control: one gap, exact spelling -> the carry is written", sg_carries([g1], {"PC-1"}, ["TC-1"]),
             ["stand gap: TC-1"])


def k_b2_3_traceability_stricter_and_evidence() -> None:
    manifest = {"unresolved": [{"case": "TC-7", "reason": "contradicts_requirement"}]}
    failed = run({"case": "TC-7", "status": "failed"})
    for label, case, keys in (("area key in `stricter`, bare case", "TC-7", {"web/TC-7"}),
                              ("bare key in `stricter`, area case", "web/TC-7", {"TC-7"})):
        out = chain(case, manifest=manifest, report=failed, stricter=frozenset(keys))
        check_eq(f"K-B2-3: stricter by identity ({label}) -> executed_failed", out[0], "executed_failed")
    check_eq("K-B2-3 (E-B3): `stricter` names another area -> the gap stays", chain("web/TC-7", manifest=manifest, report=failed,
             stricter=frozenset({"api/TC-7"}))[2], "unresolved:contradicts_requirement")
    check_eq("K-B2-3 (E-B1): an empty key in `stricter` names nothing", chain("TC-7", manifest=manifest, report=failed,
             stricter=frozenset({""}))[2], "unresolved:contradicts_requirement")
    check_eq("K-B2-3 (project form `TC_{nnn}`): `web/TC_7` against `TC_7` in `stricter`", T._case_chain(
             "web/TC_7", {"disposition": "automate"}, {"unresolved": [{"case": "TC_7", "reason": "contradicts_requirement"}]},
             run({"case": "TC_7", "status": "failed"}), frozenset({"TC_7"}), cfg=TC_FORM)[0], "executed_failed")
    human = {"disposition": "manual-human"}
    out = chain("web/TC-8", row=human, report={"manual_human": [{"case": "TC-8", "evidence": "evidence/pack.md"}]})
    check_eq("K-B2-3: evidence recorded under `TC-8`, case `web/TC-8` -> evidence_for_human", out[0], "evidence_for_human")
    out = chain("TC-8", row=human, report={"manual_human": [{"case": "web/TC-8", "evidence": "evidence/pack.md"}]})
    check_eq("K-B2-3: evidence recorded under `web/TC-8`, bare case `TC-8` -> evidence_for_human", out[0], "evidence_for_human")
    check_eq("K-B2-3 (E-B3): evidence of `api/TC-8` is not the evidence of `web/TC-8`", chain("web/TC-8", row=human,
             report={"manual_human": [{"case": "api/TC-8", "evidence": "x"}]})[2], "manual_human_no_package")
    check_eq("K-B2-3 (empty evidence): a matching key with an empty package is no package", chain("web/TC-8", row=human,
             report={"manual_human": [{"case": "TC-8", "evidence": ""}]})[2], "manual_human_no_package")
    check_eq("K-B2-3 (several keys): the empty one and the full one -> the package counts", chain("web/TC-8", row=human,
             report={"manual_human": [{"case": "TC-8", "evidence": ""}, {"case": "web/TC-8", "evidence": "p.md"}]})[0],
             "evidence_for_human")


def plan_row(case_rows: list, manifest: dict, report: dict, row=None) -> tuple:
    return L.plan_row_state(row or {"ts": "TS-1", "disposition": "automate", "reason": ""}, manifest, report, {}, {"TS-1": case_rows})


def k_b2_4_ledger_plan_row_state() -> None:
    handed = {"unresolved": [{"case": "TC-2", "reason": C.HANDED_TO_PERSON}]}
    out = plan_row(["web/TC-2"], handed, run({"case": "TC-2", "status": "failed"}))
    check("K-B2-4: hand-off + a red run recorded under the bare key -> the red outranks the hand-off", out[0].startswith("failed:"), str(out))
    out = plan_row(["web/TC-2"], handed, run({"case": "TC-2", "status": "passed"}))
    check("K-B2-4 control: the same with a green run is not a failure", not out[0].startswith("failed:"), str(out))
    out = plan_row(["web/TC-3"], {}, {"impossible": [{"case": "TC-3", "reason": "no such surface"}]})
    check_eq("K-B2-4: impossible under the bare key, plan case `web/TC-3` -> impossible", out, ("impossible", "web/TC-3: no such surface"))
    out = plan_row(["TC-3"], {}, {"impossible": [{"case": "web/TC-3", "reason": "no such surface"}]})
    check_eq("K-B2-4: impossible under the area key, bare plan case -> impossible", out[0], "impossible")
    check("K-B2-4 (E-B3): impossible of `api/TC-3` is not the impossible of `web/TC-3`",
          plan_row(["web/TC-3"], {}, {"impossible": [{"case": "api/TC-3", "reason": "x"}]})[0] != "impossible")
    out = plan_row(["web/TC-4"], {}, run({"case": "TC-4", "status": "failed"}))
    check("K-B2-4: a red result under the bare key -> failed", out[0].startswith("failed:"), str(out))
    out = plan_row(["web/TC-4"], {}, run({"case": "TC-4", "status": "passed"}))
    check_eq("K-B2-4 control: green under the bare key -> passed_green", out[0], "passed_green")
    out = plan_row(["TC-4"], {}, run({"case": "web/TC-4", "status": "passed"}, {"case": "api/TC-4", "status": "failed"}))
    check("K-B2-4 (E-B2): two aliases, one red -> red wins", out[0].startswith("failed:"), str(out))
    out = plan_row(["web/TC-4"], {}, run({"case": "api/TC-4", "status": "failed"}, {"case": "db/TC-4", "status": "failed"}))
    check("K-B2-4 (E-B3, D2-B3): reds of `api/TC-4` and `db/TC-4` are not the result of plan case `web/TC-4`", not out[0].startswith("failed:"), str(out))


def k_b3_1_run_results_bare_alias() -> None:
    """D2-B3 (AR-13, AR-28): `run_results` adds the bare alias of an area row ONLY when exactly one area carries the id."""
    one = C.run_results(run({"case": "api/TC-4", "status": "failed"}))
    check_eq("K-B3-1 (one area): no stored bare key; the bare case still finds the area row through case_lookup",
             (one.get("TC-4"), one.get("api/TC-4"), C.case_lookup(one, "TC-4")), (None, "failed", "failed"))
    check_eq("K-B3-1 (one area, two rows): the area key rolls both rows up, red wins", C.run_results(run(
        {"case": "api/TC-4", "status": "passed"}, {"case": "api/TC-4", "status": "failed"})).get("api/TC-4"), "failed")
    two = C.run_results(run({"case": "api/TC-4", "status": "failed"}, {"case": "web/TC-4", "status": "passed"}))
    check("K-B3-1 (two areas): no bare alias", "TC-4" not in two, str(two))
    check_eq("K-B3-1 (two areas): both area keys keep their own word", (two.get("api/TC-4"), two.get("web/TC-4")), ("failed", "passed"))
    check_eq("K-B3-1 (two areas): the lookup of `web/TC-4` reads its own green, not the red of `api`", C.case_lookup(two, "web/TC-4"), "passed")
    check_eq("K-B3-1 (two areas): a third area finds no result (unknown, never a pass)", C.case_lookup(two, "db/TC-4"), None)
    check_eq("K-B3-1 (two areas): the bare lookup rolls the two area keys up, red wins", C.case_lookup(two, "TC-4"), "failed")
    only_red = C.run_results(run({"case": "api/TC-4", "status": "failed"}, {"case": "web/TC-5", "status": "passed"}))
    check_eq("K-B3-1 (two areas, two different ids): each id found through case_lookup", (C.case_lookup(only_red, "TC-4"), C.case_lookup(only_red, "TC-5")), ("failed", "passed"))
    both = C.run_results(run({"case": "TC-4", "status": "passed"}, {"case": "api/TC-4", "status": "failed"}, {"case": "web/TC-4", "status": "failed"}))
    check_eq("K-B3-1 (bare row + two areas): the bare row keeps its own key and word, no alias overwrites it", both.get("TC-4"), "passed")
    bare_one = C.run_results(run({"case": "TC-4", "status": "passed"}, {"case": "api/TC-4", "status": "failed"}))
    check_eq("K-B3-1 (bare row + one area): the bare key is the bare row's own; the judged lookup rolls up, red first",
             (bare_one.get("TC-4"), C.case_lookup(bare_one, "TC-4", exact_wins=False)), ("passed", "failed"))
    check_eq("K-B3-1 (bare row only): its own key, as today", C.run_results(run({"case": "TC-4", "status": "failed"})).get("TC-4"), "failed")
    check("K-B3-1 (empty id): no key", all(k for k in C.run_results(run({"case": "", "status": "failed"}))), "blank key")
    check_eq("K-B3-1 (project form `TC_{nnn}`): two areas, no alias", "TC_4" in C.run_results(run(
        {"case": "api/TC_4", "status": "failed"}, {"case": "web/TC_4", "status": "passed"}), cfg=TC_FORM), False)
    check_eq("K-B3-1 (project form, one area): no stored bare key, found through case_lookup", C.case_lookup(C.run_results(run(
        {"case": "api/TC_4", "status": "failed"}), cfg=TC_FORM), "TC_4", TC_FORM), "failed")
    # the chain's own lookup (D2-B `_case_chain`): the red of `api` is not the outcome of `web`
    two_rows = run({"case": "api/TC-4", "status": "failed"}, {"case": "web/TC-4", "status": "passed"})
    check_eq("K-B3-1 (_case_chain): `web/TC-4` reads its own green", chain("web/TC-4", report=two_rows)[0], "executed_passed")
    check("K-B3-1 (_case_chain): reds of `api/TC-4` and `db/TC-4` -> `web/TC-4` is not executed_failed", chain("web/TC-4", report=run(
        {"case": "api/TC-4", "status": "failed"}, {"case": "db/TC-4", "status": "failed"}))[0] != "executed_failed")
    # D2-B3 Q2: a bare green row beside red area rows -> red wins where results are judged (exact_wins=False); default unchanged
    mixed = run({"case": "TC-4", "status": "passed"}, {"case": "api/TC-4", "status": "failed"}, {"case": "web/TC-4", "status": "failed"})
    check_eq("K-B3-1 Q2 (_case_chain): bare green + two red areas, bare case -> executed_failed", chain("TC-4", report=mixed)[0], "executed_failed")
    check_eq("K-B3-1 Q2 (ledger): the same plan row reads failed", plan_row(["TC-4"], {}, mixed)[0].split(":")[0], "failed")
    check_eq("K-B3-1 Q2: `case_lookup` default still lets the exact key win", C.case_lookup(C.run_results(mixed), "TC-4"), "passed")
    check_eq("K-B3-1 Q2: `exact_wins=False` rolls up, red first", C.case_lookup(C.run_results(mixed), "TC-4", exact_wins=False), "failed")
    # OPEN (question to the Lead, report t-1698-d2b3): with ONE area the alias is added (the decision) and a bare key matches any
    # area, so `web/TC-4` still reads the red of a lone `api/TC-4`. Not pinned.


def k_b2_5_cases_for_row() -> None:
    manifest = {"tests": [{"file": "t.py", "case": "TC-5", "plan_row": "TS-1"}]}
    row = {"ts": "TS-1"}
    check_eq("K-B2-5: the manifest link `TC-5` is the plan case `web/TC-5`: no bare duplicate",
             L._cases_for_row(row, manifest, {"TS-1": ["web/TC-5"]}), ["web/TC-5"])
    check_eq("K-B2-5 control: another case is appended", L._cases_for_row(row, manifest, {"TS-1": ["web/TC-6"]}),
             ["web/TC-6", "TC-5"])
    check_eq("K-B2-5: nothing designed, the manifest names it -> the link is the case", L._cases_for_row(row, manifest, {}), ["TC-5"])
    check_eq("K-B2-5: the same link twice is one case", L._cases_for_row(row, {"tests": manifest["tests"] * 2}, {}), ["TC-5"])


def k_b3_2_readers_without_the_alias() -> None:
    """D2-B3 (Lead Q1 a): the bare alias of an area row is gone; the two readers that read a bare id raw go through `case_lookup`."""
    only = run({"case": "api/TC-4", "status": "failed"})
    check("K-B3-2: no bare key for an area row", "TC-4" not in C.run_results(only), str(C.run_results(only)))
    check_eq("K-B3-2: the bare case still finds its single area row (case_lookup)", C.case_lookup(C.run_results(only), "TC-4"), "failed")
    out = plan_row(["web/TC-4"], {}, only)
    check("K-B3-2 (the target case): a lone red `api/TC-4`, plan case `web/TC-4` -> not failed", not out[0].startswith("failed:"), str(out))
    check("K-B3-2 (the target case, chain): ... not executed_failed", chain("web/TC-4", report=only)[0] != "executed_failed")
    out = plan_row(["TC-4"], {}, only)
    check("K-B3-2 control: the bare plan case reads the red of its single area", out[0].startswith("failed:"), str(out))
    # `traceability.Story._case_failed`: a bare case matches its single area row; another area does not
    class _S(TR.Story):
        def __init__(self, report):
            self.report = report
            self.artifacts = Path("no-such-artifacts-dir")
            self.results = C.current_instance_results(report)
    check("K-B3-2 (_case_failed): bare `TC-4` against the red of `api/TC-4` -> True", _S(only)._case_failed("TC-4") is True)
    check("K-B3-2 (_case_failed): `web/TC-4` against the red of `api/TC-4` -> False", _S(only)._case_failed("web/TC-4") is False)
    check("K-B3-2 (_case_failed): `api/TC-4` against its own red -> True", _S(only)._case_failed("api/TC-4") is True)
    # F7 (t-1753): both paths of `_case_failed` read with the STORY's case config, not the process's: under `TC_{nnn}` the area
    # row `api/TC_5` is the case `TC_5`; the process form (`TC-NNN`) cannot read it
    tc5 = run({"case": "api/TC_5", "status": "failed"})
    check("F7 control: the process config does not read `TC_5` as a case id", not C.case_ids("TC_5", cfg={}), "process form reads TC_5")
    marker = Path("story-with-tc-form")
    real = C.case_config
    C.case_config = lambda artifacts=None: TC_FORM if artifacts == marker else real(artifacts)
    try:
        class _F(_S):
            def __init__(self, report):
                super().__init__(report)
                self.artifacts = marker
        check("F7 (_case_failed): story form `TC_{nnn}`: bare `TC_5` against the red of `api/TC_5` -> True", _F(tc5)._case_failed("TC_5") is True)
        check("F7 (_case_failed): `web/TC_5` against the red of `api/TC_5` -> False", _F(tc5)._case_failed("web/TC_5") is False)
    finally:
        C.case_config = real
    # F8 (t-1753): the `unresolved[]` rows of a case are found by the identity match, not the raw key
    class _U(_S):
        def __init__(self, rows):
            super().__init__({})
            self.unresolved_by_case = rows
    handed = {"case": "TC-4", "reason": C.HANDED_TO_PERSON}
    check_eq("F8: a bare row is the rows of `web/TC-4` (and the exact key's rows come first)",
             _U({"TC-4": [handed], "web/TC-4": [{"case": "web/TC-4", "reason": "x"}]}).unresolved_rows("web/TC-4")[0]["case"], "web/TC-4")
    check_eq("F8: the bare row is found for the area case", _U({"TC-4": [handed]}).unresolved_rows("web/TC-4"), [handed])
    check_eq("F8: the area row is found for the bare case", _U({"api/TC-4": [handed]}).unresolved_rows("TC-4"), [handed])
    check_eq("F8 (E-B3): another area's row is not this case's", _U({"api/TC-4": [handed]}).unresolved_rows("web/TC-4"), [])
    check_eq("F8: `TC-4` is not `TC-40`; a blank case has no rows", (_U({"TC-40": [handed]}).unresolved_rows("TC-4"),
             _U({"": [handed]}).unresolved_rows("")), ([], []))
    check_eq("F8: `_handed_row` reads it through the same lookup", _U({"api/TC-4": [handed]})._handed_row("TC-4"), handed)
    check("F8 (stand_gaps): a failed case named by another spelling stops the carry", SG.names_case({"cases": ["web/TC-1"]}, "TC-1"))
    # the validator: an area-keyed result accounts for the bare required id (no false "appears in no lane")
    from harness import install_artifacts, temp_project, use_project
    root = temp_project("qa-factory-b3-")
    try:
        use_project(root)
        import validate_artifacts as V
        art = install_artifacts(root, GOOD, "QA-1")
        path = art / "work" / "run-report.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        control = dict(data, results=[])
        path.write_text(json.dumps(control), encoding="utf-8")
        check("K-B3-2 (validator control): no results at all -> `appears in no lane`", any("appears in no lane" in e for e in V.collect_errors(path)))
        spelled = dict(data, results=[dict(r, case=f"api/{r['case']}") if isinstance(r, dict) and r.get("case") else r
                                      for r in data.get("results") or []])
        path.write_text(json.dumps(spelled), encoding="utf-8")
        errs = [e for e in V.collect_errors(path) if "appears in no lane" in e]
        check("K-B3-2 (validator): area-keyed results still account for the bare required ids", not errs, "\n".join(errs))
    finally:
        cleanup(root)


def t1772_traceability_case_by_identity() -> None:
    """t-1772 item 2: `Story.unbound_instances` reads the links of a manifest row through `names_case`, not a raw set meet."""
    story = object.__new__(TR.Story)
    story.manifest = {"tests": [{"instance_id": "i1", "case": "TC-5", "file": "t.py"}]}
    story.bindings = {}
    check_eq("t-1772: an area case finds the test linking its bare id", story.unbound_instances("web/TC-5"), ["i1"])
    check_eq("t-1772: `TC-5` is not `TC-50`", story.unbound_instances("TC-50"), [])


def main() -> None:
    k_b1_unresolved_link_by_identity()
    k_b2_run_results_lookup()
    k_b3_impossible_by_identity()
    k_b4_handed_by_identity()
    k_b5_completeness()
    k_b6_ledger_unresolved_lookup()
    k_b7_colliding_current_results()
    k_b8_case_failed_by_red_row()
    k_b9_dashboard_projection()
    k_b10_adversarial()
    k_b_pin_automated_survives_a_later_red()
    k_b2_1_world_gaps_by_identity()
    k_b2_2_stand_gap_carry_by_identity()
    k_b2_3_traceability_stricter_and_evidence()
    k_b3_1_run_results_bare_alias()
    k_b3_2_readers_without_the_alias()
    k_b2_4_ledger_plan_row_state()
    k_b2_5_cases_for_row()
    t1772_traceability_case_by_identity()
    finish("case_key_identity_join")


if __name__ == "__main__":
    main()
