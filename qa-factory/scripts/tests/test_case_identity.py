#!/usr/bin/env python3
"""Case identity is `<area>/TC-NNN`: two areas numbered alike are two sets of cases.

TP2-2536 ran `speaker-detail/TC-001..008` beside `speakers/TC-001..012`. Everything
that keyed a case by the bare number read one of each pair as the other, and on recovery two
approved entries were gone (FB-2428-1). Everything here asks the same two questions of every
structure that carries a case: do both areas survive a merge and a recovery, and does a
record written by 0.7.x — which has no area at all — still read, merge and match?
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (check, check_eq, cleanup, finish, run_script,  # noqa: E402
                     temp_dir, temp_project)
import case_versions as V  # noqa: E402
import contract as C  # noqa: E402
import manifest_put as P  # noqa: E402
import manifest_view as W  # noqa: E402

AREAS = ("speakers", "speaker-detail")


def write_case(root: Path, area: str, number: int, body: str) -> Path:
    path = root / area / f"TC-{number:03d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: TC-{number:03d}\narea: {area}\nstatus: Draft\ntask: QA-1\n---\n"
        f"Requirements: R-1\nPlan row: TS-1\n# {body}\n", encoding="utf-8")
    return path


def spelling() -> None:
    check_eq("an area makes the key", C.case_key("TC-001", "speakers"), "speakers/TC-001")
    check_eq("no area leaves the number alone", C.case_key("TC-001"), "TC-001")
    check_eq("a key that already carries its area is not wrapped twice",
             C.case_key("speakers/TC-001", "speakers"), "speakers/TC-001")
    check_eq("and an argument never overrides the area a value declares",
             C.case_key("speakers/TC-001", "speaker-detail"), "speakers/TC-001")
    check_eq("the key splits back", C.split_case_key("speakers/TC-001"), ("speakers", "TC-001"))
    check_eq("a bare id splits to no area", C.split_case_key("TC-001"), ("", "TC-001"))
    check_eq("a compound cell is not read as an area",
             C.split_case_key("TC-001/TC-002"), ("", "TC-001/TC-002"))
    check_eq("nor is one turned into a key", C.case_key("TC-001/TC-002", "speakers"), "TC-001/TC-002")
    check("a bare id written by 0.7.x matches any area",
          C.case_matches("TC-001", "TC-001", "speakers"))
    check("and an area-less reader still finds an area's record",
          C.case_matches("speakers/TC-001", "TC-001"))
    check("two areas are two cases", not C.case_matches("speakers/TC-001", "TC-001", "speaker-detail"))
    check("a different number never matches", not C.case_matches("speakers/TC-001", "TC-002", "speakers"))


def manifest_merge() -> None:
    """The window of one area must not take the other area's rows with it."""
    speakers = {"tests": [{"case": "speakers/TC-001", "file": "speakers.py",
                           "test_function": "test_list", "status": "green"}],
                "unresolved": [{"case": "speakers/TC-002", "reason": "blocked_by_env"}]}
    detail = {"tests": [{"case": "TC-001", "area": "speaker-detail", "file": "detail.py",
                         "test_function": "test_open", "status": "green"}],
              "unresolved": [{"case": "TC-002", "area": "speaker-detail", "reason": "impossible"}]}
    merged, _ = P.merge(speakers, detail)
    check_eq("both areas' tests survive the merge",
             sorted(P._case(t) for t in merged["tests"]),
             ["speaker-detail/TC-001", "speakers/TC-001"])
    check_eq("and both areas' unresolved rows do too",
             sorted(P._case(u) for u in merged["unresolved"]),
             ["speaker-detail/TC-002", "speakers/TC-002"])

    # The move rules are per case, not per number: one area closing TC-002 says nothing
    # about the other area's TC-002.
    closed = {"tests": [{"case": "speakers/TC-002", "file": "speakers.py",
                         "test_function": "test_detail", "status": "green"}]}
    after, summary = P.merge(merged, closed)
    check_eq("a green test clears only its own area's unresolved row",
             [P._case(u) for u in after["unresolved"]], ["speaker-detail/TC-002"])
    check_eq("and the drop is counted once", summary["moved"], 1)

    blocked = {"unresolved": [{"case": "speaker-detail/TC-001", "reason": "blocked_by_env"}]}
    kept = P.merge(after, blocked)[0]
    check_eq("one area going unresolved leaves the other area's instance standing",
             sorted(P._case(t) for t in kept["tests"]),
             ["speakers/TC-001", "speakers/TC-002"])

    # Recovery: the event store replays every fragment from an empty manifest. Two areas
    # that were lost here is the incident this test exists for.
    replayed: dict = {}
    for fragment in (speakers, detail, closed, blocked):
        replayed = P.merge(replayed, fragment)[0]
    check_eq("a replay from zero ends where the live merges did",
             (sorted(P._case(t) for t in replayed["tests"]),
              sorted(P._case(u) for u in replayed["unresolved"])),
             (sorted(P._case(t) for t in kept["tests"]),
              sorted(P._case(u) for u in kept["unresolved"])))

    legacy = {"unresolved": [{"case": "TC-009", "reason": "impossible"}],
              "tests": [{"case": "TC-008", "file": "old.py", "marker": "TC-008"}]}
    old = P.merge(legacy, {"unresolved": [{"case": "TC-009", "reason": "blocked_by_env"}]})[0]
    check_eq("a manifest written by 0.7.x merges exactly as it always did",
             [(u["case"], u["reason"]) for u in old["unresolved"]], [("TC-009", "blocked_by_env")])
    check_eq("and its rows keep their bare spelling", P._case(old["tests"][0]), "TC-008")

    # A repair re-pins a case to its CURRENT version. The old version stood beside it, so the
    # delivery stage kept seeing the stale one and asked for the same repair again (a legacy
    # story looped on this for thirteen dispatches).
    stale = {"tests": [{"case": "TC-082", "file": "x.py", "test_function": "test_x",
                         "case_version_links": [{"case_id": "TC-082", "version": "cv_e791cbef9b7195262a80"},
                                                {"case_id": "TC-099", "version": "cv_other"}]}]}
    repair = {"tests": [{"case": "TC-082", "file": "x.py", "test_function": "test_x",
                          "case_version_links": [{"case_id": "TC-082", "version": "cv_c098ad9b0d4075cde6dc"}]}]}
    repaired = P.merge(stale, repair)[0]
    repeated = P.merge(repaired, repair)[0]
    links = repeated["tests"][0]["case_version_links"]
    check_eq("a repair replaces stale same-case CaseVersion links idempotently",
             sorted((x["case_id"], x["version"]) for x in links),
             [("TC-082", "cv_c098ad9b0d4075cde6dc"), ("TC-099", "cv_other")])

    view = {"tests": [t for t in kept["tests"]], "unresolved": kept["unresolved"]}
    check_eq("a view of one area shows that area only",
             [P._case(t) for t in W.pick_tests(view, ["speakers/TC-001"])], ["speakers/TC-001"])
    check_eq("and a bare id still shows every area holding that number",
             sorted(P._case(t) for t in W.pick_tests({"tests": merged["tests"]}, ["TC-001"])),
             ["speaker-detail/TC-001", "speakers/TC-001"])


def link(case: str, version: str, area: str = "") -> dict:
    return {"case_id": case, "version": version, **({"area": area} if area else {})}


def pairs(links) -> list:
    return [(C.case_link_key(x), x["version"]) for x in links]


def merge_links(old, new, **extra) -> list:
    return P._merge_entry({"case_version_links": old},
                          {"case_version_links": new, **extra})["case_version_links"]


def version_links() -> None:
    """One case has one current CaseVersion link; another case's link is never touched."""
    check_eq("a bare link replaces the bare link of its case and keeps the other cases, in order",
             pairs(merge_links([link("TC-1", "cv_old"), link("TC-2", "cv_two")],
                               [link("TC-1", "cv_new")])),
             [("TC-2", "cv_two"), ("TC-1", "cv_new")])
    check_eq("an area-qualified link replaces the bare link of its case",
             pairs(merge_links([link("TC-1", "cv_old")], [link("TC-1", "cv_new", "speakers")])),
             [("speakers/TC-1", "cv_new")])
    check_eq("an area-qualified link replaces the link of the same area",
             pairs(merge_links([link("TC-1", "cv_old", "speakers")],
                               [link("TC-1", "cv_new", "speakers")])),
             [("speakers/TC-1", "cv_new")])
    check_eq("a bare link replaces bare links only: the area's own link stands",
             pairs(merge_links([link("TC-1", "cv_old", "speakers")], [link("TC-1", "cv_new")])),
             [("speakers/TC-1", "cv_old"), ("TC-1", "cv_new")])
    check_eq("a link of another area is kept",
             pairs(merge_links([link("TC-1", "cv_det", "speaker-detail"), link("TC-1", "cv_old")],
                               [link("TC-1", "cv_new", "speakers")])),
             [("speaker-detail/TC-1", "cv_det"), ("speakers/TC-1", "cv_new")])
    check_eq("the area may be spelled inside the case id as well",
             pairs(merge_links([link("speakers/TC-1", "cv_old")],
                               [link("TC-1", "cv_new", "speakers")])),
             [("speakers/TC-1", "cv_new")])

    old = [link("TC-1", "cv_old"), link("TC-2", "cv_two")]
    new = [link("TC-1", "cv_new")]
    once = merge_links(old, new)
    check_eq("merging the same patch twice gives the same result", merge_links(once, new), once)
    check_eq("an empty incoming list removes nothing", merge_links(old, []), old)
    check_eq("two incoming links for one case: the last one wins",
             pairs(merge_links(old, [link("TC-1", "cv_a"), link("TC-1", "cv_b")])),
             [("TC-2", "cv_two"), ("TC-1", "cv_b")])
    check_eq("the last one wins on a first write too, with no old links",
             pairs(P._merge_entry({}, {"case_version_links": [link("TC-1", "cv_a"),
                                                              link("TC-1", "cv_b")]})
                   ["case_version_links"]),
             [("TC-1", "cv_b")])
    keyless = {"version": "cv_orphan"}
    check_eq("an incoming link with no case key accumulates, once",
             merge_links(old, [keyless, dict(keyless)]), old + [keyless])
    check_eq("non-dict entries are left alone and accumulate as before",
             merge_links(["opaque", link("TC-1", "cv_old")], ["opaque", "more", link("TC-1", "cv_new")]),
             ["opaque", "more", link("TC-1", "cv_new")])
    check_eq("`replace_fields` still replaces the whole list",
             merge_links(old, [link("TC-3", "cv_three")], replace_fields=["case_version_links"]),
             [link("TC-3", "cv_three")])
    untouched = P._merge_entry({"case_version_links": old}, {"status": "green"})
    check_eq("a patch without the field removes nothing", untouched["case_version_links"], old)
    # The two other link fields keep accumulating: only a CaseVersion is a current binding.
    both = P._merge_entry({"case_links": [link("TC-1", "cv_old")], "cases": ["TC-1"]},
                          {"case_links": [link("TC-1", "cv_new")], "cases": ["TC-2"]})
    check_eq("`case_links` and `cases` accumulate exactly as before",
             (pairs(both["case_links"]), both["cases"]),
             ([("TC-1", "cv_old"), ("TC-1", "cv_new")], ["TC-1", "TC-2"]))

    # `_retract_aliases`: two spellings of one instance collapse; the stale link is not added back.
    rows = [{"instance_id": "TC-1::test_x[a]", "case": "TC-1", "file": "a.py",
             "case_version_links": [link("TC-1", "cv_old"), link("TC-2", "cv_two")],
             "covers": ["TC-1", "TC-2"]},
            {"instance_id": "test_x[a]", "case": "TC-1", "file": "a.py",
             "case_version_links": [link("TC-1", "cv_new")], "covers": ["TC-1"]}]
    kept, retracted = P._retract_aliases(rows)
    check_eq("two spellings collapse into one row", (len(kept), retracted),
             (1, ["TC-1::test_x[a]"]))
    check_eq("the alias collapse keeps the live link and drops the stale one",
             pairs(kept[0]["case_version_links"]), [("TC-2", "cv_two"), ("TC-1", "cv_new")])
    check_eq("the other link fields keep their union", kept[0]["covers"], ["TC-1", "TC-2"])

    # Stories in flight: the projection replays every journalled patch through `merge`, so a
    # journal written by the accumulating code holds two same-case patches and must read as one.
    root = temp_project("qa-case-identity-replay-")
    try:
        ticket = "QA-1"
        task = root / "qa-factory" / "artifacts" / ticket
        from event_store import EventStore
        task.mkdir(parents=True)     # a journal write never creates the story folder (CX1-18); S0 does
        store = EventStore(task)

        def patch(case, version, name):
            return {"tests": [{"case": "TC-082", "file": "x.py", "test_function": "test_x",
                               "case_version_links": [link(case, version)]}], "note": name}
        # Journalled by hand: the events are fragments, which is what the old code stored too.
        for name, fragment in (("first", patch("TC-082", "cv_e791cbef9b7195262a80", "first")),
                               ("second", patch("TC-082", "cv_c098ad9b0d4075cde6dc", "second"))):
            store.commit("manifest_patch", {"fragment": fragment}, "manifest:" + name,
                         project=lambda events: None)
        third = root / "third.json"
        third.write_text(json.dumps({"tests": [
            {"case": "TC-099", "file": "y.py", "test_function": "test_y",
             "case_version_links": [link("TC-099", "cv_other")]}]}), encoding="utf-8")
        result = run_script("manifest_put.py", "--task", ticket, "--fragment", str(third), cwd=root,
                            env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        check_eq("manifest_put replays a journal of two same-case patches", result.returncode, 0)
        manifest = json.loads((task / "work" / "automation-manifest.json")
                              .read_text(encoding="utf-8"))
        by_case = {row["case"]: row for row in manifest["tests"]}
        check_eq("the same-case patches project to ONE link, the newer version",
                 pairs(by_case["TC-082"]["case_version_links"]),
                 [("TC-082", "cv_c098ad9b0d4075cde6dc")])
        check_eq("and the unrelated case survives", pairs(by_case["TC-099"]["case_version_links"]),
                 [("TC-099", "cv_other")])
        check_eq("the replay counted every patch", manifest.get("revision"), 3)
    finally:
        cleanup(root)


def legacy_instance_rows() -> None:
    """A story started on 0.7.6 and continued on 0.7.8 (live TP1-15045, 22.09): the old
    `TC-012::test_x[...]` rows stood beside the new `test_x[...]` ones and the S5 exit gate
    reported seven structural findings about instances nobody had written twice."""
    old = {"tests": [
        {"instance_id": "TC-012::test_validate[valid]", "case": "TC-012", "file": "api.py",
         "status": "green", "critic_verdict": "approved", "covers": ["TC-012"]},
        {"instance_id": "TC-014::test_persists[none]", "case": "TC-014", "file": "api.py",
         "status": "green", "covers": ["TC-014"]},
    ]}
    new = {"tests": [
        {"file": "api.py", "test_function": "test_validate", "parameter": "valid",
         "status": "green", "covers": ["TC-012", "TC-013"]},
        {"file": "api.py", "test_function": "test_persists", "parameter": "none",
         "status": "green", "covers": ["TC-014"]},
    ]}
    merged, summary = P.merge(old, new)
    ids = sorted(C.test_instance_id(t) for t in merged["tests"])
    check_eq("the 0.7.6 spelling leaves no ghost beside the current one", len(merged["tests"]), 2)
    check_eq("and every row reads in the current spelling", ids,
             ["test_persists[none]", "test_validate[valid]"])
    covered = sorted({case for t in merged["tests"] for case in C.manifest_test_links(t)})
    check_eq("every case link of both spellings survives", covered, ["TC-012", "TC-013", "TC-014"])
    check_eq("the verdict the old row carried is not lost",
             next(t for t in merged["tests"]
                  if C.test_instance_id(t) == "test_validate[valid]").get("critic_verdict"),
             "approved")

    # A row already standing twice is retracted on the next merge too — the repair reaches a
    # manifest that was written wrong before this rule existed.
    standing = {"tests": [old["tests"][0], new["tests"][0]]}
    repaired, repair_summary = P.merge(standing, {"run_witness": "evidence/w.json"})
    check_eq("a manifest that already holds both spellings is repaired in place",
             len(repaired["tests"]), 1)
    check_eq("the retraction is recorded for the person to read",
             repaired.get("retracted_instances"), ["TC-012::test_validate[valid]"])
    check_eq("and counted", repair_summary.get("retracted"), 1)
    check_eq("the first merge retired both old ids", summary.get("retracted"), 2)

    two_files = P.merge({"tests": [
        {"instance_id": "TC-1::test_x[a]", "file": "one.py", "covers": ["TC-1"]},
        {"instance_id": "TC-2::test_x[a]", "file": "two.py", "covers": ["TC-2"]}]},
        {"run_witness": "w.json"})[0]
    check_eq("two rows naming different files are two tests, never a spelling to collapse",
             len(two_files["tests"]), 2)

    # Nor are two PARTITIONS of one case. The legacy selector hash is the same for every
    # instance of a case when the only legacy field a row carries is the case's own marker, and
    # `_retract_aliases` read that hash as a shared alias: retracting one partition took its
    # sibling with it, evidence and all (found by the FR-40 walk, 28.09).
    partitions = [{"case": "TC-9", "file": "api.py", "marker": "TC-9",
                   "instance_id": "test_per_partition[missing]", "status": "green"},
                  {"case": "TC-9", "file": "api.py", "marker": "TC-9",
                   "instance_id": "test_per_partition[present]", "status": "green"}]
    check_eq("the hash of a case's marker is not an alias of one instance",
             [C.instance_id_aliases(row) for row in partitions],
             [["test_per_partition[missing]", "TC-9::test_per_partition[missing]"],
              ["test_per_partition[present]", "TC-9::test_per_partition[present]"]])
    kept, _ = P.merge({"tests": [dict(row) for row in partitions]},
                      {"retracted_instances": ["test_per_partition[present]"]})
    check_eq("so retracting one partition leaves the other standing",
             [row["instance_id"] for row in kept["tests"]], ["test_per_partition[missing]"])
    untouched, _ = P.merge({"tests": [dict(row) for row in partitions]},
                           {"run_witness": "evidence/w.json"})
    check_eq("and a merge about something else collapses neither",
             len(untouched["tests"]), 2)
    # A row whose legacy fields DO tell instances apart keeps the hash as an alias: that is what
    # it was kept for — a 0.7.4 manifest matching its own run blocks.
    legacy_row = {"case": "TC-9", "test": "api.py::test_per_partition", "parameters": {"p": "x"},
                  "instance_id": "test_per_partition[x]"}
    check("a legacy row that identifies its instance still answers to its hash",
          any(alias.startswith("ti_") for alias in C.instance_id_aliases(legacy_row)),
          str(C.instance_id_aliases(legacy_row)))


def pinning() -> None:
    root = temp_dir("qa-case-identity-")
    try:
        authoring, store = root / "authoring", root / "case-store"
        task = root / "artifacts" / "QA-1"
        sources = [write_case(authoring, area, number, f"{area} case {number}")
                   for area in AREAS for number in (1, 2, 3)]
        V.validate_batch(sources)
        records = [V.create_version(store, source) for source in sources]
        check_eq("the store records the area beside the number",
                 sorted({str(r.get("area")) for r in records}), sorted(AREAS))
        V.pin_batch(task, records)
        links = C.story_case_links(task)
        check_eq("every case of both areas is pinned", len(links), 6)
        check_eq("and each link carries its own identity",
                 sorted(C.case_link_key(link) for link in links),
                 sorted(f"{area}/TC-{n:03d}" for area in AREAS for n in (1, 2, 3)))

        # Recovery: the whole story is pinned again from the same bytes. This is where the two
        # entries were lost — the second area's pin evicted the first area's link.
        V.pin_batch(task, records)
        check_eq("re-pinning the whole story keeps every entry of both areas",
                 len(C.story_case_links(task)), 6)
        check_eq("and no case is pinned twice",
                 len({C.case_link_key(link) for link in C.story_case_links(task)}), 6)
        check_eq("nothing is left unpinned", V.unpinned(task, [authoring]), [])
        check_eq("no pinned version is dangling or modified", C.case_link_issues(task), [])

        index = C.case_index(task)
        check_eq("the index names both areas' cases", len(index), 6)
        check_eq("a colliding number is spelled with its area",
                 sorted(k for k in index if k.endswith("TC-001")),
                 ["speaker-detail/TC-001", "speakers/TC-001"])
        check_eq("and the index answers with the area's own file",
                 "speakers case 1" in index["speakers/TC-001"]["path"].read_text(encoding="utf-8"),
                 True)
        check("a bare id that two areas claim is not guessed at", index.get("TC-001") is None)
        check_eq("but it names both, which is what stage-scope needs",
                 sorted(index.matching("TC-001")), ["speaker-detail/TC-001", "speakers/TC-001"])

        # One area only: the spelling nothing has to change stays the spelling.
        solo = root / "artifacts" / "QA-2"
        V.pin_batch(solo, [r for r in records if r.get("area") == "speakers"])
        solo_index = C.case_index(solo)
        check_eq("a story with one area keeps the bare number as the identity",
                 sorted(solo_index), ["TC-001", "TC-002", "TC-003"])
        check_eq("and a reader that spells the area still finds the case",
                 solo_index.get("speakers/TC-002")["case_id"], "TC-002")
    finally:
        cleanup(root)


def legacy_links() -> None:
    """Links written by 0.7.x carry no `area`. They must read, update and not duplicate."""
    root = temp_dir("qa-case-identity-legacy-")
    try:
        authoring, store = root / "authoring", root / "case-store"
        task = root / "artifacts" / "QA-OLD"
        source = write_case(authoring, "speakers", 1, "first")
        record = V.create_version(store, source)
        old = dict(record)
        old.pop("area", None)
        V.pin(task, old)
        link = C.story_case_links(task)[0]
        check("a 0.7.x pin carries no area at all", "area" not in link)
        check_eq("and reads as the bare number it always was", C.case_link_key(link), "TC-001")
        check_eq("the index still finds it by either spelling",
                 (C.case_index(task).get("TC-001") is not None,
                  C.case_index(task).get("speakers/TC-001") is not None), (True, True))
        write_case(authoring, "speakers", 1, "second")
        second = V.create_version(store, source)
        V.pin(task, second, expected_previous_version=record["version"])
        links = C.story_case_links(task)
        check_eq("an area-aware pin updates that link instead of adding a second", len(links), 1)
        check_eq("and the area is recorded from then on", links[0].get("area"), "speakers")
        check_eq("the history keeps both versions", len(json.loads(
            V.link_path(task).read_text(encoding="utf-8"))["history"]), 2)
    finally:
        cleanup(root)


def entries_for_case() -> None:
    """t-044 item 2: the one predicate "this manifest entry answers this asked case" - the asker's
    spelling decides the reader (TP2-2406 S5-6: scope `feedback-api/TC-003`, row `covers`
    the same, every reader compared it with the BARE links). No ambiguity rule, no raise."""
    qualified = {"instance_id": "t_q", "covers": ["feedback-api/TC-003"],
                 "case_version_links": [{"case_id": "TC-003", "version": "cv_1"}]}
    bare = {"instance_id": "t_b", "case": "TC-003", "covers": ["TC-003"]}
    other = {"instance_id": "t_o", "covers": ["speakers/TC-003"]}
    rows = [qualified, bare, other]
    def ids(hits: list) -> list:
        return [e["instance_id"] for e in hits]

    check_eq("a qualified ask matches the entry whose keys hold it",
             ids(C.entries_for_case(rows, "feedback-api/TC-003")), ["t_q"])
    check_eq("a bare ask matches every entry whose links hold the number, across areas",
             ids(C.entries_for_case(rows, "TC-003")), ["t_q", "t_b", "t_o"])
    check_eq("a qualified ask is a miss on a bare-only row (no compatibility guess here)",
             ids(C.entries_for_case([bare], "feedback-api/TC-003")), [])
    check_eq("a qualified ask of another area is a miss",
             ids(C.entries_for_case([qualified], "speakers/TC-003")), [])
    check_eq("a bare ask is a miss on an entry that proves another number",
             ids(C.entries_for_case(rows, "TC-004")), [])
    check_eq("an empty ask answers nothing", C.entries_for_case(rows, ""), [])
    check_eq("a None ask answers nothing", C.entries_for_case(rows, None), [])
    check_eq("no entries answer nothing", C.entries_for_case([], "TC-003"), [])
    check_eq("None entries answer nothing, without a raise", C.entries_for_case(None, "TC-003"), [])
    check_eq("an entry that is not a dict is skipped",
             ids(C.entries_for_case(["TC-003", None, 7, bare], "TC-003")), ["t_b"])
    check_eq("a compound cell is not read as an area: it is asked whole, as a bare cell",
             C.entries_for_case([{"covers": ["TC-001/TC-002/TC-003"]}], "TC-001/TC-002/TC-003"), [])
    check_eq("a case id in the entry's own `area` field answers its qualified key",
             ids(C.entries_for_case([{"instance_id": "t_a", "area": "speakers", "covers": ["TC-003"]}],
                                    "speakers/TC-003")), ["t_a"])
    # t-1249 F6: the backslash spelling is the same key (`split_case_key` reads it so), compared as it yields it
    check_eq("a backslash-spelled qualified ask matches the entry that holds the slash key",
             ids(C.entries_for_case(rows, "feedback-api\\TC-003")), ["t_q"])
    check_eq("... and another area's slash key stays a miss for it",
             ids(C.entries_for_case([other], "feedback-api\\TC-003")), [])
    check_eq("a bare ask is untouched by the normalisation", ids(C.entries_for_case(rows, " TC-003 ")),
             ["t_q", "t_b", "t_o"])


def main() -> None:
    entries_for_case()
    spelling()
    manifest_merge()
    version_links()
    legacy_instance_rows()
    pinning()
    legacy_links()
    finish("test_case_identity")


if __name__ == "__main__":
    main()
