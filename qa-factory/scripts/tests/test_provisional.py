#!/usr/bin/env python3
"""The registry of assumptions (t-2181 PC-3, spec §2.2): `provisional[]` and `tests[].provisional` in the automation manifest.

One writer (the automator, through `manifest_put.py --fragment`), one reader (`contract.manifest_provisional`). What is held:
a row merges by `id` and keeps the fields a fragment omits; `home_hash` is built by the tool from the line that carries the marker
`qa-provisional: P-n` wherever it is (a role-sent hash is dropped, a marker not found leaves no hash and is printed); the door
out is `retracted_provisional`; a test row's `provisional` list merges by instance like its other fields; an absent field reads
as `[]` and a malformed row is skipped and named, never raised.
"""
import hashlib
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

LOCATOR = '    SAVE_BUTTON = "#save-btn"  # qa-provisional: P-1'
HOME = "tests/locators.py"


def digest(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


def row(pid="P-1", **more) -> dict:
    return {"id": pid, "kind": "placeholder_locator", "what": "the save button", "status": "open",
            "home": {"file": HOME, "line_hint": 2}, **more}


def write_home(root: Path, lines: list) -> None:
    path = root / HOME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_by_id_keeps_what_a_fragment_omits() -> None:
    first, _ = MP.merge({}, {"provisional": [row(home_hash="h1", dependents=[{"case": "TC-1", "then": 1}]), row("P-2")]})
    second, summary = MP.merge(first, {"provisional": [{"id": "P-1", "status": "kept_by_decision", "evidence": {"reason": "x"}}]})
    one = second["provisional"][0]
    check_eq("a patch of a standing id changes its own fields", (one["status"], one["evidence"]), ("kept_by_decision", {"reason": "x"}))
    check_eq("and the fields it omits survive (kind, home, hash, dependents)",
             (one["kind"], one["home"]["file"], one["home_hash"], one["dependents"]),
             ("placeholder_locator", HOME, "h1", [{"case": "TC-1", "then": 1}]))
    check_eq("the other row is untouched and the order is kept", [r["id"] for r in second["provisional"]], ["P-1", "P-2"])
    check_eq("counted as one replacement", summary["replaced"], 1)
    empty, _ = MP.merge({"tests": []}, {"provisional": []})
    check_eq("an empty list SENT is the declared empty outcome", empty.get("provisional"), [])
    none, _ = MP.merge({}, {"tests": []})
    check("a fragment that sends none leaves the key absent (every side real)", "provisional" not in none, str(none))


def home_hash_is_the_hash_of_the_marked_line_wherever_it_is() -> None:
    root = harness.temp_project("qa-provisional-hash-")
    try:
        write_home(root, ["# locators", "import x", LOCATOR, "OTHER = 1"])
        want = digest(LOCATOR)
        for hint in (1, 2, 3, 99):
            stamped, said = MP.stamp_provisional({"provisional": [row(home={"file": HOME, "line_hint": hint})]}, root)
            check_eq(f"line_hint {hint}: the hash is the marked line's (the marker sits on line 3)",
                     (stamped["provisional"][0]["home_hash"], said), (want, []))
        write_home(root, ["# locators", "# a comment added above", "# and another", "import x", LOCATOR])
        moved, _ = MP.stamp_provisional({"provisional": [row()]}, root)
        check_eq("an edit above the line moves it and changes no hash", moved["provisional"][0]["home_hash"], want)
        write_home(root, ["import x", '    SAVE_BUTTON = "#other"  # qa-provisional: P-1'])
        edited, _ = MP.stamp_provisional({"provisional": [row()]}, root)
        check("an edit of the marked line itself is another hash", edited["provisional"][0]["home_hash"] != want)
        write_home(root, ["x = 1  # qa-provisional: P-12", LOCATOR])
        own, _ = MP.stamp_provisional({"provisional": [row()]}, root)
        check_eq("P-1 is never found on the line of P-12", own["provisional"][0]["home_hash"], want)
        original = {"provisional": [row(home_hash="typed")]}
        MP.stamp_provisional(original, root)
        check_eq("the fragment the caller passed is not edited", original["provisional"][0]["home_hash"], "typed")
    finally:
        harness.cleanup(root)


def the_marker_not_found_leaves_no_hash_and_says_so() -> None:
    root = harness.temp_project("qa-provisional-nomarker-")
    try:
        write_home(root, ["import x", "SAVE_BUTTON = '#save'"])
        for label, file in (("no marker on any line", HOME), ("the file is absent", "tests/nowhere.py"),
                            ("a path outside the project", "../outside.py")):
            stamped, said = MP.stamp_provisional({"provisional": [row(home={"file": file, "line_hint": 1}, home_hash="typed")]}, root)
            check_eq(f"{label}: the row keeps no hash", stamped["provisional"][0]["home_hash"], "")
            check(f"{label}: one sentence says so and names the marker", len(said) == 1 and "qa-provisional" in said[0], str(said))
        merged, _ = MP.merge({}, MP.stamp_provisional({"provisional": [row(home_hash="typed")]}, root)[0])
        check("and the stored row has none either", not merged["provisional"][0].get("home_hash"), str(merged))
    finally:
        harness.cleanup(root)


def through_the_door_a_role_sent_hash_is_ignored_and_a_status_patch_keeps_the_stored_one() -> None:
    with Stand() as stand:
        write_home(stand.root, ["import x", LOCATOR])
        code, out, err = stand.put({"provisional": [row(home_hash="typed-by-the-role")]})
        stored = stand.manifest()["provisional"][0]["home_hash"]
        check_eq("run: the stored hash is the tool's, not the role's", (code, stored), (0, digest(LOCATOR)))
        write_home(stand.root, ["import x", '    SAVE_BUTTON = "#edited"  # qa-provisional: P-1'])
        code, out, err = stand.put({"provisional": [{"id": "P-1", "status": "settled_edited", "home_hash": "typed-again"}]})
        after = stand.manifest()["provisional"][0]
        check_eq("run: a status patch with no home keeps the baseline, a hash it sends is dropped",
                 (code, after["home_hash"], after["status"]), (0, digest(LOCATOR), "settled_edited"))
        code, out, err = stand.put({"provisional": [row("P-2", home={"file": HOME, "line_hint": 1})]})
        check_eq("run: a row whose marker is not found is still committed, with no hash", (code, "P-2" in str(stand.manifest())), (0, True))
        check_in("run: and the put prints that no home_hash was recorded", "no home_hash was recorded", out)
        check_eq("run: and that row holds no hash", stand.manifest()["provisional"][1].get("home_hash"), "")


def through_the_door_a_settled_row_keeps_its_baseline() -> None:
    edited = '    SAVE_BUTTON = "#real"  # qa-provisional: P-1'
    with Stand() as stand:
        write_home(stand.root, ["import x", LOCATOR])
        stand.put({"provisional": [row()]})
        base = digest(LOCATOR)
        check_eq("1: the open row is baselined by the tool", stand.manifest()["provisional"][0]["home_hash"], base)
        write_home(stand.root, ["import x", edited])
        code, _o, _e = stand.put({"provisional": [row(status="settled_edited", home_hash="typed", evidence={"run": "R-1", "home_hash_after": "typed"})]})
        one = stand.manifest()["provisional"][0]
        check_eq("2: the bind round (full row, home, settled_edited) keeps the baseline", (code, one["home_hash"]), (0, base))
        check_eq("F4: the tool stamps home_hash_after from the line now and drops the typed one",
                 one["evidence"], {"run": "R-1", "home_hash_after": digest(edited)})
        stand.put({"provisional": [row(status="settled_edited", evidence={"run": "R-1"})]})
        check_eq("3: a re-sent full settled row still keeps the baseline", stand.manifest()["provisional"][0]["home_hash"], base)
    with Stand() as stand:
        write_home(stand.root, ["import x", LOCATOR])
        stand.put({"provisional": [row()]})
        write_home(stand.root, ["import x", edited])
        stand.put({"provisional": [row(status="kept_by_decision")]})
        stand.put({"provisional": [row()]})        # kept_by_decision -> open with home: the stored row is not open, so no re-stamp
        check_eq("4: kept_by_decision -> open with home keeps the baseline", stand.manifest()["provisional"][0]["home_hash"], base)
        check("F4: a row that is not settling carries no home_hash_after", "home_hash_after" not in
              (stand.manifest()["provisional"][0].get("evidence") or {}), str(stand.manifest()["provisional"][0]))
    with Stand() as stand:
        write_home(stand.root, ["import x", LOCATOR])
        stand.put({"provisional": [row()]})
        write_home(stand.root, ["import x", edited])
        stand.put({"provisional": [row()]})
        check_eq("5: control - an open row re-sent with home after an edit IS re-stamped",
                 stand.manifest()["provisional"][0]["home_hash"], digest(edited))
        stand.put({"provisional": [{"id": "P-1", "status": "settled_matched", "home": {"file": HOME, "line_hint": 2}}]})
        check_eq("6: the journal folds to the projected manifest", MP.fold(stand.store.read()), stand.manifest())


def a_malformed_provisional_fragment_is_refused() -> None:
    for label, bad in (("a list of strings", ["P-1"]), ("an object", {"id": "P-1"}), ("a lower-case id", [{"id": "p-2"}]),
                       ("a row with no id", [{"kind": "assumed_contract"}]), ("a repeated id", [row(), row()])):
        with Stand() as stand:
            before = stand.journal()
            code, _o, err = stand.put({"provisional": bad})
            check_eq(f"{label}: refused, the journal unchanged", (code, stand.journal()), (MP.EXIT_BAD_FRAGMENT, before))
            check_in(f"{label}: the refusal names `provisional`", "provisional", err)
    with Stand() as stand:
        code, _o, err = stand.put({"tests": [{"instance_id": "t[a]", "covers": ["TC-1"], "status": "green", "provisional": ["oops"]}]})
        check_eq("a bad tests[].provisional is refused", (code, "provisional" in err), (MP.EXIT_BAD_FRAGMENT, True))
        code, _o, err = stand.put({"retracted_provisional": "P-1"})
        check_eq("a non-list retraction is refused, not committed", (code, stand.journal()), (MP.EXIT_BAD_FRAGMENT, 0))


def the_retract_door() -> None:
    held, _ = MP.merge({}, {"provisional": [row(), row("P-2")]})
    gone, summary = MP.merge(held, {"retracted_provisional": ["P-1"]})
    check_eq("the row stays as history with the status `retracted`, its neighbour is untouched",
             [(r["id"], r["status"]) for r in gone["provisional"]], [("P-1", "retracted"), ("P-2", "open")])
    check_eq("the fields of the retracted row survive", gone["provisional"][0]["what"], "the save button")
    check("the key is not copied onto the manifest as a scalar", "retracted_provisional" not in gone, str(sorted(gone)))
    check_eq("counted once, and a second retraction of the same id changes nothing and is not an error",
             (summary.get("retracted_provisional"), MP.merge(gone, {"retracted_provisional": ["P-1"]})[0]["provisional"]),
             (1, gone["provisional"]))
    for label, fragment in (("an id that names no row", {"retracted_provisional": ["P-9"]}),
                            ("a value that is not a list", {"retracted_provisional": "P-1"})):
        check_in(f"{label} is a problem that names the key", "retracted_provisional",
                 " ".join(MP.provisional_row_problems(held, fragment)))
        check_eq(f"{label}: merge itself never raises (it replays)", MP.merge(held, fragment)[0]["provisional"], held["provisional"])
    check_eq("an id the same fragment brings may be retracted by it", MP.provisional_row_problems(held, {
        "provisional": [row("P-5")], "retracted_provisional": ["P-5"]}), [])
    with Stand() as stand:
        stand.put({"provisional": [row()]})
        code, _out, _err = stand.put({"retracted_provisional": ["P-1"]})
        check_eq("run: the door works on the stored manifest", (code, stand.manifest()["provisional"][0]["status"]), (0, "retracted"))
        code, _out, err = stand.put({"retracted_provisional": ["P-7"]})
        check_eq("run: a wrong id is refused before the commit", code, MP.EXIT_BAD_FRAGMENT)


def tests_provisional_merged_by_instance() -> None:
    base = {"tests": [{"instance_id": "test_save[a]", "covers": ["TC-1"], "status": "green"},
                      {"instance_id": "test_save[b]", "covers": ["TC-1"], "status": "green", "provisional": ["P-1"]}]}
    merged, _ = MP.merge(base, {"tests": [{"instance_id": "test_save[a]", "provisional": ["P-1", "P-2"]}]})
    by_id = {t["instance_id"]: t for t in merged["tests"]}
    check_eq("the instance named by the fragment takes its list, the other instance of the case keeps its own",
             (by_id["test_save[a]"]["provisional"], by_id["test_save[b]"]["provisional"]), (["P-1", "P-2"], ["P-1"]))
    check_eq("and the fields the patch omitted survive", (by_id["test_save[a]"]["covers"], by_id["test_save[a]"]["status"]),
             (["TC-1"], "green"))
    later, _ = MP.merge(merged, {"tests": [{"instance_id": "test_save[a]", "status": "red"}]})
    check_eq("a later patch without the field keeps the list", {t["instance_id"]: t.get("provisional") for t in later["tests"]},
             {"test_save[a]": ["P-1", "P-2"], "test_save[b]": ["P-1"]})
    read = C.manifest_provisional(later)
    check_eq("the reader maps each test to its P-n", read["by_test"], {"test_save[a]": ["P-1", "P-2"], "test_save[b]": ["P-1"]})


def absent_tests_provisional_reads_empty() -> None:
    old = {"tests": [{"instance_id": "test_old[x]", "covers": ["TC-1"], "status": "green"}], "unresolved": []}
    read = C.manifest_provisional(old)
    check_eq("a manifest written before the registry: no rows, the test reads []", (read["rows"], read["by_test"], read["skipped"]),
             ([], {"test_old[x]": []}, []))
    for label, value in (("None", None), ("a string", "x"), ("empty", {})):
        check_eq(f"a manifest that is {label} reads empty and never raises", C.manifest_provisional(value)["rows"], [])


def manifest_provisional_skips_a_malformed_row() -> None:
    manifest = {"provisional": [row(), "not a row", {"id": "p-2"}, {"kind": "assumed_contract"}, row("P-1", what="again"), row("P-3")],
                "tests": [{"instance_id": "t[a]", "provisional": ["P-1", "oops", 7]}, {"instance_id": "t[b]", "provisional": "P-1"},
                          {"instance_id": "t[c]", "provisional": ["P-3", "P-3"]}]}
    read = C.manifest_provisional(manifest)
    check_eq("the readable rows are returned, the first row of an id wins", [(r["id"], r["what"]) for r in read["rows"]],
             [("P-1", "the save button"), ("P-3", "the save button")])
    check_eq("each malformed thing is named, nothing is raised", len(read["skipped"]), 7)
    check_eq("a test keeps its readable ids, a test with a non-list field reads [], a repeated id is listed once",
             read["by_test"], {"t[a]": ["P-1"], "t[b]": [], "t[c]": ["P-3"]})
    check_eq("the reader of a non-list `provisional` says so", C.manifest_provisional({"provisional": {"id": "P-1"}})["skipped"],
             ["`provisional` is dict, not a list"])


def the_kinds_are_data_and_the_scaffold_follows_the_sides() -> None:
    kinds = json.loads((harness.PLUGIN_ROOT / "references" / "provisional-kinds.json").read_text(encoding="utf-8"))["kinds"]
    check_eq("the four kinds of the spec are rows of the data file", sorted(kinds),
             ["assumed_contract", "placeholder_locator", "reference_value", "side_substitute"])
    import manifest_from_tests as MFT
    with Stand() as stand:
        def story(sides=None):
            pipeline = {"ticket": "TP2-2406", "stages": {}, "gates": {}}
            if sides is not None:
                pipeline["sides"] = sides
            (stand.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            return MFT.Story("TP2-2406", stand.task)

        for label, sides, want in (("every side real (the default)", None, False),
                                   ("a side recorded real", {"product": {"reality": "real"}}, False),
                                   ("a side absent", {"product": {"reality": "real"}, "api": {"reality": "absent"}}, True),
                                   ("a side substituted", {"api": {"reality": "substituted"}}, True),
                                   ("a side whose reality cannot be read", {"api": {}}, True)):
            entry = {"instance_id": "t[a]", "status": "pending_run"}
            story(sides).scaffold_sides(entry, "t[a]")
            check_eq(f"{label}: `sides: {{}}` is {'scaffolded' if want else 'not on the row (byte-identical to today)'}",
                     entry, {"instance_id": "t[a]", "status": "pending_run", **({"sides": {}} if want else {})})
        stand.put({"tests": [{"instance_id": "t[a]", "covers": ["TC-1"], "status": "green", "sides": {"api": "absent"}}]})
        entry = {"instance_id": "t[a]"}
        story({"api": {"reality": "absent"}}).scaffold_sides(entry, "t[a]")
        check_eq("a row the manifest already holds with its declared sides is sent without `sides` (a `{}` would wipe them)",
                 entry, {"instance_id": "t[a]"})


def main() -> None:
    merge_by_id_keeps_what_a_fragment_omits()
    home_hash_is_the_hash_of_the_marked_line_wherever_it_is()
    the_marker_not_found_leaves_no_hash_and_says_so()
    through_the_door_a_role_sent_hash_is_ignored_and_a_status_patch_keeps_the_stored_one()
    through_the_door_a_settled_row_keeps_its_baseline()
    a_malformed_provisional_fragment_is_refused()
    the_retract_door()
    tests_provisional_merged_by_instance()
    absent_tests_provisional_reads_empty()
    manifest_provisional_skips_a_malformed_row()
    the_kinds_are_data_and_the_scaffold_follows_the_sides()
    finish("test_provisional")


if __name__ == "__main__":
    main()
