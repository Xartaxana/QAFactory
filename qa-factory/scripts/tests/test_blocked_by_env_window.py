#!/usr/bin/env python3
"""t-219: an S5 window blocked by the stand closes in one record (F-cmp2-28, part 1: the code).

TP1-15045 (cmp2, 30.09-01.10): TC_004 and TC_008 were written and statically reviewed, ran on a stand
whose edit page stayed on "Loading", and reached no Then. The window record had no word for that: an instance
that did not pass was `product:`, the controller wanted a fingerprint of a run that proved nothing, and the
critic went round the loop eight times. The word is `blocked_by_env` - the manifest's own `unresolved[].reason`
(FR-10) - and ONE reader, `acceptance.blocked_instances`, decides it for `window_record` (writes the outcome),
`validate_window` (re-derives it from the manifest, so a record that only CLAIMS the outcome is not believed)
and `s5_precheck` (the both-lists rule and the run mapping).

Acceptance keys (the spec's, with the critic's overrides C1-C18 of section 0c):
  K1  the cmp2 window: `window_record --review-receipt` exits 0 "acceptable as unresolved"; two lines
      without TC_004's verdict (C4); the fixture variants of C15
  K2  `story_step finish` accepts it, S5 completes, `unresolved` is derived, no rework, one record
  K3  a mixed window with a green instance that has its probe closes; without the probe it is refused
  K4  at gate B the stand gaps are cards with four answers; delivery is HELD (the release is a B-line, C5);
      the ledger is S5-local (C6) and says what it says today
  E1-E14 the edges, each with the invariant it protects; the 300-character limit AT and BEYOND

The fixture is the cmp2 manifest (tests[] 1029-1211, unresolved[] 1633-1681, bindings 1767-1796), the run
block `b673efc6...-reparse-d4223c4742a4` and `pipeline.json`, copied in below: the keys and values are the
real ones. Two things are NOT verbatim and are said where they happen: `novelty.measured_on` is cut to the
two files that matter (thirty helper hashes add nothing to a window), and TC_008 has NO run result - SYNTHETIC:
in reality it failed four times, here it "never ran" so that both shapes of a blocked instance (a run that
failed on the stand's page, and no run at all) stand in one window (C15).
"""
import contextlib
import copy
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import (check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(harness.SCRIPTS))
import acceptance as AC  # noqa: E402
import contract as C  # noqa: E402
import controller as CONTROLLER  # noqa: E402
import manifest_put as MP  # noqa: E402
import proof_level  # noqa: E402
import story_step  # noqa: E402
import window_record as WR  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_window_record as TW  # noqa: E402  (its story fixture and its stand-in detector)

TICKET = "TP1-15045"
AUTHOR = "S5-qa-automator-6"
CRITIC = "S5-qa-code-critic-3"
CASE_4 = "TP1-15045_TC_004"
CASE_8 = "TP1-15045_TC_008"
ID_4 = "test_version_history_button_accessible_from_visual_editor"
ID_8 = "test_shortcuts_with_history_popup_open_change_neither_diff_nor_editor"
FILE_4 = "testproject1_test_harness/tests/ui/workflows/test_workflow_version_history.py"
FILE_8 = "testproject1_test_harness/tests/ui/workflows/test_workflow_visual_diff_shortcuts.py"
WHERE = "frontend localhost:5173 /workflows/<id>/edit"
BLOCK = "b673efc6c5e33cd76206-reparse-d4223c4742a4.json"

# --- the cmp2 rows -------------------------------------------------------------------------------------

def _novelty(value: str, basis: str, sha: str, name: str) -> dict:
    # `measured_on` cut to the test file and pyproject.toml (the real one lists thirty helper files)
    return {"value": value, "basis": basis, "base": {"kind": "s0", "sha": "9a6a1a7927ed2e41b66765f28581e864b468a2bb"},
            "measured_on": {name: sha, "pyproject.toml": "93316b6a223648584e8917c170771aa750e1b74b3683261a2f9aa3a163a6a787"},
            "measured_by": "manifest_from_tests.py", "measured_at": "2026-10-01T07:53:31+00:00"}


def cmp2_tests() -> list:
    """manifest tests[] lines 1029-1211: the rows the automator wrote - red, no critic_verdict yet."""
    return [
        {"case": CASE_4, "covers": [CASE_4],
         "case_version_links": [{"case_id": CASE_4, "version": "cv_17147dda622d6dd2f88b"}],
         "requirements": ["R-15", "R-27"], "plan_row": "TS-4", "file": FILE_4, "marker": CASE_4,
         "test": ID_4, "selector": FILE_4 + "::" + ID_4, "instance_id": ID_4, "obligation_ids": ["OB-4"],
         "obligation_refs": [{"obligation_id": "OB-4",
                              "obligation_hash": "34d1d0807cda5b07ac6dd8054e35b1b8df1196f6fe5c505767ba121497ab43c0"}],
         "trace_binding": {"selector": FILE_4 + "::" + ID_4, "assertion_refs": [FILE_4 + ":45-66"],
                           "test_content_sha": "27121a15e01cc2a3fcf7899a8fd388ae5cfe3419bcbc0cfe48fa4e98b0e2b337"},
         "status": "red", "shape": "new", "consolidates": [CASE_4],
         "generated_from": [FILE_4, FILE_8],
         "novelty": _novelty("changed", "the test, or a file it uses, changed since the story's base 9a6a1a7927ed "
                             "(first difference: " + FILE_4 + ")",
                             "27121a15e01cc2a3fcf7899a8fd388ae5cfe3419bcbc0cfe48fa4e98b0e2b337", FILE_4),
         "assertion_id": FILE_4 + ":55",
         "defect_location": "testproject1-ui YamlPanel version history button (R-15, R-27)",
         "change_disposition": "new_or_changed", "change_basis_ref": "manifest:" + CASE_4},
        {"case": CASE_8, "covers": [CASE_8],
         "case_version_links": [{"case_id": CASE_8, "version": "cv_cd3951aa46f48d4f5067"}],
         "requirements": ["R-9", "R-25"], "plan_row": "TS-8", "file": FILE_8, "marker": CASE_8,
         "test": ID_8, "selector": FILE_8 + "::" + ID_8, "instance_id": ID_8, "obligation_ids": ["OB-8"],
         "obligation_refs": [{"obligation_id": "OB-8",
                              "obligation_hash": "ee913e844c327ed27c3403563606e4213550c748f222ef9c71b6be98bc2d7c6c"}],
         "trace_binding": {"selector": FILE_8 + "::" + ID_8, "assertion_refs": [FILE_8 + ":65-107"],
                           "test_content_sha": "ea2c80f1a08886baddb83bf14ead3363533030b7300f60decb1b5bc960928dc9"},
         "status": "red", "shape": "new", "consolidates": [CASE_8],
         "generated_from": [FILE_4, FILE_8],
         "novelty": _novelty("new", "the test file did not exist at the story's base 9a6a1a7927ed",
                             "ea2c80f1a08886baddb83bf14ead3363533030b7300f60decb1b5bc960928dc9", FILE_8),
         "assertion_id": FILE_8 + ":100",
         "defect_location": "testproject1-ui visual diff popup keyboard shortcut handling (R-9, R-25)",
         "change_disposition": "new_or_changed", "change_basis_ref": "manifest:" + CASE_8},
    ]


def remedy() -> dict:
    return {"kind": "service", "where": WHERE, "change": "edit page must finish loading (stand build or load gate timeout)",
            "restart": "re-run the window"}


def cmp2_unresolved() -> list:
    """manifest unresolved[] lines 1633-1681: one row per case, a partition and NO instance_id (C2)."""
    return [
        {"case": CASE_4, "reason": "blocked_by_env",
         "detail": "ran once: edit page stayed on Loading, heading Edit Workflow not visible in 5s; Then not reached",
         "remedy": remedy(), "requirements": ["R-15", "R-27"], "plan_row": "TS-4",
         "case_version_links": [{"case_id": CASE_4, "version": "cv_17147dda622d6dd2f88b"}],
         "partitions": ["tc004-visual-editor-history"]},
        {"case": CASE_8, "reason": "blocked_by_env", "detail": "edit page stayed on Loading in 2 runs; Then 1-4 not reached",
         "remedy": remedy(), "requirements": ["R-9", "R-25"], "plan_row": "TS-8",
         "case_version_links": [{"case_id": CASE_8, "version": "cv_cd3951aa46f48d4f5067"}],
         "partitions": ["tc008-shortcuts-popup-open"]},
    ]


def cmp2_bindings() -> list:
    """manifest obligation_bindings[] lines 1767-1796: no review_receipt_ref, sensitivity missing."""
    return [{"obligation_id": ob, "obligation_hash": digest, "instance_ids": [iid],
             "design_assessment": "sufficient", "assertion_refs": [assertion],
             "change_disposition": "new_or_changed", "change_basis_ref": "manifest:" + case,
             "code_validity": "unverified", "sensitivity": "missing"}
            for ob, digest, iid, assertion, case in (
                ("OB-4", "34d1d0807cda5b07ac6dd8054e35b1b8df1196f6fe5c505767ba121497ab43c0", ID_4, FILE_4 + ":55", CASE_4),
                ("OB-8", "ee913e844c327ed27c3403563606e4213550c748f222ef9c71b6be98bc2d7c6c", ID_8, FILE_8 + ":100", CASE_8))]


def sibling_of(row: dict, instance_id: str) -> dict:
    """A second test of the same case: its own id, its own function and selector (two rows that spell one
    function are one instance to `manifest_put`, which is the point of its alias rule)."""
    twin = copy.deepcopy(row)
    twin.update(instance_id=instance_id, test=instance_id, selector=FILE_4 + "::" + instance_id)
    twin["trace_binding"]["selector"] = twin["selector"]
    return twin


def critic_step(manifest: dict, verdicts=("unverified", "unverified")) -> dict:
    """What the critic does for a blocked instance (Q4): a static review, `unverified`, and the reason the live
    check is absent. `None` leaves that row with no verdict at all."""
    for row, verdict in zip(manifest["tests"], verdicts):
        row.pop("critic_verdict", None)
        if verdict is not None:
            row["critic_verdict"] = verdict
            row["sensitivity_proof_missing_reason"] = "blocked_by_env: " + WHERE
    return manifest


def cmp2_manifest(verdicts=("unverified", "unverified")) -> dict:
    return critic_step({"schema_version": 2, "tests": cmp2_tests(), "unresolved": cmp2_unresolved(),
                        "obligation_bindings": cmp2_bindings()}, verdicts)


def cmp2_run_block(environment: str = "localhost", status: str = "failed", with_shas: bool = True) -> dict:
    """The run block b673efc6...-reparse-d4223c4742a4 with TC_008's result removed (SYNTHETIC: it never ran)."""
    row = {"instance_id": ID_4,
           "test_id": "tests.ui.workflows.test_workflow_version_history::test_version_history_button_accessible_from_visual_editor",
           "case_version_links": [{"case_id": CASE_4, "version": "cv_17147dda622d6dd2f88b"}], "obligation_ids": ["OB-4"],
           "parameters": {}, "status": status, "reason": "AssertionError: Locator expected to be visible",
           "report_matched": True, "attempt_id": "b673efc6c5e33cd76206", "purpose": "initial", "repo_id": "",
           "profile_id": "e2e-ui", "equivalence_verified": False,
           "input_fingerprint": "5027c24e2f1177f3ddcadf870685113ced74c91121f867fa067fe6d03a3dc9c4",
           "source_fingerprint": {"source_sha": "e6532059cc2a965c0a37ba1a40cd481652d40481",
                                  "test_content_sha": "0957f189a02f1a6cb54566293d665a26ac8d0877f51835bb09ed6261d2a193f3"}}
    if with_shas:
        row.update(instance_content_sha="54d3d12425b4a7df282389a48d0bd14a662a618ef5a6e7f1d1cae06c7f21169b",
                   instance_content_scope="function",
                   instance_code_sha="2f5f61fbd626ac518e24c76d6c569692b1efe3422850a79c561da71dcf72637a")
    return {"schema_version": 2, "block_id": "b673efc6c5e33cd76206-reparse-d4223c4742a4",
            "attempt_id": "b673efc6c5e33cd76206", "attempt_started_at": "2026-10-01T06:12:48.612444+00:00",
            "attempt_ended_at": "2026-10-01T06:22:04.850100+00:00", "dispatch_id": AUTHOR, "profile_id": "e2e-ui",
            "repo_id": "", "purpose": "initial",
            "input_fingerprint": "5027c24e2f1177f3ddcadf870685113ced74c91121f867fa067fe6d03a3dc9c4",
            "source_fingerprint": row["source_fingerprint"],
            "runtime_provenance": {"profile_id": "e2e-ui", "timestamp": "2026-10-01T06:11:32+00:00",
                                   "environment_id": environment,
                                   "expected_source_revision": "e6532059cc2a965c0a37ba1a40cd481652d40481",
                                   "observed_runtime_identity": "verified_content:b42ab433b870|894b0057a09d"},
            "execution_status": status, "results": [row],
            "evidence": [{"summary": "", "reporter": "pytest", "report_path": "", "report_sha256": ""}],
            "reporter_mapping": {"mode": "exact", "source_attempt_id": "b673efc6c5e33cd76206", "reparsed": True},
            "report_scope": {"selected": [ID_4, ID_8], "unmatched_report_rows": []},
            "supersedes_block_id": "b673efc6c5e33cd76206",
            "reparse_of": "work/run-blocks/20261001T062231394053Z-b673efc6c5e33cd76206.json"}


# --- the story on disk -----------------------------------------------------------------------------------

def put(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def configure_case_form(project: Path) -> None:
    """cmp2's cases are `<ticket>_TC_<nnn>`: the project says so, as 15045's own config does (FR-13)."""
    config = project / "qa-factory" / "config.json"
    settings = json.loads(config.read_text(encoding="utf-8"))
    settings["case_id_form"] = "{ticket}_TC_{nnn}"
    config.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    C.case_config_reset()


def cmp2_story(project: Path, manifest=None, *, environment="localhost", block=True, block_status="failed") -> Path:
    """A task folder holding the cmp2 files: the manifest, the run block, pipeline.json and the two test files
    (a window reads the bytes of a test from its file). `block=False` leaves no run block at all."""
    task = project / "qa-factory" / "artifacts" / TICKET
    task.mkdir(parents=True, exist_ok=True)
    configure_case_form(project)
    for name in (FILE_4, FILE_8):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"def {Path(name).stem}():\n    assert True, 'stand'\n", encoding="utf-8")
    put(task / "pipeline.json", {"ticket": TICKET, "environment": environment, "stages": {"S5": {"status": "running"}}})
    put(task / "work/automation-manifest.json", manifest if manifest is not None else cmp2_manifest())
    if block:
        put(task / "work/run-blocks" / BLOCK, cmp2_run_block(status=block_status))
    return task


class StandIn:
    """`controller.Controller(task_root).state()` for `window_record.build`: the author accepted, the critic's
    dispatch running, both over the two cases of the cmp2 window."""

    def __init__(self, _root):
        pass

    def state(self):
        scope = [CASE_4, CASE_8]
        return {"dispatches": {
            AUTHOR: {"id": AUTHOR, "role": "qa-automator", "stage": "S5", "status": "accepted", "scope": scope,
                     "input_hash": "s5-h"},
            CRITIC: {"id": CRITIC, "role": "qa-code-critic", "stage": "S5", "status": "running", "scope": scope,
                     "input_hash": "s5-h"}},
            "required_quality_checks": list(StandIn.required_checks), "source_revision": "src-1"}

    required_checks = ()    # a test may set a check the window owes (a non-string id is always demanded)


@contextlib.contextmanager
def standin():
    """`window_record.build` over the stand-in controller and a detector that finds no changed test."""
    real, CONTROLLER.Controller = CONTROLLER.Controller, StandIn
    try:
        with TW.Detector({"pairs": [], "unmeasured": []}):
            yield
    finally:
        CONTROLLER.Controller = real


def cli(review_receipt: bool = False) -> tuple:
    """`window_record.run` the way the command runs it, in this process: (exit code, stdout)."""
    out = io.StringIO()
    with standin(), contextlib.redirect_stdout(out):
        code = WR.run(TICKET, CRITIC, "", review_receipt)
    return code, out.getvalue()


def build(task: Path) -> tuple:
    with standin():
        return WR.build(task, CRITIC)


def items_of(window: dict) -> dict:
    return {item["instance_id"]: item for item in window["instances"]}


def problem_lines(output: str) -> list:
    return [line[4:] for line in output.splitlines() if line.startswith("  - ")]


def reload_manifest(task: Path) -> dict:
    return json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))


def scope_of(window: dict) -> dict:
    return window["scope_instances"]


# --- K1 ---------------------------------------------------------------------------------------------------

def k1_the_cmp2_window_closes_in_one_record():
    project = temp_project("qa-blocked-k1-")
    use_project(project)
    try:
        task = cmp2_story(project)
        code, out = cli(review_receipt=True)
        check_eq("K1: window_record --review-receipt exits 0", code, 0)
        check_in("K1: and says it is acceptable AS UNRESOLVED, naming the instances, the fix's place and the stand "
                 "(O3: and that TC_004 RAN and went red; TC_008 never ran and carries no such mark)",
                 f"acceptable as unresolved: 2 instance(s) blocked by the stand - {ID_4}: {WHERE} on localhost "
                 f"(ran red: AssertionError: Locator expected to be visible); {ID_8}: {WHERE} on localhost\n", out)
        check_not_in("K1: and never calls it NOT acceptable (that line is the marker the driver loops on)",
                     "NOT acceptable", out)
        window = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        items = items_of(window)
        check_eq("K1: both items have the outcome blocked_by_env",
                 [items[ID_4]["outcome"], items[ID_8]["outcome"]], ["blocked_by_env", "blocked_by_env"])
        check_eq("K1: and no fingerprint is invented (present, empty)",
                 [items[ID_4]["execution_fingerprint"], items[ID_8]["execution_fingerprint"]], ["", ""])
        listed = window["blocked_by_env"]
        check_eq("K1: blocked_by_env[] has 2 entries", [e["instance_id"] for e in listed], [ID_4, ID_8])
        check_eq("K1: with the remedy's `where` of the row", [e["remedy"]["where"] for e in listed], [WHERE, WHERE])
        check_eq("K1: the stand localhost", [e["stand"] for e in listed], ["localhost", "localhost"])
        check_eq("K1: the cases each covers", [e["cases"] for e in listed], [[CASE_4], [CASE_8]])
        check_eq("K1: TC_004's last run is the failed one, kept (E4: a red is never deleted)",
                 (listed[0]["last_run"] or {}).get("status"), "failed")
        check_eq("K1: with its reason and its block",
                 ((listed[0]["last_run"] or {}).get("reason"), (listed[0]["last_run"] or {}).get("block")),
                 ("AssertionError: Locator expected to be visible", "work/run-blocks/" + BLOCK))
        check_eq("K1: TC_008 never ran (SYNTHETIC): no last run, said as null", listed[1]["last_run"], None)
        check_eq("K1: the failed run is cited as evidence; the instance that never ran cites none",
                 ([r["path"] for r in items[ID_4]["evidence_refs"]], items[ID_8]["evidence_refs"]),
                 (["work/run-blocks/" + BLOCK], []))
        check("K1: no probe is demanded, so none is written", "probe" not in items[ID_4] and "probe" not in items[ID_8])
        check_eq("K1: the record has no structural gap", C.window_shape_errors(window), [])
        check_eq("K1: and its ONLY gaps are the two blocked instances",
                 AC.validate_window(window, task), sorted(["blocked_by_env:" + ID_4, "blocked_by_env:" + ID_8]))
        manifest = reload_manifest(task)
        refs = {b["obligation_id"]: b.get("review_receipt_ref") for b in manifest["obligation_bindings"]}
        check_eq("K1: review_receipt_ref is on OB-4 and OB-8",
                 refs, {"OB-4": "work/review-receipts/" + CRITIC + ".json",
                        "OB-8": "work/review-receipts/" + CRITIC + ".json"})
        check("K1: and the immutable review receipt is on disk", (task / "work/review-receipts" / (CRITIC + ".json")).is_file())
    finally:
        cleanup(project)

    # without TC_004's verdict (C4): exit 1 and TWO lines - the gap and the shape error of the missing review
    project = temp_project("qa-blocked-k1b-")
    use_project(project)
    try:
        task = cmp2_story(project, cmp2_manifest(verdicts=(None, "unverified")))
        code, out = cli(review_receipt=True)
        lines = problem_lines(out)
        others = [l for l in lines if not l.startswith("blocked_by_env:")]
        check_eq("K1: without TC_004's verdict the exit is 1", code, 1)
        check_eq("K1: with exactly two lines besides the blocked ones (C4: the gap AND the shape error, never one)",
                 len(others), 2)
        check("K1: one is the gap `review:<id>`", any(l.startswith("review:" + ID_4) for l in others), "\n".join(lines))
        check("K1: the other is the shape error `<id>: review is missing`",
              any(l.startswith(ID_4 + ": review is missing") for l in others), "\n".join(lines))
        check_eq("K1: the blocked lines stay among the others (B4), one per blocked instance",
                 sorted(l.split(" ")[0] for l in lines if l.startswith("blocked_by_env:")),
                 sorted(["blocked_by_env:" + ID_4, "blocked_by_env:" + ID_8]))
        check_not_in("K1: TC_008, which has its verdict, is in no other line", ID_8, "\n".join(others))
        check("K1: no receipt is written for a window that is not acceptable",
              not (task / "work/review-receipts").exists())
    finally:
        cleanup(project)


# --- C15: the fixture variants ----------------------------------------------------------------------------

def c15_the_variants():
    # (a) DISTINCT remedies: each entry carries its own row's fix, never the first row's
    project = temp_project("qa-blocked-c15a-")
    use_project(project)
    try:
        manifest = cmp2_manifest()
        manifest["unresolved"][1]["remedy"] = {"kind": "flag", "where": "customer-config.yaml:304-311",
                                               "change": "features:subWorkflow enabled: true", "restart": "testproject1"}
        cmp2_story(project, manifest)
        window, _ = build(project / "qa-factory/artifacts" / TICKET)
        got = {e["instance_id"]: e["remedy"]["where"] for e in window["blocked_by_env"]}
        check_eq("C15: two cases, two remedies: each blocked instance names ITS row's fix",
                 got, {ID_4: WHERE, ID_8: "customer-config.yaml:304-311"})
    finally:
        cleanup(project)
    # (b) the run block's stand differs from pipeline.json's: the instance that ran says where IT ran
    project = temp_project("qa-blocked-c15b-")
    use_project(project)
    try:
        task = cmp2_story(project, environment="stand-b")
        window, _ = build(task)
        got = {e["instance_id"]: e["stand"] for e in window["blocked_by_env"]}
        check_eq("C15: TC_004 ran on `localhost` (its block), TC_008 never ran and takes the story's `stand-b`",
                 got, {ID_4: "localhost", ID_8: "stand-b"})
    finally:
        cleanup(project)
    # (c) FR-41: no run block says it and pipeline.json does not either - `unknown`, never a guess
    project = temp_project("qa-blocked-c15c-")
    use_project(project)
    try:
        task = cmp2_story(project, block=False)
        (task / "pipeline.json").unlink()
        window, _ = build(task)
        check_eq("C15/FR-41: no block and no pipeline.json: the stand is `unknown`",
                 [e["stand"] for e in window["blocked_by_env"]], ["unknown", "unknown"])
    finally:
        cleanup(project)
    # (d) ONE row with instance_ids (C1), and pair scoping (C3)
    project = temp_project("qa-blocked-c15d-")
    use_project(project)
    try:
        manifest = cmp2_manifest()
        row = manifest["unresolved"][0]
        row.pop("partitions")
        row["instance_ids"] = [ID_4, ID_8]  # names TC_008's instance too - but its case is TC_004
        manifest["unresolved"].pop(1)       # and TC_008 has no row of its own
        task = cmp2_story(project, manifest)
        window, _ = build(task)
        items = items_of(window)
        check_eq("C15/C1: the row of TC_004 carrying instance_ids blocks TC_004's instance",
                 items[ID_4]["outcome"], "blocked_by_env")
        check_eq("C15/C3: and does NOT block TC_008's: the alias matches, the instance does not cover the row's case",
                 items[ID_8].get("outcome"), None)
        check_eq("C15/C3: so TC_008 is a plain gap with no outcome (it never ran)",
                 [g for g in AC.validate_window(window, task) if ID_8 in g and g.startswith("product")],
                 ["product:" + ID_8])
    finally:
        cleanup(project)


# --- the reader: E1, E2, E3, E6, E7, C3, C8, C9 ------------------------------------------------------------

def scope_for(*pairs) -> dict:
    return {case: list(ids) for case, ids in pairs}


def asked(manifest, ids, scope, root=None, **more):
    refused: list = []
    got = AC.blocked_instances(manifest, [{"instance_id": i} for i in ids], scope, root, refused=refused, **more)
    return got, refused


def the_reader_and_its_error_direction():
    project = temp_project("qa-blocked-reader-")
    use_project(project)
    try:
        task = cmp2_story(project)
        manifest = cmp2_manifest()
        scope = scope_for((CASE_4, [ID_4]), (CASE_8, [ID_8]))
        got, refused = asked(manifest, [ID_4, ID_8], scope, task)
        check_eq("reader: the cmp2 rows (a partition, no instance_id) block each case's ONLY instance",
                 sorted(got), sorted([ID_4, ID_8]))
        check_eq("reader: it returns the row itself", got[ID_4]["partitions"], ["tc004-visual-editor-history"])
        check_eq("reader: and refuses nothing", refused, [])

        # E1: a row with no remedy is not a block; the refusal names what to add and the door
        bare = cmp2_manifest()
        bare["unresolved"][0].pop("remedy")
        got, refused = asked(bare, [ID_4], scope, task)
        check_eq("E1: no remedy: not blocked", got, {})
        check_eq("E1: the refusal says so, in the spec's own words", [r[2] for r in refused],
                 [f"{ID_4}: the blocked_by_env row has no remedy; the automator adds {{kind, where, change, restart}} "
                  "to that unresolved[] row through manifest_put.py"])
        # E2: a remedy that reads like a credential is not a block either
        secret = cmp2_manifest()
        secret["unresolved"][0]["remedy"] = {"kind": "credential", "where": ".env", "change": "sk8A9fKq2LmN7xP4wZ1vB3cD"}
        got, refused = asked(secret, [ID_4], scope, task)
        check_eq("E2: a remedy that looks like a secret: not blocked", got, {})
        check_in("E2: and the refusal says why", "looks like a secret value", refused[0][2] if refused else "")
        # E6 / C8: a whole-case row. With NO test row there is no instance; with exactly one red row it blocks
        whole = cmp2_manifest()
        for row in whole["unresolved"]:
            row.pop("partitions")
        got, _ = asked(whole, [ID_4], scope, task)
        check_eq("C8: a whole-case row beside exactly one red tests[] row blocks that instance", sorted(got), [ID_4])
        gone = copy.deepcopy(whole)
        gone["tests"] = [t for t in gone["tests"] if t["instance_id"] != ID_4]
        got, _ = asked(gone, [ID_4], scope_for((CASE_4, []), (CASE_8, [ID_8])), task)
        check_eq("E6: a whole-case row and NO tests[] row (what manifest_put leaves): no instance, nothing blocked",
                 got, {})
        check_eq("E6: and blocked_by_env is NOT among the reasons that let a case list no instance",
                 CONTROLLER.Controller.NO_INSTANCE_REASONS, ("impossible", "handed_to_person"))
        # E7: a partition row on a case with two instances is never guessed at
        two = cmp2_manifest()
        second = sibling_of(two["tests"][0], ID_4 + "_second")
        two["tests"].append(second)
        got, refused = asked(two, [ID_4, second["instance_id"]], scope_for((CASE_4, [ID_4, second["instance_id"]])), task)
        check_eq("E7: a partition row on a case with two instances: nothing is blocked", got, {})
        check_in("E7: and the refusal says to name the instance_id", "name the instance_id", refused[0][2] if refused else "")
        named = copy.deepcopy(two)
        named["unresolved"][0]["instance_ids"] = [ID_4]
        got, _ = asked(named, [ID_4, second["instance_id"]], scope_for((CASE_4, [ID_4, second["instance_id"]])), task)
        check_eq("E7: named, it blocks THAT instance and not its sibling", sorted(got), [ID_4])
        # a row for a case outside the scope; an instance_id that matches nothing; no manifest row at all
        outside = cmp2_manifest()
        outside["unresolved"][0]["case"] = "TP1-15045_TC_999"
        got, _ = asked(outside, [ID_4], scope, task)
        check_eq("a row for a case OUTSIDE the scope blocks nothing", got, {})
        nothing = cmp2_manifest()
        nothing["unresolved"][0].pop("partitions")
        nothing["unresolved"][0]["instance_ids"] = ["test_something_else"]
        got, _ = asked(nothing, [ID_4], scope, task)
        check_eq("a row whose instance_id matches nothing blocks nothing", got, {})
        check_eq("a hand-typed instance the manifest has no test row for is not blocked",
                 asked(manifest, ["test_hand_typed"], scope_for((CASE_4, ["test_hand_typed"])), task)[0], {})
        check_eq("no scope map: the allowed error, nothing is blocked", asked(manifest, [ID_4], None, task)[0], {})
        # C3: a test that also proves a case the row does not speak about is not blocked by a row with no instance
        consolidated = cmp2_manifest()
        consolidated["tests"][0]["covers"] = [CASE_4, CASE_8]
        consolidated["unresolved"].pop(1)
        both = scope_for((CASE_4, [ID_4]), (CASE_8, [ID_4, ID_8]))
        got, _ = asked(consolidated, [ID_4], both, task)
        check_eq("C3: the single-instance rule rejects an instance that covers cases outside the row", got, {})
        named_row = copy.deepcopy(consolidated)
        named_row["unresolved"][0].pop("partitions")
        named_row["unresolved"][0]["instance_ids"] = [ID_4]
        got, _ = asked(named_row, [ID_4], both, task)
        check_eq("C3: the same instance NAMED by the row is blocked (the alias branch asks only that it covers the row's case)",
                 sorted(got), [ID_4])
    finally:
        cleanup(project)


def e3_a_passed_run_beside_the_row_and_c9_the_bytes():
    project = temp_project("qa-blocked-e3-")
    use_project(project)
    try:
        task = cmp2_story(project, block_status="passed")
        manifest = cmp2_manifest()
        scope = scope_for((CASE_4, [ID_4]), (CASE_8, [ID_8]))
        # the run row carries the per-test shas; nothing says what the file holds as a TEST: it cannot be
        # measured, and "cannot tell" reads as PASSED - the forbidden error is "blocked" for an instance that is not
        got, refused = asked(manifest, [ID_4], scope, task)
        check_eq("E3/C9: a passed run whose bytes cannot be measured counts as passed: not blocked", got, {})
        check_in("E3: and the refusal says the blocked row is stale", "the blocked row is stale",
                 refused[0][2] if refused else "")
        window, notes = build(task)
        items = items_of(window)
        check_eq("E3: the window item says what happened: passed", items[ID_4]["outcome"], "passed")
        check_eq("E3: TC_008, with no run, is still blocked", items[ID_8]["outcome"], "blocked_by_env")
        info: list = []
        WR.verdict(task, window, notes, info)
        check("E3: the note is printed beside the verdict, not as a problem",
              any("the blocked row is stale" in line for line in info), str(info))
        # the same in the precheck: the row beside a GREEN tests[] row of its instance is `blocked-but-green`
        import s5_precheck
        green = cmp2_manifest()
        green["tests"][0]["status"] = "green"
        findings: list = []
        s5_precheck.check_manifest(green, [CASE_4, CASE_8], findings)
        tags = sorted((f["case"], f["id"].split("-", 1)[-1]) for f in findings if f["check"] == "manifest")
        check("E3: s5_precheck calls it `blocked-but-green` and names the door (manifest_put)",
              any(f["case"] == CASE_4 and "blocked-but-green" in f["id"] and "manifest_put.py" in f["fix"]
                  for f in findings), str(tags))
        check("E3: and never `both-lists` or `partial-green` for it",
              not any(f["case"] == CASE_4 and ("both-lists" in f["id"] or "partial-green" in f["id"]) for f in findings),
              str(tags))
        # C9: a passed run on OTHER bytes does not hide the block. The measurement is stood in for: the run row
        # says one test, the file now says another.
        same = {"input_hash": "r", "test_code_sha": "c", "why": "", "instance_identity": {
            "instance_content_sha": "54d3d12425b4a7df282389a48d0bd14a662a618ef5a6e7f1d1cae06c7f21169b",
            "instance_code_sha": "2f5f61fbd626ac518e24c76d6c569692b1efe3422850a79c561da71dcf72637a", "job_id": "j"}}
        other = dict(same, instance_identity=dict(same["instance_identity"], instance_content_sha="new-bytes",
                                                  instance_code_sha="new-code"))
        real = proof_level.instance_identity
        try:
            proof_level.instance_identity = lambda entry, root, project=None: same
            check_eq("C9: a passed run on the SAME test (the shas agree): stale row, not blocked",
                     asked(manifest, [ID_4], scope, task)[0], {})
            proof_level.instance_identity = lambda entry, root, project=None: other
            got, _ = asked(manifest, [ID_4], scope, task)
            check_eq("C9: a passed run on the OLD bytes of a test that changed: the new bytes never ran - blocked",
                     sorted(got), [ID_4])
            window, _ = build(task)
            listed = {e["instance_id"]: e for e in window["blocked_by_env"]}
            check_eq("C9: and the record keeps the passed run it did not believe (a pass is never deleted)",
                     (listed[ID_4]["last_run"] or {}).get("status"), "passed")
        finally:
            proof_level.instance_identity = real
        # a run row with no per-test shas cannot be measured either
        put(task / "work/run-blocks" / BLOCK, cmp2_run_block(status="passed", with_shas=False))
        check_eq("C9: a passed run row with no per-test shas counts as passed", asked(manifest, [ID_4], scope, task)[0], {})
    finally:
        cleanup(project)


# --- B3: what validate_window believes ------------------------------------------------------------------------

def b3_validate_window_rederives_from_the_manifest():
    project = temp_project("qa-blocked-b3-")
    use_project(project)
    try:
        task = cmp2_story(project)
        window, _ = build(task)
        check_eq("B3: a blocked item gives only blocked_by_env:<id> (the review is unverified, the probe not owed)",
                 AC.validate_window(window, task), sorted(["blocked_by_env:" + ID_4, "blocked_by_env:" + ID_8]))
        # a record hand-typed as blocked_by_env with NO manifest row: product:
        bare = cmp2_manifest()
        bare["unresolved"] = []
        put(task / "work/automation-manifest.json", bare)
        gaps = AC.validate_window(window, task)
        check("B3: no unresolved row, no block: the claim is `product:` for both (and every rule of a run applies)",
              "product:" + ID_4 in gaps and "product:" + ID_8 in gaps
              and not any(g.startswith("blocked_by_env:") for g in gaps), str(gaps))
        # E5: any verdict but `unverified` is a review gap, whatever the instance claims
        for verdict in ("rejected", "approved_with_fixes", "approved", ""):
            put(task / "work/automation-manifest.json", cmp2_manifest())
            claimed = copy.deepcopy(window)
            claimed["instances"][0]["review"]["verdict"] = verdict
            gaps = AC.validate_window(claimed, task)
            check(f"E5: verdict {verdict!r} on a blocked instance is a review gap (never rides out on `blocked`)",
                  "review:" + ID_4 in gaps and "blocked_by_env:" + ID_4 in gaps, str(gaps))
        # a blocked item that DID run cites its run block like any other: a moved hash is a gap (C4)
        moved = copy.deepcopy(window)
        moved["instances"][0]["evidence_refs"][0]["sha256"] = "0" * 64
        check("C4: a blocked item that ran keeps the evidence rule (a hash that moved is a gap)",
              "evidence:" + ID_4 in AC.validate_window(moved, task))
        empty = copy.deepcopy(window)
        empty["instances"][0]["evidence_refs"] = []
        check("C4: ... and one that never ran owes none; but an instance that is NOT blocked still does",
              "evidence:" + ID_8 not in AC.validate_window(window, task)
              and "evidence:" + ID_4 in AC.validate_window(dict(empty, instances=[
                  dict(empty["instances"][0], outcome="failed")] + empty["instances"][1:]), task))
        # the shape: the word is allowed, the probe-missing error skips it, but only for the two outcomes that never ran
        item = dict(window["instances"][0])
        shaped = dict(window, instances=[dict(item, outcome="failed")] + window["instances"][1:])
        check("shape: the probe is still demanded of a failed new_or_changed instance",
              any("probe is missing" in e for e in C.window_shape_errors(shaped)))
        check_eq("shape: WINDOW_OUTCOMES carries the word", "blocked_by_env" in C.WINDOW_OUTCOMES, True)
        # E12: a mechanical round is the author's green run on the current bytes: a blocked item is not green
        withround = dict(window, mechanical_round={"author_dispatch_id": AUTHOR, "reviewer_dispatch_id": CRITIC,
                                                   "reviewed_input_hash": "h"})
        check_eq("E12: a mechanical round over a blocked instance is refused by its own green-run rule",
                 AC.green_on_current_bytes_why(window["instances"][0], withround, task),
                 (False, "the instance's outcome is not passed"))
        # E13: a record with no `blocked_by_env` key reads as []
        old = copy.deepcopy(window)
        old.pop("blocked_by_env")
        check_eq("E13: an old record (no key) has no structural gap", C.window_shape_errors(old), [])
        check_eq("E13: and validates exactly as the new one", AC.validate_window(old, task), AC.validate_window(window, task))
        check_eq("E13: the key is ALWAYS written - `[]` when the stand blocked nothing",
                 _window_without_blocks(project)["blocked_by_env"], [])
    finally:
        cleanup(project)


def _window_without_blocks(project: Path) -> dict:
    """The cmp2 story with both cases green: nothing is blocked, and the key is there."""
    manifest = cmp2_manifest()
    manifest["unresolved"] = []
    task = cmp2_story(project, manifest)
    return build(task)[0]


# --- B5, E8, E9, E10, E14: story_step ----------------------------------------------------------------------------

def gaps_of(*pairs) -> list:
    return sorted(f"{kind}:{iid}" for kind, iid in pairs)


def e10_the_limit_at_and_beyond():
    shown = "work/windows/S5-qa-code-critic-3.json"
    head = "blocked_by_env; full list: " + shown
    fixed = len(head) + len("; blocked_by_env:")
    exact = "i" * (story_step.WINDOW_REASON_LIMIT - fixed)
    word, reason = story_step._derived_pair(gaps_of(("blocked_by_env", exact)), shown)
    check_eq("E10: a reason of exactly 300 characters is kept whole", (len(reason), reason.endswith(exact)), (300, True))
    word, reason = story_step._derived_pair(gaps_of(("blocked_by_env", exact + "x")), shown)
    check_eq("E10: 301 characters are cut to 300", len(reason), 300)
    check("E10: and the kinds and the path survive the cut", reason.startswith(head + "; "), reason[:80])
    word, reason = story_step._derived_pair(gaps_of(("blocked_by_env", "i" * 5000)), shown)
    check_eq("E10: a very long id is cut at the limit too", (len(reason), word), (300, "blocked_by_env"))
    long_path = "work/" + "d/" * 200 + "w.json"
    word, reason = story_step._derived_pair(gaps_of(("blocked_by_env", "a")), long_path)
    check("E10: a path longer than the limit itself is kept whole - the kinds and the path never go",
          reason == "blocked_by_env; full list: " + long_path, reason[:80])
    # the invariant (t-204 F1): ANY gap of another kind and nothing is derived
    for label, found in (("a product red", gaps_of(("blocked_by_env", "a"), ("product", "b"))),
                         ("a review gap", gaps_of(("blocked_by_env", "a"), ("review", "b"))),
                         ("a sensitivity gap", gaps_of(("blocked_by_env", "a"), ("sensitivity", "b"))),
                         ("an evidence gap of a handed instance (C4)",
                          gaps_of(("blocked_by_env", "a"), ("handed_to_person", "b"), ("evidence", "b"))),
                         ("no gaps at all", [])):
        check_eq(f"E8: {label}: nothing is derived", story_step._derived_pair(found, "w.json"), ())
    # E9: blocked and handed together: both kinds first in the reason, the first kind is the word
    word, reason = story_step._derived_pair(gaps_of(("blocked_by_env", "a"), ("handed_to_person", "b")), "w.json")
    check_eq("E9: the word is the first kind", word, "blocked_by_env")
    check("E9: and the reason names both kinds first, so names_handed still finds its word",
          reason.startswith("blocked_by_env, handed_to_person; full list: w.json; ")
          and CONTROLLER.names_handed({"unresolved": word, "reason": reason})
          and CONTROLLER.names_blocked({"unresolved": word, "reason": reason}), reason)
    check_eq("names_blocked reads a spelling the way names_handed does (a list of rows, a string, nothing)",
             [CONTROLLER.names_blocked({"unresolved": [{"reason": "blocked_by_env"}]}),
              CONTROLLER.names_blocked({"unresolved": True, "reason": "blocked_by_env: a"}),
              CONTROLLER.names_blocked({"unresolved": True, "reason": "gaps"}), CONTROLLER.names_blocked({}),
              CONTROLLER.names_blocked(None)], [True, True, False, False, False])


class Stop(Exception):
    pass


def finish_with_stub(task: Path, *, complete=True, unresolved=None, reason=None, window=None, dispatch=CRITIC) -> dict:
    """`story_step.finish` over the cmp2 task, a stand-in controller that records what it was asked to prepare
    (nothing is accepted), and no handover form: the options the controller would receive."""
    import argparse
    seen: list = []

    class Recorder:
        def __init__(self, _root, wait_seconds=0.0):
            pass

        def state(self):
            return {"dispatches": {dispatch: {"stage": "S5", "role": "qa-code-critic"}}}

        def prepare(self, options):
            seen.append(dict(options))
            raise Stop()
    saved = {n: getattr(story_step, n) for n in ("Controller", "_task_root", "_stages", "_handoff_check",
                                                 "_evidence", "_role_receipts")}
    story_step.Controller, story_step._task_root = Recorder, lambda _t: task
    story_step._stages, story_step._handoff_check = (lambda: {"S5": {"roles": ["qa-automator", "qa-code-critic"]}},
                                                     lambda *_a: ("green", "", ""))
    story_step._evidence, story_step._role_receipts = lambda *_a: ["work/x.json"], lambda *_a: []
    try:
        ns = argparse.Namespace(task=TICKET, dispatch_id=dispatch, digest="d", output=None, not_complete=not complete,
                                complete=complete, ignore_handoff=False, window=window, unresolved=unresolved,
                                reason=reason)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                story_step.finish(ns)
        except Stop:
            pass
    finally:
        for name, value in saved.items():
            setattr(story_step, name, value)
    return seen[0] if seen else {}


def b5_story_step_derives_the_pair():
    project = temp_project("qa-blocked-b5-")
    use_project(project)
    try:
        task = cmp2_story(project)
        cli(review_receipt=True)
        options = finish_with_stub(task)
        check_eq("B5: the critic's finish carries `unresolved` = blocked_by_env", options.get("unresolved"), "blocked_by_env")
        reason = options.get("reason") or ""
        check("B5: and the reason names BOTH instances", ID_4 in reason and ID_8 in reason, reason)
        check("B5: ... after the kind and the record's own path",
              reason.startswith("blocked_by_env; full list: work/windows/" + CRITIC + ".json; "), reason)
        check("B5/O3: ... then the mark that TC_004 RAN and went red (it is the only one that ran), before the gaps",
              reason.startswith("blocked_by_env; full list: work/windows/" + CRITIC + ".json; "
                                "ran red: AssertionError: Locator expected to be visible; blocked_by_env:"), reason)
        check_eq("B5/O3: and TC_008, which never ran, adds no mark", reason.count("ran red"), 1)
        check("B5: ... within the limit", len(reason) <= story_step.WINDOW_REASON_LIMIT, str(len(reason)))
        check("B5: and the window was loaded for the controller", isinstance(options.get("window"), dict))
        # E14: an open stage stays open
        open_stage = finish_with_stub(task, complete=False)
        check("E14: --not-complete with blocked gaps: nothing is derived and no window is passed",
              "unresolved" not in open_stage and "reason" not in open_stage and "window" not in open_stage, str(open_stage))
        # a caller's pair goes through unchanged - except Q8: the controller needs the WORD
        keep = finish_with_stub(task, unresolved="could_not_judge", reason="the stand is down: blocked_by_env, see the list")
        # F2 (critic t-243): TC_004 of this fixture RAN red, so the caller's pair gains the `ran red` mark too
        red_mark = "; ran red: AssertionError: Locator expected to be visible"
        check_eq("Q8: a caller's pair that already names blocked_by_env keeps its words, plus the F2 `ran red` mark",
                 (keep.get("unresolved"), keep.get("reason")),
                 ("could_not_judge", "the stand is down: blocked_by_env, see the list" + red_mark))
        added = finish_with_stub(task, unresolved="could_not_judge", reason="the critic's own words")
        check_eq("Q8: one that does not gets `; blocked_by_env: <ids>` appended, its own words first",
                 (added.get("unresolved"), added.get("reason")),
                 ("could_not_judge", f"the critic's own words; blocked_by_env: {', '.join(sorted([ID_4, ID_8]))}"
                                     + red_mark))
        # E8: any other gap - nothing is derived (t-204 F1)
        manifest = cmp2_manifest()
        manifest["tests"][1]["critic_verdict"] = "approved"  # TC_008: a claim of a live check on a test that never ran
        put(task / "work/automation-manifest.json", manifest)
        cli()
        mixed = finish_with_stub(task)
        check("E8: a review gap beside the blocked ones: nothing is derived - the controller's own refusal stays reachable",
              "unresolved" not in mixed, str(mixed))
        # a record the validation cannot read: nothing is derived either (the allowed error)
        put(task / "work/windows" / (CRITIC + ".json"), {"window": "W", "instances": [1, 2]})
        check("a window the validation cannot read derives nothing and does not crash",
              "unresolved" not in finish_with_stub(task))
    finally:
        cleanup(project)


# --- B6: the controller ---------------------------------------------------------------------------------------

def story_with_blocked_instances(project: Path, blocked: dict) -> tuple:
    """TW's coverage-v2 story at S5 (two cases, two instances, the author accepted, the critic running), with the
    given instances BLOCKED: `blocked` maps an instance id to its case. Each blocked instance gets the critic's
    `unverified`, a row with a remedy, and - for test_a[x] - a failed run (a red on the stand's page); test_b[y]
    never ran (its run block is deleted). Returns (task, remedy)."""
    task, _controller = TW.a_story_at_s5(project)
    manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
    rows = []
    for row in manifest["tests"]:
        if row["instance_id"] in blocked:
            row["critic_verdict"] = "unverified"
            row["sensitivity_proof_missing_reason"] = "blocked_by_env: " + WHERE
            rows.append({"case": blocked[row["instance_id"]], "reason": "blocked_by_env",
                         "instance_ids": [row["instance_id"]], "detail": "the edit page stayed on Loading; no Then reached",
                         "remedy": remedy()})
    manifest["unresolved"] = rows
    TW.write(task / "work/automation-manifest.json", manifest)
    if "test_a[x]" in blocked:   # a red on the stand's own page
        failed = json.loads((next((task / "work/run-blocks").glob("*b1.json"))).read_text(encoding="utf-8"))
        failed["execution_status"] = "failed"
        failed["results"][0].update(status="failed", reason="AssertionError: Locator expected to be visible")
        failed["runtime_provenance"] = {"environment_id": "localhost"}
        TW.write(next((task / "work/run-blocks").glob("*b1.json")), failed)
    if "test_b[y]" in blocked:   # never ran
        next((task / "work/run-blocks").glob("*b2.json")).unlink()
    return task, remedy()


def run_window_cli(project: Path, *more):
    return run_script("window_record.py", "--task", TW.TICKET, "--dispatch", TW.CRITIC, *more, cwd=project)


def finish_cli(project: Path, task: Path, *more):
    findings = task / "work/test-code/critic-findings.md"
    findings.parent.mkdir(parents=True, exist_ok=True)
    findings.write_text("# findings\n\nthe stand blocked both tests; a static review only\n", encoding="utf-8")
    return run_script("story_step.py", "finish", "--task", TW.TICKET, "--dispatch-id", TW.CRITIC,
                      "--digest", "qa-code-critic S5 done", "--ignore-handoff", "--output",
                      "work/test-code/critic-findings.md", "--output", "work/windows/" + TW.CRITIC + ".json", *more,
                      cwd=project)


def k2_and_b6_the_story_closes_on_one_record():
    project = temp_project("qa-blocked-k2-")
    use_project(project)
    try:
        task, _ = story_with_blocked_instances(project, {"test_a[x]": "TC-1", "test_b[y]": "TC-2"})
        built = run_window_cli(project, "--review-receipt")
        check_eq("K2: the window record exits 0 (acceptable as unresolved)", built.returncode, 0)
        check_in("K2: and says so", "acceptable as unresolved: 2 instance(s) blocked by the stand", built.stdout)
        window = json.loads((task / "work/windows" / (TW.CRITIC + ".json")).read_text(encoding="utf-8"))
        check_eq("K2: the stand is `localhost` for the instance that ran (its block) and `unknown` for the one that "
                 "never did (this story has no pipeline.json: FR-41)",
                 {e["instance_id"]: e["stand"] for e in window["blocked_by_env"]},
                 {"test_a[x]": "localhost", "test_b[y]": "unknown"})
        dispatches = sorted(CONTROLLER.Controller(task).state()["dispatches"])
        # B6: the controller refuses a completion that does not NAME the word - and says what to say
        refused = TW.accept_window(project, task, window, "plain", unresolved=["TC-1", "TC-2"],
                                   reason="the critic could not close this window")
        check("B6: a completion that does not name `blocked_by_env` is refused", refused.returncode != 0,
              refused.stdout + refused.stderr)
        check_in("B6: the refusal names the gaps", "blocked_by_env:test_a[x]", refused.stdout + refused.stderr)
        check_in("B6: the word expected", "naming `blocked_by_env`", refused.stdout + refused.stderr)
        check_in("B6: and the command that derives the pair (story_step finish)", "story_step.py finish --task",
                 refused.stdout + refused.stderr)
        check_eq("B6: nothing was accepted by the refusal", CONTROLLER.Controller(task).state()["dispatches"][TW.CRITIC]["status"],
                 "running")
        done = finish_cli(project, task)
        check_eq("K2: story_step finish of the critic is accepted, exit 0", done.returncode, 0)
        check_in("K2: said so", "accepted " + TW.CRITIC, done.stdout)
        state = CONTROLLER.Controller(task).state()
        record = state["dispatches"][TW.CRITIC]
        check_eq("K2: the dispatch is accepted and S5 is completed", (record["status"], state["stages"]["S5"]["status"]),
                 ("accepted", "completed"))
        check_eq("K2: `unresolved` is blocked_by_env", record.get("unresolved"), "blocked_by_env")
        check("K2: and the reason names both ids",
              "test_a[x]" in str(record.get("reason")) and "test_b[y]" in str(record.get("reason")), str(record.get("reason")))
        check_eq("K2: no rework is dispatched", sorted(state["dispatches"]), dispatches)
        check_eq("K2: ONE record was built (no second window file)",
                 sorted(p.name for p in (task / "work/windows").glob("*.json")), [TW.CRITIC + ".json"])
        # C17: coverage_contract.witnessed_binding reads the window through validate_window: a blocked instance
        # reads "not witnessed" - the right direction
        import coverage_contract as CC
        binding = {"obligation_id": "OB-TS-1", "review_receipt_ref": "work/windows/" + TW.CRITIC + ".json",
                   "quality_not_applicable_reason": "no quality checks", "change_disposition": "new_or_changed",
                   "change_basis_ref": "manifest:TC-1", "sensitivity": "proven", "probe_receipt_ref": TW.PROBE_REF}
        binding["obligation_hash"] = next(r["obligation_hash"] for item in window["instances"]
                                          for r in item["obligation_refs"] if r["obligation_id"] == "OB-TS-1")
        check_eq("C17: coverage_contract.witnessed_binding reads a blocked instance as NOT witnessed",
                 CC.witnessed_binding(task, binding, ["test_a[x]"]), False)
        k4_gate_b(project, task)
    finally:
        cleanup(project)


def k4_gate_b(project: Path, task: Path):
    """K4 on the K2 story: the person's card at gate B, the delivery HOLD, and the S5-local ledger (C5, C6)."""
    import check_delivery
    import ledger
    import stand_gaps
    gaps = stand_gaps.collect(task, "B")
    check_eq("K4: gate B lists both cases", sorted(g["case"] for g in gaps), ["TC-1", "TC-2"])
    check_eq("K4: each carries the remedy of its row", [g["remedy"]["where"] for g in gaps], [WHERE, WHERE])
    check_eq("K4: the reason on the card is `blocked_by_env`, the manifest's own word", {g["reason"] for g in gaps},
             {"blocked_by_env"})
    card = stand_gaps.render(gaps)
    import gate_brief   # t-357: the card offers the four answers by the words of the data file (never `apply`/`theirs`/`handed`)
    check("K4: the four answers are on the card", all(row["word"] in card for row in gate_brief.stand_gap_words()), card[:400])
    check("K4: and the card never calls the instances passed or failed",
          not re.search(r"\b(passed|failed)\b", card), card[:400])
    reasons = check_delivery.completeness_reasons(task)
    held = "{case} is held by the stand and waits for your answer on its stand-gap card at gate B"
    check("K4: check_delivery HOLDS: `blocked on the stand: <case> ...` for each case",
          all(f"blocked on the stand: {held.format(case=case)}" in reasons for case in ("TC-1", "TC-2")), str(reasons))
    records = [r for r in check_delivery.completeness_records(task) if r["kind"] == "env_undecided"]
    check_eq("K4: the typed records of the two stand holds are owned by the environment, none by the product",
             sorted((r["text"][:len("blocked on the stand: TC-1")], check_delivery.reason_record(r["text"])["owner"])
                    for r in records),
             [("blocked on the stand: TC-1", "environment"), ("blocked on the stand: TC-2", "environment")])
    # K5 (kind and text agree), for the records whose case is not STALE (a STALE row is legitimately the factory's)
    import delivery_verdict as DV
    kind_owner = DV.load_kinds()[0]["kinds"]["env_undecided"]["owner"]
    check_eq("K5: for every env_undecided record the text owner equals the kind's declared owner",
             {check_delivery.reason_record(r["text"])["owner"] for r in records}, {kind_owner})
    # C5: the HOLD only. `waiver.py --block "stand gap: <case>"` is the card's own door (stage_overrides[]), and
    # check_delivery never reads `stand_gap_decisions`: the hold stays. Releasing it is a B-line.
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8")) if (task / "pipeline.json").is_file() else {}
    pipeline.setdefault("stage_overrides", []).append({"stage": "S9", "match": "stand gap: TC-1", "decision": "accept",
                                                       "at": "2026-10-01T12:00:00"})
    TW.write(task / "pipeline.json", pipeline)
    check("K4/C5: after the person's `stand gap: TC-1` word the hold is STILL there (the release is queued)",
          f"blocked on the stand: {held.format(case='TC-1')}" in check_delivery.completeness_reasons(task))
    # C6: the blocked state is S5-local. A terminal result supersedes the row in the ledger, so for TC-1 - whose
    # instance ran and failed on the stand's page - the ledger prints a FAILED state, and for TC-2, which never ran,
    # `env_blocked`. What the person reads is S7's to judge; the reconciliation is queued.
    manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
    report = {"current_results": [{"instance_id": "test_a[x]", "case": "TC-1", "status": "failed",
                                   "reason": "AssertionError: Locator expected to be visible"}]}
    row = {"ts": "TS-1", "disposition": "automate"}
    state, _detail = ledger.plan_row_state(row, manifest, report, {}, {"TS-1": ["TC-1"]})
    check_eq("K4/C6: today the ledger prints `failed:...` for the blocked instance that ran red (S5-local state)",
             state.split(":")[0], "failed")
    state, _detail = ledger.plan_row_state({"ts": "TS-2", "disposition": "automate"}, manifest, report, {},
                                           {"TS-2": ["TC-2"]})
    check("K4/C6: and `env_blocked` for the one that never ran - not `not executed`", state.startswith("env_blocked"), state)


# --- K3: the mixed window --------------------------------------------------------------------------------------

def k3_a_mixed_window():
    project = temp_project("qa-blocked-k3-")
    use_project(project)
    try:
        task, _ = story_with_blocked_instances(project, {"test_b[y]": "TC-2"})
        # test_a[x] is green with its probe (the story's own fixture); test_b[y] never ran
        built = run_window_cli(project, "--review-receipt")
        check_eq("K3: a green instance with a valid probe and a blocked one: acceptable as unresolved, exit 0",
                 built.returncode, 0)
        window = json.loads((task / "work/windows" / (TW.CRITIC + ".json")).read_text(encoding="utf-8"))
        check_eq("K3: the instance that ran keeps every rule: outcome passed, a probe, a fingerprint",
                 (items_of(window)["test_a[x]"]["outcome"], "probe" in items_of(window)["test_a[x]"],
                  bool(items_of(window)["test_a[x]"]["execution_fingerprint"])), ("passed", True, True))
        check_eq("K3: only the blocked one is gapped", AC.validate_window(window, task), ["blocked_by_env:test_b[y]"])
        import coverage_contract as CC
        manifest = reload_manifest(task)
        binding = next(b for b in manifest["obligation_bindings"] if b["obligation_id"] == "OB-TS-1")
        done = finish_cli(project, task)
        check_eq("K3: the window closes", done.returncode, 0)
        check_eq("K3: with the word derived", CONTROLLER.Controller(task).state()["dispatches"][TW.CRITIC].get("unresolved"),
                 "blocked_by_env")
        # C17 control: the SAME reader says "witnessed" for the green instance of the window and "not" for the blocked one
        binding = {"obligation_id": "OB-TS-1", "obligation_hash": binding["obligation_hash"],
                   "review_receipt_ref": "work/windows/" + TW.CRITIC + ".json",
                   "quality_not_applicable_reason": "no quality checks", "change_disposition": "new_or_changed",
                   "change_basis_ref": "manifest:TC-1", "sensitivity": "proven", "probe_receipt_ref": TW.PROBE_REF,
                   "assertion_refs": ["tests/test_tc-1.py:12"]}
        check_eq("C17 control: the green instance of this window IS witnessed (the reader can say yes)",
                 CC.witnessed_binding(task, binding, ["test_a[x]"], {"test_a[x]": {"input_fingerprint": "fp-a"}}), True)
    finally:
        cleanup(project)

    # without the probe of the green instance: a gap of its own, nothing derived, the controller refuses
    project = temp_project("qa-blocked-k3b-")
    use_project(project)
    try:
        task, _ = story_with_blocked_instances(project, {"test_b[y]": "TC-2"})
        manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
        for binding in manifest["obligation_bindings"]:
            binding.pop("probe_receipt_ref", None)
        TW.write(task / "work/automation-manifest.json", manifest)
        (task / TW.PROBE_REF).unlink()
        built = run_window_cli(project)
        check_eq("K3: the probe removed: exit 1", built.returncode, 1)
        check_in("K3: refusal `sensitivity:<id>`", "sensitivity:test_a[x]", built.stdout)
        check_in("K3: and the blocked instance is among the lines, not alone", "blocked_by_env:test_b[y]", built.stdout)
        window = json.loads((task / "work/windows" / (TW.CRITIC + ".json")).read_text(encoding="utf-8"))
        gaps = AC.validate_window(window, task)
        check("K3: the gaps are the green instance's missing proof and the blocked one",
              "sensitivity:test_a[x]" in gaps and "blocked_by_env:test_b[y]" in gaps
              and all(g.endswith(":test_a[x]") or g == "blocked_by_env:test_b[y]" for g in gaps), str(gaps))
        options = finish_with_stub(task, dispatch=TW.CRITIC)
        check("K3: story_step derives NOTHING over a gap nobody named - no `unresolved` reaches the controller",
              "unresolved" not in options and "window" in options, str(sorted(options)))
        before = CONTROLLER.Controller(task).state()["revision"]
        done = finish_cli(project, task)
        check("K3: and the real finish is refused by the controller's own gates", done.returncode != 0, done.stdout)
        check_eq("K3: nothing was recorded", CONTROLLER.Controller(task).state()["revision"], before)
    finally:
        cleanup(project)


# --- E6 at the controller ----------------------------------------------------------------------------------------

def e6_the_controller_still_refuses_an_empty_scope():
    import test_fixes_13797 as FIX
    root = harness.temp_project("qa-blocked-e6-")
    try:
        controller, window = FIX.v2_story_at_s5(root)
        FIX.manifest_with(root, "blocked_by_env")
        message = FIX.refused(controller.apply, "accept",
                              FIX.completion(window, "env", unresolved=["TC-2"], reason="blocked_by_env: the stand is down"))
        check_in("E6: a case that lists no instance is not closed by `blocked_by_env` - an unwritten test is not a blocked one",
                 "it does not carry TC-2", message)
    finally:
        cleanup(root)


# --- B8: the stand came back (E11) ------------------------------------------------------------------------------------

def b8_a_green_entry_takes_its_blocked_row_with_it():
    project = temp_project("qa-blocked-b8-")
    use_project(project)
    configure_case_form(project)
    try:
        b8_in_a_project()
    finally:
        cleanup(project)


def b8_in_a_project():
    manifest = cmp2_manifest()
    green = {"tests": [{"instance_id": ID_4, "case": CASE_4, "covers": [CASE_4], "file": FILE_4, "status": "green"}]}
    merged, summary = MP.merge(copy.deepcopy(manifest), green)
    check_eq("B8/C2: the partition-scoped row of the instance that went green is dropped (the cmp2 shape)",
             [row["case"] for row in merged["unresolved"]], [CASE_8])
    check_eq("B8: the other case's row is untouched", merged["unresolved"][0]["partitions"], ["tc008-shortcuts-popup-open"])
    check_eq("B8: and the drop is counted as a move", summary["moved"], 1)
    check_eq("B8: the input was not edited in place (rows are replaced, never mutated)", manifest, cmp2_manifest())
    # a critic's verdict patch has no `status`: it is not a green run and drops nothing
    review = {"tests": [{"instance_id": ID_4, "critic_verdict": "unverified"}]}
    kept, _ = MP.merge(copy.deepcopy(manifest), review)
    check_eq("B8: a verdict-only fragment (no status) drops no blocked row", len(kept["unresolved"]), 2)
    # a row carrying instance_ids loses the id that went green and is dropped when the list is empty (C1)
    listed = cmp2_manifest()
    listed["unresolved"][0].pop("partitions")
    listed["unresolved"][0]["instance_ids"] = [ID_4, "test_other_of_tc4"]
    listed["tests"].append(sibling_of(listed["tests"][0], "test_other_of_tc4"))
    merged, _ = MP.merge(copy.deepcopy(listed), green)
    row = next(r for r in merged["unresolved"] if r["case"] == CASE_4)
    check_eq("B8/C1: the id that went green leaves `instance_ids`, the other stays blocked", row["instance_ids"],
             ["test_other_of_tc4"])
    merged, _ = MP.merge(merged, {"tests": [{"instance_id": "test_other_of_tc4", "case": CASE_4, "covers": [CASE_4],
                                             "file": FILE_4, "status": "green"}]})
    check_eq("B8/C1: and the row goes once the list is empty", [r["case"] for r in merged["unresolved"]], [CASE_8])
    # a partition row on a case with TWO instances is never guessed at (E7): the allowed error is to leave it
    two = cmp2_manifest()
    two["tests"].append(sibling_of(two["tests"][0], ID_4 + "_second"))
    merged, _ = MP.merge(two, green)
    check_eq("B8/E7: a partition row on a case with two instances survives a green of one of them",
             sorted(r["case"] for r in merged["unresolved"]), [CASE_4, CASE_8])
    # an instance_ids row never takes the tests[] rows of its case with it (`_whole_case`)
    row_only = {"unresolved": [{"case": CASE_4, "reason": "blocked_by_env", "instance_ids": [ID_4], "remedy": remedy()}]}
    merged, _ = MP.merge(copy.deepcopy(manifest), row_only)
    check_eq("C1: a row naming instance_ids is instance-scoped: the tests[] rows of its case stay",
             sorted(t["instance_id"] for t in merged["tests"]), sorted([ID_4, ID_8]))
    check_eq("B8: a row naming no instance and no partition is still a whole-case row (today's rule)",
             MP._partition_scoped({"case": CASE_4, "reason": "blocked_by_env"}), False)
    # E11: the stand is back - after the merge the window is a normal one for that instance
    project = temp_project("qa-blocked-e11-")
    use_project(project)
    try:
        task = cmp2_story(project, merged_green_manifest(green), block_status="passed")
        window, _ = build(task)
        check_eq("E11: the instance that went green reads passed, and only TC_008 is still blocked",
                 (items_of(window)[ID_4]["outcome"], [e["instance_id"] for e in window["blocked_by_env"]]),
                 ("passed", [ID_8]))
    finally:
        cleanup(project)


def k18_h6_a_later_green_unblocks_the_case():
    """RD1-4 K18 (B-306 d, H6), re-verification with no code change: a case parked as blocked by the stand is NOT blocked by
    a later passed run on the current bytes (`REFUSED_STALE`), and once that green `tests[]` entry goes through the manifest
    writer (`manifest_put.merge`) the case has no `unresolved[]` row and check_delivery holds no stand reason for it."""
    import check_delivery
    project = temp_project("qa-blocked-k18-")
    use_project(project)
    configure_case_form(project)
    try:
        task = cmp2_story(project, block_status="passed")
        manifest = cmp2_manifest()
        scope = scope_for((CASE_4, [ID_4]), (CASE_8, [ID_8]))
        got, refused = asked(manifest, [ID_4], scope, task)
        check_eq("K18: a passed run beside the blocked row: the instance is not blocked", got, {})
        check_eq("K18: and the refusal is the STALE one", [r[0] for r in refused], [AC.REFUSED_STALE])
        green = {"tests": [{"instance_id": ID_4, "case": CASE_4, "covers": [CASE_4], "file": FILE_4, "status": "green"}]}
        merged = merged_green_manifest(green)
        check_eq("K18: after the writer the case has no unresolved row", [r["case"] for r in C.manifest_unresolved(merged)
                                                                         if r["case"] == CASE_4], [])
        task = cmp2_story(project, merged, block_status="passed")
        texts = [r["text"] for r in check_delivery.completeness_records(task) if r["kind"] == "env_undecided"]
        check("K18: check_delivery holds no stand reason for the case that went green",
              not any(CASE_4 in t for t in texts), str(texts))
        check("K18: (control) it still holds the one of the case that never ran", any(CASE_8 in t for t in texts), str(texts))
    finally:
        cleanup(project)


def merged_green_manifest(green: dict) -> dict:
    manifest = cmp2_manifest()
    merged, _ = MP.merge(manifest, green)
    return merged


# --- s5_precheck: the run mapping and the both-lists rule ---------------------------------------------------------------

def b7_the_precheck():
    import s5_precheck
    project = temp_project("qa-blocked-b7-")
    use_project(project)
    try:
        task = cmp2_story(project)
        # the instance-scoped row beside a RED row: the third allowed shape, no `both-lists`
        listed = cmp2_manifest()
        listed["unresolved"][0].pop("partitions")
        listed["unresolved"][0]["instance_ids"] = [ID_4]
        findings: list = []
        s5_precheck.check_manifest(listed, [CASE_4, CASE_8], findings)
        check_eq("B7: an `instance_ids` row beside a red tests[] row is no `both-lists` finding",
                 [f["id"] for f in findings if "both-lists" in f["id"]], [])
        check_eq("B7: nor a `partial-green` one", [f["id"] for f in findings if "partial-green" in f["id"]], [])
        # beside a GREEN row of THAT instance: blocked-but-green; beside a green row of ANOTHER instance: nothing
        listed["tests"][0]["status"] = "green"
        findings = []
        s5_precheck.check_manifest(listed, [CASE_4, CASE_8], findings)
        check("B7: beside a green row of its own instance: `blocked-but-green`",
              any("blocked-but-green" in f["id"] for f in findings), str([f["id"] for f in findings]))
        sibling = copy.deepcopy(listed["tests"][0])
        sibling["instance_id"] = ID_4 + "_sibling"
        listed["tests"][0]["status"] = "red"
        listed["tests"].append(dict(sibling, status="green"))
        findings = []
        s5_precheck.check_manifest(listed, [CASE_4, CASE_8], findings)
        check_eq("B7: beside a green row of ANOTHER instance of the case: no finding at all (the normal state of a case "
                 "with several)", [f["id"] for f in findings if f["case"] == CASE_4], [])
        # the run mapping: a blocked instance is not asked for a reporter row; the same instance with no remedy is
        for manifest, label, expected in ((cmp2_manifest(), "a blocked instance", False),
                                          (None, "the same instance with NO remedy (not blocked)", True)):
            if manifest is None:
                manifest = cmp2_manifest()
                for row in manifest["unresolved"]:
                    row.pop("remedy")
            put(task / "work/automation-manifest.json", manifest)
            put(task / "work/run-blocks" / BLOCK, dict(cmp2_run_block(), results=[]))
            result = s5_precheck.run(task, None)
            mapping = [f for f in result["findings"] if f["check"] == "run_mapping" and f["case"] == CASE_8]
            check_eq(f"B7: run mapping asks for TC_008's reporter row: {label}", bool(mapping), expected)
        findings = []
        manifest = cmp2_manifest()
        manifest["unresolved"][0].pop("remedy")
        notes: list = []
        s5_precheck.check_environment(task, manifest, [CASE_4, CASE_8], {}, {}, findings, notes)
        check("B7: a row with no remedy keeps its `remedy-missing` finding",
              any("remedy-missing" in f["id"] for f in findings), str([f["id"] for f in findings]))
    finally:
        cleanup(project)


# --- the fix wave after the critic of t-226 (O1, O3, O5) ---------------------------------------------------------

def o3_the_red_that_ran_is_marked():
    """O3 (P20, FR-10): a red that RAN is parked as blocked, and the line says `ran red` with its reason."""
    cut = "…"
    check_eq("O3: never ran (no last_run): no mark", AC.ran_red(None), "")
    check_eq("O3: a passed last run: no mark", AC.ran_red({"status": "passed", "reason": "x"}), "")
    check_eq("O3: failed with an empty reason: said so", AC.ran_red({"status": "failed", "reason": ""}),
             "ran red: (no reason recorded)")
    check_eq("O3: failed with a whitespace-only reason: the same", AC.ran_red({"status": "failed", "reason": " \n "}),
             "ran red: (no reason recorded)")
    check_eq("O3: failed with no reason key: the same", AC.ran_red({"status": "failed"}), "ran red: (no reason recorded)")
    check_eq("O3: a reason of exactly 60 characters is kept whole", AC.ran_red({"status": "failed", "reason": "r" * 60}),
             "ran red: " + "r" * 60)
    check_eq("O3: 61 characters are cut to 60 with an ellipsis", AC.ran_red({"status": "failed", "reason": "r" * 61}),
             "ran red: " + "r" * 60 + cut)
    check_eq("O3: line breaks become spaces (the mark stays one line)",
             AC.ran_red({"status": "failed", "reason": "a\n  b\tc"}), "ran red: a b c")
    # end to end through the CLI line
    for label, reason, expected in (("a 70-character reason is cut at 60", "r" * 70, "(ran red: " + "r" * 60 + cut + ")"),
                                    ("an empty reason says so", "", "(ran red: (no reason recorded))")):
        project = temp_project("qa-blocked-o3-")
        use_project(project)
        try:
            task = cmp2_story(project)
            block = cmp2_run_block()
            block["results"][0]["reason"] = reason
            put(task / "work/run-blocks" / BLOCK, block)
            code, out = cli()
            line = next((l for l in out.splitlines() if l.startswith("acceptable as unresolved")), "")
            check_eq(f"O3: the CLI is still acceptable ({label})", code, 0)
            check_in(f"O3: the line carries the mark of the instance that ran: {label}", f"on localhost {expected}", line)
            check_eq(f"O3: and exactly one mark (TC_008 never ran): {label}", line.count("ran red"), 1)
            check_not_in(f"O3: nothing past the cut: {label}", "r" * 61, line)
        finally:
            cleanup(project)


def o5_a_red_needs_its_detail():
    """O5 (FR-34): a blocked row for an instance that has a terminal FAILED run needs a non-empty `detail`: the
    automator's word for the control that shows the stand, not the product, stopped it. One that never ran needs none."""
    project = temp_project("qa-blocked-o5-")
    use_project(project)
    try:
        task = cmp2_story(project)
        scope = scope_for((CASE_4, [ID_4]), (CASE_8, [ID_8]))
        whole = cmp2_manifest()  # the C8 shape: a whole-case row beside exactly one red tests[] row
        for row in whole["unresolved"]:
            row.pop("partitions")
        got, refused = asked(whole, [ID_4, ID_8], scope, task)
        check_eq("O5: with its detail (today's behaviour) the red is blocked", (sorted(got), refused), (sorted([ID_4, ID_8]), []))
        for label, absent in (("absent", None), ("an empty string", ""), ("whitespace only", "  \n\t ")):
            bare = copy.deepcopy(whole)
            if absent is None:
                bare["unresolved"][0].pop("detail")
            else:
                bare["unresolved"][0]["detail"] = absent
            got, refused = asked(bare, [ID_4, ID_8], scope, task)
            check_eq(f"O5: detail {label} on the instance that ran and failed: not blocked; the one that never ran still is",
                     sorted(got), [ID_8])
            said = [r for r in refused if r[0] == AC.REFUSED_NO_DETAIL]
            check_eq(f"O5: and ONE refusal says so, for that instance ({label})", [r[1] for r in said], [ID_4])
            sentence = said[0][2] if said else ""
            check(f"O5: it names the row's case and the instance ({label})", CASE_4 in sentence and ID_4 in sentence, sentence)
            check(f"O5: it names both doors: the automator's `detail` and the critic's verdict ({label})",
                  "automator adds a `detail`" in sentence and "critic judges" in sentence, sentence)
            check(f"O5: and no script name ({label})", ".py" not in sentence, sentence)
        # the never-ran instance with no detail: nothing is owed
        quiet = copy.deepcopy(whole)
        quiet["unresolved"][1].pop("detail")
        got, refused = asked(quiet, [ID_8], scope, task)
        check_eq("O5: an instance that never ran owes no detail", (sorted(got), refused), ([ID_8], []))
        # a PASSED run is the stale rule, not this one
        put(task / "work/run-blocks" / BLOCK, cmp2_run_block(status="passed"))
        bare = copy.deepcopy(whole)
        bare["unresolved"][0].pop("detail")
        got, refused = asked(bare, [ID_4], scope, task)
        check_eq("O5: a passed run beside a row with no detail is the STALE refusal, not a detail one",
                 [r[0] for r in refused], [AC.REFUSED_STALE])
        put(task / "work/run-blocks" / BLOCK, cmp2_run_block())
        # the window: the red without its detail is a plain failure (product:), the refusal line is printed
        bare = cmp2_manifest()
        bare["unresolved"][0].pop("detail")
        put(task / "work/automation-manifest.json", bare)
        code, out = cli()
        lines = problem_lines(out)
        check_eq("O5: the window is refused, exit 1", code, 1)
        check("O5: the red is a failure of its own: `product:<id>`",
              any(l.startswith("product:" + ID_4) for l in lines), "\n".join(lines))
        check("O5: the instance that never ran is still blocked",
              any(l.startswith("blocked_by_env:" + ID_8) for l in lines), "\n".join(lines))
        check("O5: and the refusal that names the row and the doors is among the lines",
              any(l.startswith(CASE_4 + ": the blocked_by_env row for " + ID_4) and "automator adds a `detail`" in l
                  for l in lines), "\n".join(lines))
        # the way through, FR-40: the automator adds the detail (a fragment through manifest_put) and the same record closes
        merged, _ = MP.merge(copy.deepcopy(bare), {"unresolved": [{"case": CASE_4, "reason": "blocked_by_env",
                                                                   "detail": "a direct GET of the edit route answers 200; "
                                                                             "the same page on /workflows loads"}]})
        put(task / "work/automation-manifest.json", merged)
        code, out = cli()
        check_eq("O5: with the detail sent the same window is acceptable as unresolved", code, 0)
    finally:
        cleanup(project)


def o1_the_instance_a_later_row_no_longer_names():
    """O1: a later fragment that names [b] only REPLACES the naming; the refusal line then says why t[a] - a red
    that ran - is no longer blocked, with the row's own naming in it."""
    project = temp_project("qa-blocked-o1-")
    use_project(project)
    try:
        manifest = cmp2_manifest()
        second = sibling_of(manifest["tests"][0], ID_4 + "_second")
        manifest["tests"].append(second)
        manifest["unresolved"].pop(1)
        manifest["unresolved"][0].pop("partitions")
        manifest["unresolved"][0]["instance_ids"] = [ID_4]
        later = {"unresolved": [{"case": CASE_4, "reason": "blocked_by_env", "instance_ids": [second["instance_id"]],
                                 "remedy": remedy(), "detail": "never reached a Then"}]}
        merged, _ = MP.merge(manifest, later)
        check_eq("O1: the merged row names [b] only", merged["unresolved"][0]["instance_ids"], [second["instance_id"]])
        task = cmp2_story(project, merged)
        scope = scope_for((CASE_4, [ID_4, second["instance_id"]]))
        got, refused = asked(merged, [ID_4, second["instance_id"]], scope, task)
        check_eq("O1: [b] is blocked, [a] - which ran red - is not", sorted(got), [second["instance_id"]])
        said = [r for r in refused if r[0] == AC.REFUSED_NAMES]
        check_eq("O1: ONE refusal, for [a]", [r[1] for r in said], [ID_4])
        check_in("O1: it says what the row names and what it does not",
                 f"{CASE_4}'s blocked_by_env row names [{second['instance_id']}], not {ID_4}", said[0][2] if said else "")
        check_in("O1: and how to satisfy it: list every blocked instance of the case", "instance_ids", said[0][2] if said else "")
        code, out = cli()
        check_eq("O1: the window is refused (a red with no row is a failure)", code, 1)
        check_in("O1: and the refusal is printed with the gap", f"not {ID_4}", out)
        # the instance a row does not name is NOT refused when it passed: one blocked test and its green sibling is normal
        put(task / "work/run-blocks" / BLOCK, cmp2_run_block(status="passed"))
        got, refused = asked(merged, [ID_4, second["instance_id"]], scope, task)
        check_eq("O1: a sibling whose latest run PASSED is no refusal subject", [r[0] for r in refused if r[0] == AC.REFUSED_NAMES], [])
    finally:
        cleanup(project)


def e5b_a_rejected_blocked_instance_is_receipted_and_sent_back():
    """t-1603: E5 stays (a rejected review of a blocked test is a gap), but the critic's `rejected` has a road: the
    receipt is written, the exit stays 1, and the window goes back to its author."""
    import coverage_contract as CC
    project = temp_project("qa-blocked-e5b-")
    use_project(project)
    try:
        task = cmp2_story(project, cmp2_manifest(verdicts=("rejected", "unverified")))
        code, out = cli(review_receipt=True)
        check_eq("K1: a rejected blocked instance exits 1, never 0", code, 1)
        check_in("K1: and says the window is sent back to its author", "sent back to its author", out)
        check_not_in("K1: and never calls it acceptable", "acceptable", out.replace("NOT acceptable", ""))
        receipt = task / "work/review-receipts" / (CRITIC + ".json")
        check("K2: the receipt exists", receipt.is_file())
        check("K2: and records the verdict rejected", '"rejected"' in receipt.read_text(encoding="utf-8"))
        manifest = reload_manifest(task)
        refs = {b["obligation_id"]: b.get("review_receipt_ref") for b in manifest["obligation_bindings"]}
        check_eq("K3: OB-4 carries review_receipt_ref", refs.get("OB-4"), "work/review-receipts/" + CRITIC + ".json")
        window = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        gaps = AC.validate_window(window, task)
        check("K4: validate_window still holds review: and blocked_by_env: for the instance",
              "review:" + ID_4 in gaps and "blocked_by_env:" + ID_4 in gaps, str(gaps))
        binding = next(b for b in manifest["obligation_bindings"] if b["obligation_id"] == "OB-4")
        check_eq("edge: a send-back receipt never witnesses a binding", CC.witnessed_binding(task, binding, [ID_4]), False)
    finally:
        cleanup(project)
    for label, verdicts, owed in (("K5: approved", ("approved", "unverified"), ()),
                                  ("K6: rejected beside a WINDOW-level gap (a quality check owed)",
                                   ("rejected", "unverified"), (42,)),
                                  ("K6b: rejected beside a gap of another instance", ("rejected", None), ())):
        project = temp_project("qa-blocked-e5b2-")
        use_project(project)
        StandIn.required_checks = owed
        try:
            task = cmp2_story(project, cmp2_manifest(verdicts=verdicts))
            code, out = cli(review_receipt=True)
            if owed:
                check("K6: the window-level gap is really there", any(line.startswith("quality:") for line in problem_lines(out)), out)
            check_eq(label + ": exit 1", code, 1)
            check_not_in(label + ": no send-back line", "sent back to its author", out)
            check(label + ": no receipt is written", not (task / "work/review-receipts").exists())
        finally:
            StandIn.required_checks = ()
            cleanup(project)


def main() -> None:
    e5b_a_rejected_blocked_instance_is_receipted_and_sent_back()
    k1_the_cmp2_window_closes_in_one_record()
    o3_the_red_that_ran_is_marked()
    o5_a_red_needs_its_detail()
    o1_the_instance_a_later_row_no_longer_names()
    c15_the_variants()
    the_reader_and_its_error_direction()
    e3_a_passed_run_beside_the_row_and_c9_the_bytes()
    b3_validate_window_rederives_from_the_manifest()
    e10_the_limit_at_and_beyond()
    b5_story_step_derives_the_pair()
    b8_a_green_entry_takes_its_blocked_row_with_it()
    b7_the_precheck()
    e6_the_controller_still_refuses_an_empty_scope()
    k2_and_b6_the_story_closes_on_one_record()
    k3_a_mixed_window()
    k18_h6_a_later_green_unblocks_the_case()
    finish("blocked_by_env window")


if __name__ == "__main__":
    main()
