#!/usr/bin/env python3
"""A story resumed on a newer plugin migrates its own artifacts once (part 2).

TP1-15045 was written by 0.7.6 and continued on 0.7.8: `manifest_put` already reads a
0.7.7 `<case>::<function>` instance id as an alias of its bare form, but nothing ever
rewrote the OLD rows to that spelling, so the S5 exit gate reported seven "structural"
findings about instances nobody had actually written twice. The fix is `story_version`
(records `pipeline.json.plugin_version`) plus `migrate_artifacts.py --if-older` (compares it
against the installed build and rewrites what it finds, through the artifact's own writer,
never by hand) — proven here end to end: an old spelling becomes the current one, a second
run touches nothing, and a genuine collision is reported instead of corrupting a row.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, cleanup, finish,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import migrate_artifacts  # noqa: E402
import story_version  # noqa: E402

TASK = "QA-RESUME"


def _story(root: Path, plugin_version=None, tests=None) -> Path:
    art = root / "qa-factory" / "artifacts" / TASK
    (art / "work").mkdir(parents=True, exist_ok=True)
    (art / "state").mkdir(parents=True, exist_ok=True)
    pipeline = {"ticket": TASK, "stages": {}, "gates": {}, "halts": [], "warnings": []}
    if plugin_version is not None:
        pipeline["plugin_version"] = plugin_version
    (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    (art / "work" / "automation-manifest.json").write_text(
        json.dumps({"revision": 0, "tests": tests or [], "unresolved": []}), encoding="utf-8")
    return art


def version_comparison_is_conservative():
    check_eq("no recorded version reads as older than any installed one",
             story_version.is_older("", "0.7.9"), True)
    check_eq("an equal version is not older", story_version.is_older("0.7.9", "0.7.9"), False)
    check_eq("a numerically smaller version is older", story_version.is_older("0.7.6", "0.7.8"), True)
    check_eq("a numerically larger version is not older", story_version.is_older("0.7.9", "0.7.8"), False)
    check_eq("an unreadable installed version never triggers a migration",
             story_version.is_older("0.7.6", ""), False)


def record_is_idempotent_and_leaves_everything_else_alone():
    root = temp_project("qa-resume-record-")
    try:
        art = _story(root, plugin_version="0.7.6")
        first = story_version.record(art, "0.7.9")
        check("the first stamp writes", first["written"])
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("the field lands", pipeline["plugin_version"], "0.7.9")
        check_eq("the ticket is untouched", pipeline["ticket"], TASK)
        second = story_version.record(art, "0.7.9")
        check("the same version a second time writes nothing",
              not second["written"] and second["reason"] == "already recorded")
    finally:
        cleanup(root)


def a_never_recorded_story_migrates_the_legacy_spelling_once():
    root = temp_project("qa-resume-migrate-")
    try:
        use_project(root)
        legacy_row = {"case": "TC-012", "file": "tests/test_workflow.py",
                     "instance_id": "TC-012::test_validate[eu]", "status": "green",
                     "case_version_links": [{"case_id": "TC-012", "version": "cv_abc"}]}
        current_row = {"case": "TC-013", "file": "tests/test_other.py",
                       "instance_id": "test_already_current", "status": "green"}
        art = _story(root, plugin_version=None, tests=[legacy_row, current_row])
        report = migrate_artifacts.run_if_older(art)
        check("a story with no recorded version runs its migrations", report["ran"])
        check_in("the legacy id is named in what changed",
                 "TC-012::test_validate[eu] -> test_validate[eu]", report["changed"])
        manifest = json.loads((art / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        rows = {r.get("case"): r for r in manifest["tests"]}
        check_eq("the legacy row now carries the bare id", rows["TC-012"]["instance_id"],
                 "test_validate[eu]")
        check_eq("its other fields survive the rewrite", rows["TC-012"]["status"], "green")
        check_eq("the case link is not lost", rows["TC-012"]["case_version_links"][0]["case_id"],
                 "TC-012")
        check_eq("a row already spelled the current way is untouched",
                 rows["TC-013"]["instance_id"], "test_already_current")
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("the story is stamped with the installed version",
                 pipeline["plugin_version"], story_version.installed_version())
        journal = (root / "qa-factory" / "records" / "journal.jsonl")
        check("one journal line records the migration", journal.exists())
        events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
        migrated = [e for e in events if e.get("event") == "artifacts_migrated" and e.get("task") == TASK]
        check_eq("exactly one migration event for this run", len(migrated), 1)

        second = migrate_artifacts.run_if_older(art)
        check_eq("a second run on the same installed version is a no-op", second["ran"], False)
        events_after = journal.read_text(encoding="utf-8").splitlines()
        check_eq("and writes no second journal line", len(events_after), len(events))
    finally:
        cleanup(root)


def a_genuine_collision_is_reported_not_silently_merged():
    """Two legacy rows whose bare spelling collides but whose files differ is exactly what
    `manifest_put._refuse_colliding_ids` exists to catch — the migration must surface that
    refusal, never guess which row is right."""
    root = temp_project("qa-resume-collision-")
    try:
        use_project(root)
        row_a = {"case": "TC-020", "file": "tests/a.py", "instance_id": "TC-020::test_dup"}
        row_b = {"case": "TC-021", "file": "tests/b.py", "instance_id": "TC-021::test_dup"}
        art = _story(root, plugin_version="0.7.6", tests=[row_a, row_b])
        report = migrate_artifacts.run_if_older(art)
        check("the run still completes", report["ran"])
        check_eq("nothing is reported changed", report["changed"], [])
        check_eq("exactly one left entry for the whole manifest", len(report["left"]), 1)
        check_in("naming the artifact", "automation-manifest.json", report["left"][0]["artifact"])
        # manifest_put's own EventStore commits the fragment event before running the merge
        # that refuses it, so the projection failure is what surfaces here ("event committed;
        # projection stale..."), not the original "different files" text merge() raised with —
        # still a refusal, still non-empty, still never silently applied.
        check("and a non-empty reason is surfaced, not silently dropped",
              bool(report["left"][0]["reason"].strip()))
        manifest = json.loads((art / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        rows = {r.get("case"): r for r in manifest["tests"]}
        check_eq("neither row was corrupted by a wrong match",
                 (rows["TC-020"]["instance_id"], rows["TC-020"]["file"]),
                 ("TC-020::test_dup", "tests/a.py"))
        check_eq("the second row is untouched too",
                 (rows["TC-021"]["instance_id"], rows["TC-021"]["file"]),
                 ("TC-021::test_dup", "tests/b.py"))
    finally:
        cleanup(root)


def a_case_shaped_ghost_is_retracted_when_real_coverage_exists():
    """Seen on the live TP1-15045 manifest: a 0.7.6 window left a `tests[]`
    row whose `instance_id` IS the case id (`"TC-012"`, no function) before per-instance rows
    existed. `contract.instance_id_aliases` shares no alias with the real per-instance row that
    proves the same case today, so the spelling fix above cannot see it — this is a second,
    coverage-based pass."""
    root = temp_project("qa-resume-ghost-")
    try:
        use_project(root)
        ghost = {"case": "TC-012", "instance_id": "TC-012", "status": "green"}
        real = {"file": "tests/test_workflow.py", "test_function": "test_validate",
               "status": "green", "covers": ["TC-012"]}
        art = _story(root, plugin_version=None, tests=[ghost, real])
        report = migrate_artifacts.run_if_older(art)
        check("the run completes", report["ran"])
        check_in("the retraction is named in what changed", "TC-012", report["changed"])
        manifest = json.loads((art / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        ids = [r.get("instance_id") for r in manifest["tests"]]
        check("the ghost row is gone", "TC-012" not in ids, ids)
        check_eq("exactly the real row remains", len(manifest["tests"]), 1)
        check_eq("the real row is untouched", manifest["tests"][0].get("test_function"),
                 "test_validate")
        check_eq("no stray unresolved[] row is left for a case that IS covered",
                 manifest.get("unresolved"), [])
    finally:
        cleanup(root)


def a_case_shaped_ghost_with_no_coverage_is_left_and_reported():
    root = temp_project("qa-resume-ghost-orphan-")
    try:
        use_project(root)
        ghost = {"case": "TC-099", "instance_id": "TC-099", "status": "green"}
        art = _story(root, plugin_version=None, tests=[ghost])
        report = migrate_artifacts.run_if_older(art)
        check("the run completes", report["ran"])
        check_eq("nothing is reported changed", report["changed"], [])
        check("the orphan ghost is reported under left",
              any("TC-099" in x["artifact"] for x in report["left"]), report["left"])
        manifest = json.loads((art / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("and it is left exactly as it stood, not guessed at",
                 manifest["tests"][0]["instance_id"], "TC-099")
    finally:
        cleanup(root)


def a_legacy_selector_row_is_retracted_when_a_same_function_instance_covers_the_case():
    """The row this package retires: the live TP1-15045 TC-012 row, spelled the way
    0.7.6 wrote it — no `instance_id`, a `case`, and a function-level `selector` whose
    partitions are joined by `|`. Retracted because a real per-instance row of the SAME
    function (`test_validate_matches_update_outcome_per_partition`) already covers TC-012;
    removed by hand as revision 44 on the live manifest because 0.7.9's migration never saw
    this shape (`_fix_legacy_spellings` needs a `::`, `_retract_case_ghosts` needs a case-id
    `instance_id` — this row has neither)."""
    root = temp_project("qa-resume-legacy-selector-")
    try:
        use_project(root)
        legacy_row = {
            "case": "TC-012",
            "file": "testproject1_test_harness/tests/workflow/test_workflow_validate_api.py",
            "marker": "TC-012",
            "status": "green",
            "selector": "test_validate_matches_update_outcome_per_partition"
                       "[valid|missing-assistant|executor-failure|autonomous]",
            "case_version_links": [{"case_id": "TC-012", "version": "cv_78071ada7e71db77c5f4"}],
            "note": "4 partitions green; self-reference and consumer-warning partitions "
                    "unresolved; P-mcp/P-guardrail not implemented",
        }
        covering_row = {
            "instance_id": "test_validate_matches_update_outcome_per_partition[missing-assistant]",
            "file": "testproject1_test_harness/tests/workflow/test_workflow_validate_api.py",
            "selector": "testproject1_test_harness/tests/workflow/test_workflow_validate_api.py"
                       "::test_validate_matches_update_outcome_per_partition[missing-assistant]",
            "status": "green",
            "covers": ["TC-012"],
            "case_version_links": [{"case_id": "TC-012", "version": "cv_78071ada7e71db77c5f4"}],
            "case": "TC-012",
        }
        untouched_row = {"case": "TC-013", "file": "tests/test_other.py",
                         "instance_id": "test_already_current", "status": "green"}
        art = _story(root, plugin_version=None, tests=[legacy_row, covering_row, untouched_row])
        report = migrate_artifacts.run_if_older(art)
        check("the run completes", report["ran"])
        check("the retraction names the case and the function",
              any("TC-012" in line and "test_validate_matches_update_outcome_per_partition" in line
                  for line in report["changed"]), report["changed"])
        manifest = json.loads((art / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        selectors = [r.get("selector") for r in manifest["tests"] if not r.get("instance_id")]
        check("the legacy selector row is gone", not selectors, selectors)
        ids = {r.get("instance_id") for r in manifest["tests"]}
        check_eq("the covering instance and the unrelated row both survive", ids,
                 {"test_validate_matches_update_outcome_per_partition[missing-assistant]",
                  "test_already_current"})
        check_eq("no stray unresolved[] row is left for a case that IS covered",
                 manifest.get("unresolved"), [])

        second = migrate_artifacts.run_if_older(art)
        check_eq("a second run on the same installed version is a no-op", second["ran"], False)
    finally:
        cleanup(root)


def a_legacy_selector_row_with_no_same_function_coverage_is_left_and_reported():
    """A different case (TC-050) has per-instance rows, but none of the SAME function as the
    legacy row's selector — the row must not be retracted on the strength of some other test
    covering the case, only on a same-function one."""
    root = temp_project("qa-resume-legacy-selector-orphan-")
    try:
        use_project(root)
        legacy_row = {"case": "TC-050", "file": "tests/legacy.py",
                     "selector": "test_something_per_partition[a|b]"}
        unrelated_covering_row = {"instance_id": "test_other_thing", "file": "tests/legacy.py",
                                  "covers": ["TC-050"], "status": "green"}
        art = _story(root, plugin_version=None, tests=[legacy_row, unrelated_covering_row])
        report = migrate_artifacts.run_if_older(art)
        check("the run completes", report["ran"])
        check_eq("nothing is reported changed", report["changed"], [])
        check("the orphan legacy row is reported under left",
              any("TC-050" in x["artifact"] for x in report["left"]), report["left"])
        manifest = json.loads((art / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        selectors = [r.get("selector") for r in manifest["tests"] if r.get("case") == "TC-050"]
        check_eq("the legacy row is left exactly as it stood, not guessed at",
                 selectors, ["test_something_per_partition[a|b]"])
    finally:
        cleanup(root)


def a_story_already_on_the_installed_version_is_left_alone():
    root = temp_project("qa-resume-current-")
    try:
        use_project(root)
        row = {"case": "TC-030", "file": "tests/a.py", "instance_id": "TC-030::test_x"}
        art = _story(root, plugin_version=story_version.installed_version(), tests=[row])
        report = migrate_artifacts.run_if_older(art)
        check_eq("nothing runs for a story already on this build", report["ran"], False)
        manifest = json.loads((art / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("even a legacy-looking row is left exactly as it stood",
                 manifest["tests"][0]["instance_id"], "TC-030::test_x")
    finally:
        cleanup(root)


def a_stale_projection_is_reported_as_committed_not_refused():
    """t-1253 F-3: `manifest_put.py` exits 4 when the fragment IS in the journal and only the manifest's projection
    failed; the reason of `left` names the replay and never says the migration was refused or not written."""
    import subprocess
    from unittest.mock import patch
    root = temp_project("qa-resume-stale-")
    try:
        use_project(root)

        def exits(code: int, said: str):
            return lambda command, **_kw: subprocess.CompletedProcess(command, code, "", said)
        with patch.object(migrate_artifacts.subprocess, "run",
                          exits(4, "manifest_put: event committed; projection stale - the fragment is in the journal")):
            stale = migrate_artifacts._run_manifest_put(root, "QA-9", root, {"tests": []})
        with patch.object(migrate_artifacts.subprocess, "run", exits(3, "manifest_put: nothing was committed")):
            refused = migrate_artifacts._run_manifest_put(root, "QA-9", root, {"tests": []})
        with patch.object(migrate_artifacts.subprocess, "run", exits(0, "")):
            done = migrate_artifacts._run_manifest_put(root, "QA-9", root, {"tests": []})
        check_eq("t-1253 F-3: exit 4 is not ok, and the reason names the replay",
                 (stale[0], "`manifest_put.py --task QA-9 --recover`" in stale[1]), (False, True))
        check("t-1253 F-3: ... and does not call the committed fragment refused", "refused" not in stale[1], stale[1])
        check_eq("t-1253 F-3: CONTROL - exit 3 keeps manifest_put's own words as the reason",
                 refused, (False, "manifest_put: nothing was committed"))
        check_eq("t-1253 F-3: CONTROL - exit 0 is ok", done, (True, ""))
    finally:
        cleanup(root)


def main():
    a_stale_projection_is_reported_as_committed_not_refused()
    version_comparison_is_conservative()
    record_is_idempotent_and_leaves_everything_else_alone()
    a_never_recorded_story_migrates_the_legacy_spelling_once()
    a_genuine_collision_is_reported_not_silently_merged()
    a_case_shaped_ghost_is_retracted_when_real_coverage_exists()
    a_case_shaped_ghost_with_no_coverage_is_left_and_reported()
    a_legacy_selector_row_is_retracted_when_a_same_function_instance_covers_the_case()
    a_legacy_selector_row_with_no_same_function_coverage_is_left_and_reported()
    a_story_already_on_the_installed_version_is_left_alone()
    finish("story resume migration (part 2)")


if __name__ == "__main__":
    main()
