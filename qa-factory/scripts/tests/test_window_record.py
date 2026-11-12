#!/usr/bin/env python3
"""The S5 window acceptance record is written by code, from what is already on disk.

TP2-2553: `acceptance.validate_window` demanded `scope_instances`, per-instance
hashes, fingerprints, obligations, dispositions, evidence, a review and a probe — and no
script wrote any of it. The orchestrator learned the shape one refusal at a time, two waivers
were spent and the critic's last interval ran close to two hours.

Here a story reaches S5 with a manifest of two instances, run blocks and a sensitivity
receipt. `window_record.py` builds the record, it passes `contract.window_shape_errors` and
`acceptance.validate_window` untouched, and `controller.py accept --window` takes it. With
the run block gone the printed verdict names the instance, the missing field and the command
that produces it — all of them at once, never one per refusal.

t-108 (B-194): the window also lists the tests that changed between a red run and the next green
run (`expectation_changes`), and is not clean while one of them has no good critic verdict. Those
checks are in two groups: `pure` (no story, seconds - the copy from the detector, the gaps, the
words) and the rest (a story at S5, minutes). `test_window_record.py pure` runs the first group only.
"""
import collections
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, driver_sources, finish,  # noqa: E402
                     run_script, s5_apply, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import handoff  # noqa: E402
import s5_precheck  # noqa: E402
import window_record as WR  # noqa: E402
import tempfile  # noqa: E402

# HF4-10: a quality check is demanded only when a factory script produces its receipt (`references/quality-receipt-producers.json`,
# empty today). The `lint` windows below test the gap machinery of a DEMANDED check, so they run against a data file that
# names a producer for `lint`; what the shipped (empty) file does is `test_quality_demand.py`'s.
_PRODUCERS = Path(tempfile.mkdtemp(prefix="qa-wr-producers-")) / "producers.json"
_PRODUCERS.write_text(json.dumps({"schema_version": 1, "producers": {"lint": "lint.py"}, "why": {}}), encoding="utf-8")
WR.QUALITY_PRODUCERS_FILE = _PRODUCERS
from acceptance import change_word, expectation_change_gaps, validate_window  # noqa: E402
import controller as CONTROLLER  # noqa: E402  (the stand-in controller of the pure `build` tests)
from controller import Controller  # noqa: E402
from event_store import content_hash  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework_scope as SCOPED  # noqa: E402
import test_s5_precheck as TP  # noqa: E402  (piece B's fixtures for the detector's real shapes)

TICKET = "QA-WINDOW-1"
AUTHOR = "S5-qa-automator-1"
CRITIC = "S5-qa-code-critic-1"
PROBE_REF = "work/sensitivity-receipts/probe-test-a.json"

# The instances' tests are REAL files under the project: the window reads an instance's current
# bytes from the file (the one reader, t-016 Amendment 2), the raw sha256 manifest_from_tests.py
# binds. SHAS holds them per case once `a_story_at_s5` wrote the files.
SHAS: dict = {}
TEST_SRC = "def {name}():\n    total = 1 + 2\n    assert total == 3, 'coupon limit not enforced'\n"


def test_file(project: Path, case: str, name: str, extra: str = "") -> str:
    path = project / f"tests/test_{case.lower()}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEST_SRC.format(name=name) + extra, encoding="utf-8")
    SHAS[case] = digest(path)
    return SHAS[case]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def obligation_hashes(task: Path) -> dict:
    document = json.loads((task / "work/test-plan.json").read_text(encoding="utf-8"))
    rows = document["rows"] if isinstance(document, dict) else document
    return {str(row["id"]): {str(ob["obligation_id"]): content_hash(ob)
                             for ob in row.get("coverage_obligations") or []}
            for row in rows}


def test_row(instance, case, row_id, sha, disposition, hashes):
    obligation = f"OB-{row_id}"
    return {"instance_id": instance, "covers": [case], "file": f"tests/test_{case.lower()}.py",
            "case_version_links": [{"case_id": case, "version": "cv_" + case.lower()}],
            "trace_binding": {"selector": f"tests/test_{case.lower()}.py::{instance}",
                              "assertion_refs": [f"tests/test_{case.lower()}.py:12"],
                              "test_content_sha": sha},
            "obligation_refs": [{"obligation_id": obligation,
                                 "obligation_hash": hashes[row_id][obligation]}],
            "assertion_id": f"tests/test_{case.lower()}.py:12",
            "defect_location": f"src/{case.lower()}.py:40",
            "change_disposition": disposition,
            "change_basis_ref": "manifest:" + case,
            "status": "green", "critic_verdict": "approved"}


def run_block(task: Path, name, instance, fingerprint, sha):
    write(task / "work/run-blocks" / name, {
        "schema_version": 2, "block_id": name, "attempt_id": name, "dispatch_id": AUTHOR,
        "input_fingerprint": fingerprint, "source_fingerprint": {"test_content_sha": sha},
        "execution_status": "passed", "purpose": "initial",
        "results": [{"instance_id": instance, "status": "passed", "attempt_id": name,
                     "input_fingerprint": fingerprint,
                     "source_fingerprint": {"test_content_sha": sha}}],
        "evidence": [{"summary": "", "reporter": "none", "report_path": "", "report_sha256": ""}]})


def a_story_at_s5(project: Path, expected: str = "coupon limit not enforced",
                  actual: str = "AssertionError:  coupon limit not enforced") -> tuple:
    """A task through gate A with two automate cases, a manifest, run blocks and a probe.
    `expected` / `actual` are the two spellings of the probe's reason in its receipt."""
    task = project / "qa-factory" / "artifacts" / TICKET
    task.mkdir(parents=True)
    controller = Controller(task)
    controller.apply("initialize", {"scope": ["TC-1", "TC-2"], "source_revision": "src-1",
                                    "known_paths": {"root": str(project)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(controller, task, f"S{number}")
    BASE.seed_plan(task, [SCOPED.plan_row(1, "automate"), SCOPED.plan_row(2, "automate")])
    write(task / "state/story-case-links.json",
          {"links": [{"case_id": "TC-1", "version": "cv_tc-1"},
                     {"case_id": "TC-2", "version": "cv_tc-2"}]})
    controller.apply("decision", BASE.bind_gate_a(task, {
        "id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
        "authorization_source": "human", "source_revision": "src-1", "scope": ["TC-1", "TC-2"],
        "input_revision": "src-1", "idempotency_key": "gate-a"}))

    hashes = obligation_hashes(task)
    sha_a, sha_b = test_file(project, "TC-1", "test_a"), test_file(project, "TC-2", "test_b")
    write(task / "work/automation-manifest.json", {
        "schema_version": 2,
        "tests": [test_row("test_a[x]", "TC-1", "TS-1", sha_a, "new_or_changed", hashes),
                  test_row("test_b[y]", "TC-2", "TS-2", sha_b, "unchanged", hashes)],
        "obligation_bindings": [
            {"obligation_id": "OB-TS-1", "obligation_hash": hashes["TS-1"]["OB-TS-1"],
             "instance_ids": ["test_a[x]"], "sensitivity": "proven",
             "probe_receipt_ref": PROBE_REF, "design_assessment": "sufficient",
             "code_validity": "valid", "change_disposition": "new_or_changed",
             "change_basis_ref": "manifest:TC-1"},
            {"obligation_id": "OB-TS-2", "obligation_hash": hashes["TS-2"]["OB-TS-2"],
             "instance_ids": ["test_b[y]"], "sensitivity": "not_required",
             "design_assessment": "sufficient", "code_validity": "valid",
             "change_disposition": "unchanged", "change_basis_ref": "manifest:TC-2"}]})
    # A run block's source_fingerprint.test_content_sha is the run's fingerprint over test and
    # helper files - another quantity than the raw file hash, as it is in every real block.
    run_block(task, "20260924T090000000000Z-b1.json", "test_a[x]", "fp-a", "fingerprint-a")
    run_block(task, "20260924T090100000000Z-b2.json", "test_b[y]", "fp-b", "fingerprint-b")
    # The red probe's own immutable receipt, exactly as `red_sandbox.write_sensitivity_receipts`
    # leaves it: the reason is spelled with pytest's prefix in one field and without it in the
    # other, which is the difference that made TP1-15045 prepare a second sandbox.
    proof = {"instance_id": "test_a[x]", "case_version": "cv_tc-1", "test_content_hash": sha_a,
             "source_revision": "src-1", "build_id": "runtime-1", "mutation": "real_behavior",
             "expected_assertion_failure": expected,
             "actual_failure": actual,
             "assertion_location": "tests/test_tc-1.py:12", "failure_kind": "assertion",
             "restoration_evidence": "red_sandbox --verify-receipt: 12 hashes unchanged",
             "immutable": True}
    proof["receipt_hash"] = content_hash(proof)
    write(task / PROBE_REF, proof)
    # A stale sibling binding may be present for the same consolidated instance. It must
    # never eclipse the instance's declared obligation or its canonical receipt reference.
    write(task / "work/sensitivity-receipts/stale-sibling.json", {"kind": "green-run"})
    manifest_path = task / "work/automation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["obligation_bindings"].insert(0, {
        "obligation_id": "OB-STALE-SIBLING", "instance_ids": ["test_a[x]"],
        "sensitivity": "proven", "probe_receipt_ref": "work/sensitivity-receipts/stale-sibling.json",
        "review_receipt_ref": "work/review-receipts/prior.json"})
    write(manifest_path, manifest)

    for role, identity, key in (("qa-automator", AUTHOR, "auth"), ("qa-code-critic", CRITIC, "crit")):
        s5_apply(controller, {"id": identity, "stage": "S5", "role": role,
                                      "scope": ["TC-1", "TC-2"], "input_hash": "s5-h", "budget": {},
                                      "known_paths": {}, "idempotency_key": "d-" + key})
        if role == "qa-automator":
            evidence = task / "work/author-green.txt"
            evidence.write_text("author green", encoding="utf-8")
            controller.apply("accept", {"id": identity, "status": "accepted", "stage_complete": False,
                                        "evidence_refs": [{"path": "work/author-green.txt",
                                                           "sha256": digest(evidence)}],
                                        "idempotency_key": "a-" + key})
    return task, controller


def the_record_is_built_and_accepted():
    project = temp_project("qa-window-record-")
    use_project(project)
    try:
        task, controller = a_story_at_s5(project)
        result = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC,
                            "--review-receipt", cwd=project)
        check("a complete window is built without a question", result.returncode == 0,
              result.stdout + result.stderr)
        check_in("and says where it put the record", "work/windows/" + CRITIC + ".json", result.stdout)
        check_in("with the command that accepts it", "--operation accept", result.stdout)

        record = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        check_eq("the record has no structural gap", C.window_shape_errors(record), [])
        check_eq("and no semantic one", validate_window(record, task), [])
        check_eq("the record carries the list of changes after a red run, empty: nothing changed",
                 record.get("expectation_changes"), [])
        check_eq("the author is the accepted automator of the same window",
                 record["author_dispatch_id"], AUTHOR)
        check_eq("every case of the scope maps to its instances", record["scope_instances"],
                 {"TC-1": ["test_a[x]"], "TC-2": ["test_b[y]"]})
        probe = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")["probe"]
        check_eq("the probe reason is read past pytest's prefix",
                 (probe["expected_reason"], probe["actual_reason"]),
                 ("coupon limit not enforced", "coupon limit not enforced"))
        check_eq("and it points at the receipt inside the instance's evidence",
                 probe["evidence_ref"], PROBE_REF)

        receipt = task / "work/review-receipts" / (CRITIC + ".json")
        check("the immutable S5 review receipt is written", receipt.is_file())
        manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("and its path is published on every binding the window reaches",
                 sorted({b.get("review_receipt_ref") for b in manifest["obligation_bindings"]
                         if b.get("obligation_id") != "OB-STALE-SIBLING"}),
                 ["work/review-receipts/" + CRITIC + ".json"])

        findings = task / "work/test-code/critic-findings.md"
        findings.parent.mkdir(parents=True, exist_ok=True)
        findings.write_text("# findings\n\nnone blocking\n", encoding="utf-8")
        completion = task / "work/completion.json"
        completion.write_text(json.dumps({
            "id": CRITIC, "status": "accepted", "stage_complete": True,
            "evidence_refs": [{"path": "work/test-code/critic-findings.md", "sha256": digest(findings)}],
            "idempotency_key": "a-critic"}), encoding="utf-8")
        accept = run_script("controller.py", "--task-root", task, "--operation", "accept",
                            "--input", completion, "--window",
                            task / "work/windows" / (CRITIC + ".json"), cwd=project)
        check("the controller accepts the record from the file", accept.returncode == 0,
              accept.stdout + accept.stderr)
        check_eq("no role typed a line of it",
                 Controller(task).state()["dispatches"][CRITIC]["status"], "accepted")
        check_eq("and the critic's acceptance closed S5",
                 Controller(task).state()["stages"]["S5"]["status"], "completed")
    finally:
        cleanup(project)


def a_second_review_receipt_writes_nothing():
    """C2-4 T19 (the measurement behind edge 11): the driver's receipt door may run again - the receipt file is
    kept ('copy') and `manifest_put` on the same fragment leaves the manifest byte for byte. A rewrite here would
    make the door 'write' on every pass and the once-per-key bound the only brake."""
    project = temp_project("qa-window-twice-")
    use_project(project)
    try:
        task, _controller = a_story_at_s5(project)
        receipt = task / "work/review-receipts" / (CRITIC + ".json")
        manifest = task / "work/automation-manifest.json"

        def sha(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        first = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        check_eq("T19: the first receipt is written", (first.returncode, receipt.is_file()), (0, True))
        before = (sha(receipt), sha(manifest))
        second = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        check_eq("T19: the second run exits 0", second.returncode, 0)
        check_eq("T19: and neither the receipt nor the manifest changed by a byte", (sha(receipt), sha(manifest)), before)
    finally:
        cleanup(project)


def a_stale_projection_is_not_a_refused_receipt():
    """t-1253 F-3: `manifest_put.py` exits 4 when the receipt IS in the journal and only the manifest's projection
    failed. The publish line names the replay and never says "refused"; exit 3 (nothing committed) still does."""
    import subprocess
    from unittest.mock import patch

    def exits(code: int, said: str):
        return lambda command, **_kw: subprocess.CompletedProcess(command, code, "", said)
    window, ref = {"instances": [{"obligation_ids": ["OB-1"]}]}, {"path": "work/review-receipts/x.json"}
    with patch.object(WR.subprocess, "run", exits(4, "manifest_put: event committed; projection stale - the fragment "
                                                     "is in the journal, do not send it again")):
        stale = WR.publish_review_receipt(Path("."), TICKET, window, ref)
    with patch.object(WR.subprocess, "run", exits(3, "manifest_put: nothing was committed (the journal is unchanged)")):
        refused = WR.publish_review_receipt(Path("."), TICKET, window, ref)
    with patch.object(WR.subprocess, "run", exits(0, "automation-manifest.json: revision 2, receipt abc")):
        done = WR.publish_review_receipt(Path("."), TICKET, window, ref)
    check_in("t-1253 F-3: exit 4 names the replay as the move", f"`manifest_put.py --task {TICKET} --recover`", stale)
    check("t-1253 F-3: and does not call a committed receipt refused or unwritten",
          "refused" not in stale and "not written" not in stale, stale)
    check_in("t-1253 F-3: CONTROL - exit 3 is still the refusal", "manifest_put.py refused the review receipt", refused)
    check_eq("t-1253 F-3: CONTROL - exit 0 is the receipt line", done, "manifest_put.py: automation-manifest.json: revision 2, receipt abc")


def a_missing_run_block_is_named_with_its_command():
    project = temp_project("qa-window-gap-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        for block in (task / "work/run-blocks").glob("*.json"):
            block.unlink()
        result = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, cwd=project)
        check_eq("a window that cannot be green refuses", result.returncode, 1)
        check_in("naming the instance", "test_a[x]", result.stdout)
        check_in("and the field it has no value for", "execution_fingerprint is missing",
                 result.stdout)
        check_in("with the artifact the value comes from", "work/run-blocks/", result.stdout)
        check_in("and the command that writes it", "run_suite.py --mine", result.stdout)
        check_in("the second instance is named in the same verdict", "test_b[y]", result.stdout)
        check("every gap is printed at once, never one per refusal",
              result.stdout.count("execution_fingerprint is missing") >= 2, result.stdout)
        # Every line of it names the artifact its gap came from, so the work is a role's own.
        # P4b: a refusal that says as much in prose still reached the person, because the driver
        # routes on this marker. (Until t-299 `waiver.py` stood here as a promise that a person's word
        # passes the window; no reader of a window gap reads one, so the promise is gone, Q7 B'.)
        import story_run
        from role_cli import REPAIR_MARKER
        check_in("the refusal says it is not the person's to answer", REPAIR_MARKER, result.stdout)
        check_eq("and the driver hands it back to the role",
                 (story_run.match_known(result.stdout) or ("", "<no match>"))[1], "resume_repair")
        # t-299 (Q7 B'): the blanket promise is gone; this window has no gap a recorded word passes, and the line
        # that replaced the promise says where to look (the test of it: a_word_nothing_reads_is_printed_...)
        check_in("and the closing line points at the gap lines for the way a person's word passes one",
                 "Where a person's word passes a gap, the line above says how.", result.stdout)
        check_not_in("without promising a word that nothing reads", "A person's word still passes", result.stdout)
    finally:
        cleanup(project)


# --- the levels (D-0010): which receipt the window reads, and what it says about it -------------------

LIVE_REF = "work/sensitivity-receipts/test_a-live-0123456789abcdef.json"


def without_freshness(lines: list) -> list:
    """`lines` minus the HF2-11 note `run freshness not measured: <why>`: the run blocks of these stories carry no
    per-test shas, so every instance gets one, and the keys that use this helper are about the OTHER notes
    (`the_item_carries_the_identity_the_run_recorded` and `test_run_freshness.py` are about that one)."""
    return [line for line in lines if "run freshness not measured" not in line]


def live_body(**over) -> dict:
    """The receipt `probe_by_code.py` writes: level live, an assertion mutation, no window_probe."""
    body = {"instance_id": "test_a[x]", "case_version": "cv_tc-1", "test_content_hash": SHAS["TC-1"],
            "source_revision": "src-1", "build_id": "runtime-1", "mutation": "invert",
            "expected_assertion_failure": "probe-test_a invert: total == 3",
            "actual_failure": "probe-test_a invert: total == 3",
            "assertion_location": "tests/test_tc-1.py:12", "failure_kind": "assertion",
            "restoration_evidence": "probe_by_code: tests/test_tc-1.py sha256 abc verified restored",
            "proof_level": "live", "probe_tool": "probe_by_code.py", "mutation_kind": "assertion",
            "immutable": True}
    body.update(over)
    body["receipt_hash"] = content_hash({k: v for k, v in body.items() if k != "receipt_hash"})
    return body


def rewire(task: Path, *, row=None, binding=PROBE_REF) -> None:
    """Point test_a's receipt at `row` (tests[].sensitivity_proof.receipt_ref) and/or `binding`."""
    path = task / "work/automation-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for test in manifest["tests"]:
        if test["instance_id"] == "test_a[x]":
            test.pop("sensitivity_proof", None)
            if row:
                test["sensitivity_proof"] = {"receipt_ref": {"path": row, "sha256": digest(task / row)}}
    for item in manifest["obligation_bindings"]:
        if item["obligation_id"] == "OB-TS-1":
            item.pop("probe_receipt_ref", None)
            if binding:
                item["probe_receipt_ref"] = binding
                item["sensitivity"] = "proven"
            else:
                item["sensitivity"] = "not_required"
    write(path, manifest)


def window_of(project: Path, task: Path) -> tuple:
    result = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, cwd=project)
    record = task / "work/windows" / (CRITIC + ".json")
    return result, (json.loads(record.read_text(encoding="utf-8")) if record.is_file() else {})


def a_live_receipt_on_the_row_reaches_the_window():
    project = temp_project("qa-window-live-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        write(task / LIVE_REF, live_body())
        rewire(task, row=LIVE_REF, binding=None)
        result, record = window_of(project, task)
        check("a window whose only receipt is the row's live one is acceptable", result.returncode == 0,
              result.stdout + result.stderr)
        probe = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")["probe"]
        check_eq("the probe is the live level, with the assertion mutation the receipt names",
                 (probe["proof_level"], probe["mutation_kind"]), ("live", "assertion"))
        check_eq("its evidence is the receipt, which is inside the instance's evidence",
                 (probe["evidence_ref"], probe["evidence_ref"] in
                  [e["path"] for e in next(i for i in record["instances"]
                                           if i["instance_id"] == "test_a[x]")["evidence_refs"]]), (LIVE_REF, True))
        check_eq("and validate_window has no gap over it", validate_window(record, task), [])
        # the row first, the binding as the fallback: both name a receipt, the row's wins
        rewire(task, row=LIVE_REF, binding=PROBE_REF)
        _, both = window_of(project, task)
        probe = next(i for i in both["instances"] if i["instance_id"] == "test_a[x]")["probe"]
        check_eq("when the row and the binding name receipts, the window reads what reached() picks: the best",
                 (probe["proof_level"], probe["evidence_ref"]), ("catches_broken_product", PROBE_REF))
        rewire(task, row=None, binding=PROBE_REF)
        _, fallback = window_of(project, task)
        probe = next(i for i in fallback["instances"] if i["instance_id"] == "test_a[x]")["probe"]
        check_eq("and the binding is the fallback (an old red_sandbox receipt: catches a broken product)",
                 (probe["proof_level"], probe["mutation_kind"]), ("catches_broken_product", "real_behavior"))
    finally:
        cleanup(project)


def a_receipt_for_other_bytes_is_not_the_windows_probe():
    """BYTES RULE (critic t-030): the row binds bytes 2 and holds a receipt of the HIGHER level for
    bytes 1. The window must not pick it (it would bind a probe of other bytes); once the live probe of
    bytes 2 is the row's receipt, the window binds it. The door of the gap is always answerable."""
    project = temp_project("qa-window-bytes-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        # PROBE_REF is a product receipt for the first bytes; the test changes and the author
        # rebinds the row to the new bytes.
        old_sha = SHAS["TC-1"]
        new_sha = test_file(project, "TC-1", "test_a", extra="# edited\n")
        path = task / "work/automation-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for test in manifest["tests"]:
            if test["instance_id"] == "test_a[x]":
                test["trace_binding"]["test_content_sha"] = new_sha
        write(path, manifest)
        run_block(task, "20260924T090500000000Z-b3.json", "test_a[x]", "fp-a2", "fingerprint-a2")
        result, record = window_of(project, task)
        item = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")
        check_eq("the instance's bytes are the file's raw sha256 now", item["input_hash"], new_sha)
        check_eq("a receipt for other bytes is not chosen: the window has no probe for it", "probe" in item, False)
        check_eq("so the window is not acceptable and says why", result.returncode, 1)
        check_in("the gap names the door that can answer it: the live probe", "probe_by_code.py --task", result.stdout)
        write(task / LIVE_REF, live_body(test_content_hash=new_sha))
        rewire(task, row=LIVE_REF, binding=PROBE_REF)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        result, record = window_of(project, task)
        item = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")
        check_eq("with the live receipt of the new bytes the window binds it (not the higher one for old bytes)",
                 (item["probe"]["proof_level"], item["probe"]["evidence_ref"], item["probe"]["input_hash"]),
                 ("live", LIVE_REF, new_sha))
        check_eq("and validate_window has no gap over it", validate_window(record, task), [])
        # Amendment 2: a row that binds NO bytes is not lenient - the file is read, and a receipt for
        # the old bytes of a changed test is not the window's probe (the t-030 trap without a binding).
        write(task / LIVE_REF, live_body(test_content_hash=old_sha))
        rewire(task, row=LIVE_REF, binding=None)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for test in manifest["tests"]:
            if test["instance_id"] == "test_a[x]":
                test.pop("trace_binding")
        write(path, manifest)
        result, record = window_of(project, task)
        item = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")
        check_eq("no trace_binding: the instance's bytes are still read from the file", item["input_hash"], new_sha)
        check_eq("no trace_binding: a receipt for the old bytes is not chosen", "probe" in item, False)
        check_eq("no trace_binding: the window is not acceptable", result.returncode, 1)
        # the test file is gone: its bytes are unknown - the instance carries no input_hash and the
        # verdict says which file could not be found
        (project / "tests/test_tc-1.py").unlink()
        result, record = window_of(project, task)
        item = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")
        check_eq("a test file that is gone: no bytes are invented", "input_hash" in item, False)
        check_eq("...and no receipt is vouched for as the probe of bytes nobody can read", "probe" in item, False)
        check_in("...and the verdict names why", "test_a[x]: input_hash is missing", result.stdout)
        check_in("...and where the value comes from", "cannot be found under the project", result.stdout)
    finally:
        cleanup(project)


def an_old_mutable_probe_record_counts_as_live_in_the_window():
    """Edge row 2: `work/probes/<IID>.json` written before receipts, reached through a binding. Its
    `window_probe` says `real_behavior` and carries no level; the window reads it as the live check."""
    project = temp_project("qa-window-legacy-live-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        # The old record's prepared `input_hash` is the run's fingerprint; the same record measured
        # the raw test file too (`test_file_sha256`), and the window compares raw with raw.
        old = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_a[x]",
               "verdict": "intended_failure", "mutation": "invert", "mutation_kind": "real_behavior",
               "test_file_sha256": SHAS["TC-1"],
               "window_probe": {"verdict": "intended_failure", "input_hash": "fingerprint-a",
                                "expected_location": "tests/test_tc-1.py:12",
                                "actual_location": "tests/test_tc-1.py:12", "expected_reason": "probe: r",
                                "actual_reason": "probe: r", "failure_kind": "assertion",
                                "mutation_kind": "real_behavior",
                                "evidence_ref": "evidence/runs/job1/red_probe.json"}}
        write(task / PROBE_REF, old)
        result, record = window_of(project, task)
        check("a window over an old probe record is acceptable", result.returncode == 0, result.stdout + result.stderr)
        probe = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")["probe"]
        check_eq("its level is the live check, by the receipt's own tool", probe["proof_level"], "live")
        check_eq("its bytes are the raw file it measured, not the run's fingerprint", probe["input_hash"], SHAS["TC-1"])
        check_eq("its evidence is repointed at the receipt (the run summary is not among the instance's evidence)",
                 probe["evidence_ref"], PROBE_REF)
        check_eq("no gap", validate_window(record, task), [])
        # a record so old it measured no raw bytes: its fingerprint is never compared with the raw
        # hash as if it were one - the probe is not bound to these bytes, and the door is a new probe
        write(task / PROBE_REF, {k: v for k, v in old.items() if k != "test_file_sha256"})
        result, record = window_of(project, task)
        check_in("a record with only a fingerprint: the probe is not bound to the bytes", "sensitivity:test_a[x]",
                 result.stdout)
        check_in("...and the door is the live probe", "probe_by_code.py --task", result.stdout)
        check_in("...and the line says which bytes differ (FR-41)",
                 f"(the probe is bound to sha256 fingerprint-a, the test now holds {SHAS['TC-1']}, and its "
                 "code differs or was not measured: a probe of the current bytes is due)", result.stdout)
        check_not_in("...and no text says the window binds raw bytes until a later change (t-043 C)",
                     "until t-043 C", result.stdout)
    finally:
        cleanup(project)


def an_unknown_level_and_a_false_claim_are_named_with_their_doors():
    project = temp_project("qa-window-levels-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        write(task / LIVE_REF, live_body(proof_level="mystery"))
        rewire(task, row=LIVE_REF, binding=None)
        result, record = window_of(project, task)
        check_eq("a receipt of a level nobody knows does not make an acceptable window", result.returncode, 1)
        check_in("the gap is named", "probe_level:test_a[x]", result.stdout)
        check_in("with what it is", "does not know", result.stdout)
        write(task / LIVE_REF, live_body(proof_level="catches_broken_product"))
        rewire(task, row=LIVE_REF, binding=None)
        result, _ = window_of(project, task)
        check_eq("a receipt that claims to catch a broken product with an assertion mutation is refused",
                 result.returncode, 1)
        check_in("the gap is the mutation kind", "probe_mutation_kind:test_a[x]", result.stdout)
        check_in("and says what it proves instead, and whose receipt that is",
                 "an assertion mutation proves the check is live", result.stdout)
        check_in("naming probe_by_code.py", "probe_by_code.py's receipt", result.stdout)
        # no receipt at all: the door named is the live probe, with the dispatch and the node
        rewire(task, row=None, binding=None)
        result, _ = window_of(project, task)
        check_eq("a new or changed test with no receipt anywhere is refused", result.returncode, 1)
        check_in("the door is probe_by_code.py", 'probe_by_code.py --task <T> --dispatch <critic id> --test "<node>" --instance <IID>',
                 result.stdout)
        check_in("and says it is for every new or changed test", "every new or changed test", result.stdout)
    finally:
        cleanup(project)


def the_vocabulary_missing_is_said_not_guessed():
    import proof_level
    project = temp_project("qa-window-nolevels-")
    use_project(project)
    real = proof_level.LEVELS_FILE
    try:
        task, _ = a_story_at_s5(project)
        write(task / LIVE_REF, live_body())
        rewire(task, row=LIVE_REF, binding=None)
        window, notes = WR.build(task, CRITIC)
        proof_level.LEVELS_FILE = project / "nowhere.json"
        proof_level._reset()
        lines = WR.verdict(task, window, notes)
        check_in("with the vocabulary missing the verdict names the file and the door",
                 "reinstall the plugin", "\n".join(lines))
        check_in("...and is not the 'explicit list' message of a shape error", "verification-levels.json",
                 "\n".join(lines))
    finally:
        proof_level.LEVELS_FILE = real
        proof_level._reset()
        cleanup(project)


def per_test_fields_are_copied_from_the_receipt_or_left_out():
    """t-043 C (D1, D2, D4): the item carries the raw sha and the code sha of ONE read of the test file; a review
    carries what its receipt recorded and nothing when there is no receipt (never a code sha or identity it did
    not record); a probe carries what its receipt says; a proof that holds over a comment-only change is a NOTE,
    not a problem, and `verdict`'s return - the problem lines - is what it was."""
    import proof_level
    project = temp_project("qa-window-perinst-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        window, notes = WR.build(task, CRITIC)
        item = next(i for i in window["instances"] if i["instance_id"] == "test_a[x]")
        data = (project / "tests/test_tc-1.py").read_bytes()
        check_eq("the item's raw and code shas come from one read of the file",
                 (item["input_hash"], item["test_code_sha"]), (SHAS["TC-1"], proof_level.code_sha(data, "test_tc-1.py")))
        check_eq("no run of the story selected the test: no identity, and no measurement failed to say so",
                 ("instance_identity" in item, "instance_identity_why" in item), (False, False))
        check_eq("a review with NO receipt: the claimed raw bytes, and no code sha or identity (edge 11)",
                 item["review"], {"verdict": "approved", "input_hash": SHAS["TC-1"]})
        check_eq("a probe from a receipt that recorded no code sha carries none",
                 "test_code_sha" in item["probe"], False)
        result = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        check("the window is receipted", result.returncode == 0, result.stdout + result.stderr)
        window, notes = WR.build(task, CRITIC)
        item = next(i for i in window["instances"] if i["instance_id"] == "test_a[x]")
        check_eq("a review WITH a receipt: copied from it - the raw sha and the code sha it recorded",
                 item["review"], {"verdict": "approved", "input_hash": SHAS["TC-1"],
                                  "test_code_sha": proof_level.code_sha(data, "test_tc-1.py")})
        # the receipt of a live probe records its code sha (and identity): the window's probe copies them
        write(task / LIVE_REF, live_body(test_code_sha="code-of-the-bytes", instance_identity={
            "instance_content_sha": "c", "instance_code_sha": "k", "job_id": "j"}))
        rewire(task, row=LIVE_REF, binding=None)
        window, notes = WR.build(task, CRITIC)
        probe = next(i for i in window["instances"] if i["instance_id"] == "test_a[x]")["probe"]
        check_eq("a probe copies test_code_sha and instance_identity from its receipt, input_hash stays the receipt's",
                 (probe["test_code_sha"], probe["instance_identity"]["instance_code_sha"], probe["input_hash"]),
                 ("code-of-the-bytes", "k", SHAS["TC-1"]))
        # a comment appended to the test AFTER the review: the review holds by the file's code - a note, not a problem
        rewire(task, row=None, binding=PROBE_REF)
        test_file(project, "TC-1", "test_a", extra="# edited after the review\n")
        window, notes = WR.build(task, CRITIC)
        info: list = []
        problems = WR.verdict(task, window, notes, info)
        check_eq("the review holds over a comment-only change and says so, as a note",
                 without_freshness(info), [f"test_a[x]: the review holds; {proof_level.comment_only_words()}"])
        check_eq("verdict's problem lines are the same with and without `info`", WR.verdict(task, window, notes), problems)
        check("...and the note is not among them", not [p for p in problems if "comment-only" in p], str(problems))
        check("...(the pre-C receipt of the probe binds raw bytes: its own gap stays)", any(
            p.startswith("sensitivity:test_a[x]") or "probe is missing" in p for p in problems), str(problems))
    finally:
        cleanup(project)


def window_for_reasons(label: str, expected: str, actual: str) -> tuple:
    """(exit code, stdout, the probe block of the first instance, validate_window gaps) of a window
    built over a receipt that holds exactly these two spellings of the probe's reason."""
    project = temp_project("qa-window-reason-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project, expected, actual)
        result = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, cwd=project)
        record = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        probe = next(i for i in record["instances"] if i["instance_id"] == "test_a[x]")["probe"]
        return result.returncode, result.stdout + result.stderr, probe, validate_window(record, task)
    finally:
        cleanup(project)


def a_trx_headline_receipt_is_accepted():
    """A .NET assertion reads `Assert.Equal() Failure` over `Expected:` / `Actual:` lines the author
    never pinned. The producer (`red_sandbox.reason_matches`) accepted the probe on the headline, so
    the window - built from the receipt - must read the same reason on both sides, or the window
    refuses a proof the sandbox already accepted. This ADDS to the pytest-prefix receipt above."""
    code, out, probe, gaps = window_for_reasons(
        "headline", "Assert.Equal() Failure",
        "Assert.Equal() Failure\nExpected: 4\nActual:   0")
    check("a TRX receipt whose actual reason carries the reporter's detail is accepted", code == 0, out)
    check_eq("both sides of the window's probe read the headline",
             (probe["expected_reason"], probe["actual_reason"]),
             ("Assert.Equal() Failure", "Assert.Equal() Failure"))
    check_eq("and the semantic check has no gap", gaps, [])
    code, out, probe, gaps = window_for_reasons(
        "other", "Assert.IsType() Failure", "Assert.Equal() Failure\nExpected: 4\nActual:   0")
    check("a different headline is a different assertion: the window refuses", code == 1, out)
    check("naming the sensitivity gap", any(g.startswith("sensitivity") for g in gaps), str(gaps))
    check("and the two reasons stay different", probe["expected_reason"] != probe["actual_reason"],
          str(probe))


def an_old_receipt_with_a_whole_text_match_is_still_accepted():
    """Stories in flight hold receipts written before the shared rule: the whole text on both
    sides, differently spelled (prefix, line breaks, runs of spaces). They keep passing."""
    whole = "Expected the cart\ntotal to be 4"
    code, out, probe, gaps = window_for_reasons("whole", whole, "AssertionError:  Expected the   cart total\nto be 4")
    check("an old receipt whose whole reason matched after folding is accepted", code == 0, out)
    check_eq("and the folded reason is the same on both sides",
             (probe["expected_reason"], probe["actual_reason"]),
             ("Expected the cart total to be 4", "Expected the cart total to be 4"))
    check_eq("with no semantic gap", gaps, [])
    code, out, probe, gaps = window_for_reasons("empty", "", "AssertionError: boom")
    check("an empty expected reason is still no proof", code == 1 and any(g.startswith("sensitivity") for g in gaps),
          out)


# --- t-108 (B-194): a test changed between its red run and the next green run is never a silent pass ---
#
# `window_record.build` copies the OWED pairs of the scope from the one detector into the window as
# `expectation_changes`; `acceptance.validate_window` reads that list and stays pure. The detector's own
# shapes are piece B's (`test_s5_precheck.py`): its fixtures are imported here, not copied.

WORDS = handoff.vocabulary()["expectation_change_words"]
ALLOWED = ", ".join(handoff.allowed("expectation_change_verdicts"))
UNRESOLVED_REASON = "the person read the change and lets it stand"


def word(name: str, function: str) -> str:
    """The vocabulary's gap sentence for `function` - the test reads the same data the code reads."""
    return WORDS[name].format(function=function)


def entry(function="m.f", red="r1", green="g1", verdict=None, by_word=None) -> dict:
    """One line of a window's `expectation_changes`; `by_word` adds the key `passed_by_word` with that value
    (a pair a person's word did not pass has no such key)."""
    line = {"function": function, "red_attempt": red, "green_attempt": green, "critic_verdict": verdict}
    if by_word is not None:
        line["passed_by_word"] = by_word
    return line


def canned(function, red, green, *, owed=True, verdict=None, record=True, by_word=False) -> dict:
    """A pair as the detector returns it (`s5_precheck.expectation_changes`), with its joined record."""
    joined = {"function": function, "red_attempt": red, "green_attempt": green, "then_refs": [],
              "critic_verdict": verdict} if record else None
    return {"function": function, "red_attempt": red, "green_attempt": green, "owed": owed,
            "orphan": green is None, "record": joined, "passed_by_word": by_word, "cases": ["TC-1"]}


def canned_words(_task_root, changes, _cases) -> list:
    """Stands in for `s5_precheck.word_passed_pairs`: the canned pairs carry their own `passed_by_word`
    (the real helper needs a full pair and a pipeline.json; it is tested against the real detector)."""
    return [p for p in changes.get("pairs") or [] if isinstance(p, dict) and p.get("passed_by_word")]


class Detector:
    """Stands in for `s5_precheck.expectation_changes` (and for the helper that reads the person's words
    off its pairs) inside one `with`: counts the calls and answers with `answer` (a dict, or an exception
    to raise)."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __enter__(self):
        self.real, s5_precheck.expectation_changes = s5_precheck.expectation_changes, self
        self.real_words, s5_precheck.word_passed_pairs = s5_precheck.word_passed_pairs, canned_words
        return self

    def __call__(self, task_root, cases, manifest):
        self.calls.append((Path(task_root), list(cases), manifest))
        if isinstance(self.answer, Exception):
            raise self.answer
        return copy.deepcopy(self.answer)

    def __exit__(self, *_):
        s5_precheck.expectation_changes = self.real
        s5_precheck.word_passed_pairs = self.real_words


def tree_hash(root: Path) -> dict:
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}


def pure_window(*changes, **extra) -> dict:
    """The smallest window that passes `window_shape_errors` and has no gap of its own: no instance, and
    the reason there is none. What is left is the list under test - and no story to build."""
    window = {"schema_version": 2, "author_dispatch_id": "a1", "reviewer_dispatch_id": "c1", "input_hash": "h",
              "scope_instances": {"TC-1": []}, "instances": [], "required_quality_checks": [],
              "quality_receipts": [], "not_applicable_reason": "no instance: the list is what is tested"}
    if changes:
        window["expectation_changes"] = list(changes)
    window.update(extra)
    return window


def first(found: list) -> str:
    """The first of a list of gap lines, "" when there is none - so a missing gap fails its own check
    instead of ending the run in an IndexError."""
    return found[0] if found else ""


def owed(root: Path, *pairs, unmeasured=()) -> tuple:
    """`window_record.owed_changes` over a stand-in detector that answers `pairs`."""
    with Detector({"pairs": list(pairs), "unmeasured": list(unmeasured)}) as seen:
        return WR.owed_changes(root, ["TC-1"], {"tests": []}), seen


# ---- group `pure`: no story ---------------------------------------------------------------------------

def the_owed_pairs_are_copied_from_the_real_detector():
    """Edge 1 against the real detector (the cmp1 shape of piece B): one owed pair, its verdict from the
    record that answers it, null when there is none; an orphaned red has a null green attempt; a pair
    outside the scope is only listed by the detector and is not copied."""
    project = temp_project("qa-window-changes-real-")
    try:
        task = TP.filter_story(project)
        TP.cmp1_shape(task)
        manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
        before = tree_hash(task)
        rows, why = WR.owed_changes(task, ["TC-500"], manifest)
        check_eq("cmp1: the one pair the detector owes is copied, with no verdict (no record)",
                 rows, [entry(TP.KEY, TP.A1, TP.A4, None)])
        check_eq("and nothing was left unmeasured", why, "")
        check_eq("the measurement writes nothing", tree_hash(task), before)
        check_eq("a scope that holds none of the pair's cases owes nothing: not copied",
                 WR.owed_changes(task, ["TC-501"], manifest), ([], ""))
        # the record that answers it, and the critic's word on it
        record = {"function": TP.KEY, "red_attempt": TP.A1, "green_attempt": TP.A4,
                  "then_refs": [{"case": "TC-500", "then": 1}], "what_changed": "400 -> 422", "reason": "open"}
        for said, expected in (("legitimate_correction", "legitimate_correction"),
                               ("fitted_to_code", "fitted_to_code"), ("  could_not_judge ", "could_not_judge"),
                               ("", None), ("   ", None), (None, None)):
            with_verdict = dict(manifest, expectation_changes=[dict(record, critic_verdict=said)])
            check_eq(f"a record whose verdict is {said!r} is copied as {expected!r}",
                     WR.owed_changes(task, ["TC-500"], with_verdict)[0][0]["critic_verdict"], expected)
        check_eq("a record with no verdict field at all is a null verdict",
                 WR.owed_changes(task, ["TC-500"], dict(manifest, expectation_changes=[record]))[0][0]["critic_verdict"],
                 None)
        # an orphaned red: the test is gone from its file; its expectation went somewhere
        gone = TP.filter_story(project, ticket="QA-560")
        TP.one_run(gone, "r1", 0, "failed", {"instance_code_sha": "X"}, fn="test_gone")
        rows, why = WR.owed_changes(gone, ["TC-500"], json.loads(
            (gone / "work/automation-manifest.json").read_text(encoding="utf-8")))
        check_eq("an orphaned red is copied with a null green attempt",
                 rows, [entry("test_filter_mod.TestFilters.test_gone", "r1", None, None)])
    finally:
        cleanup(project)


def the_copy_is_stable_and_owed_only():
    """Edge 1 (a stable order, only OWED pairs), edge 4 (a pair passed by a person's word is still listed)
    and edge 2 (an unmeasured detector is reported next to the list). The detector is stood in for so the
    shapes are exact; its real answers are the test above."""
    root = temp_dir("qa-window-changes-order-")
    try:
        pairs = [canned("z.f", "r2", None, verdict="fitted_to_code"),
                 canned("b.f", "r9", "g1", record=False, by_word=True),
                 canned("b.f", "r1", "g2", verdict="legitimate_correction"),
                 canned("a.f", "r1", "g1", verdict="  "),
                 canned("listed.f", "r1", "g1", owed=False)]
        (rows, why), seen = owed(root, *pairs)
        check_eq("owed pairs only, in a stable order (function, red attempt, green attempt)", rows,
                 [entry("a.f", "r1", "g1", None), entry("b.f", "r1", "g2", "legitimate_correction"),
                  entry("b.f", "r9", "g1", None, by_word=True), entry("z.f", "r2", None, "fitted_to_code")])
        check_eq("the same pairs in another order give the same list", owed(root, *reversed(pairs))[0][0], rows)
        check_eq("a pair listed but not owed is not copied", "listed.f" in json.dumps(rows), False)
        check_eq("B1: a pair passed by a person's word (no record) is listed with a null verdict and "
                 "`passed_by_word: true` - visible, never dropped",
                 [e for e in rows if e["function"] == "b.f" and e["red_attempt"] == "r9"],
                 [entry("b.f", "r9", "g1", None, by_word=True)])
        check_eq("B1: a pair NO word passed has no such key at all (the list of before is unchanged)",
                 ["passed_by_word" in e for e in rows], [False, False, True, False])
        check_eq("nothing unmeasured, nothing said", why, "")
        check_eq("no pairs: an empty list, nothing said", owed(root)[0], ([], ""))
        # unmeasured: what WAS measured is kept, and the reason is said, joined
        (rows, why), _ = owed(root, canned("a.f", "r1", "g1"), unmeasured=["block x is unreadable", "report y is gone"])
        check_eq("an unmeasured detector keeps the pairs it found", [e["function"] for e in rows], ["a.f"])
        check_eq("and says why the rest was not measured", why, "block x is unreadable; report y is gone")
        # the call raises: an empty list, the reason names the error
        with Detector(RuntimeError("boom")):
            rows, why = WR.owed_changes(root, ["TC-1"], {})
        check_eq("a detector that raises leaves the list empty", rows, [])
        check_in("and says what failed", "RuntimeError: boom", why)
        # an answer that is not the shape is reported, never a crash and never 'nothing changed'
        for odd in ({"pairs": "nope"}, {"pairs": None}, {}, {"pairs": 5, "unmeasured": []}):
            with Detector(odd):
                rows, why = WR.owed_changes(root, ["TC-1"], {})
            check_eq(f"an answer {odd!r} is unmeasured, not a pass", (rows, bool(why)), ([], True))
    finally:
        cleanup(root)


def the_list_gaps_the_way_the_spec_says():
    """Edges 3, 5 and 7 over `validate_window`, on windows that need no story."""
    root = temp_dir("qa-window-changes-gaps-")
    try:
        def gaps(*entries, **extra):
            return validate_window(pure_window(*entries, **extra), root)

        # each verdict
        check_eq("no verdict: a gap, with the vocabulary's sentence", gaps(entry(verdict=None)),
                 [word("gap_no_verdict", "m.f")])
        check_eq("could_not_judge: a gap", gaps(entry(verdict="could_not_judge")), [word("gap_could_not_judge", "m.f")])
        check_eq("fitted_to_code: a gap", gaps(entry(verdict="fitted_to_code")), [word("gap_fitted_to_code", "m.f")])
        check_eq("legitimate_correction: no gap", gaps(entry(verdict="legitimate_correction")), [])
        check_eq("an orphaned red (no green attempt) with a good verdict: no gap",
                 gaps(entry(green=None, verdict="legitimate_correction")), [])
        check_eq("an orphaned red with no verdict: a gap", gaps(entry(green=None)), [word("gap_no_verdict", "m.f")])
        check_eq("every gap starts with `expectation_change:<function>`",
                 [g.startswith("expectation_change:m.f: ") for g in gaps(entry(verdict="fitted_to_code"))], [True])
        # the closed list: a value outside it names the value and the allowed ones
        for value in ("bogus", "Legitimate_Correction", " legitimate_correction", 5, True, ["legitimate_correction"],
                      {"a": 1}):
            found = gaps(entry(verdict=value))
            check_eq(f"verdict {value!r}: one gap that names the value and the allowed ones",
                     (len(found), f"critic verdict {value!r} is not one of {ALLOWED}" in found[0]), (1, True))
        # an empty word is a missing verdict
        for value in ("", "   "):
            check_eq(f"verdict {value!r} reads as no verdict", gaps(entry(verdict=value)), [word("gap_no_verdict", "m.f")])
        # the limit a gap introduces: the value shown is cut at 60 characters, AT and BEYOND it
        at, beyond = "x" * 58, "x" * 59
        check_in("a value whose repr is 60 characters is printed whole", repr(at) + " is not one of",
                 first(gaps(entry(verdict=at))))
        check_in("one more character is cut, with an ellipsis", repr(beyond)[:60] + "... is not one of",
                 first(gaps(entry(verdict=beyond))))
        big = first(gaps(entry(verdict="y" * 10_000)))
        check("10 KB of verdict is cut to a line a person can read", len(big) < 300, str(len(big)))
        # malformed entries are a hole, not a pass and not a crash
        check_eq("entries that are not objects are named `?`", gaps("nope", 5, None),
                 [word("gap_no_verdict", "?")])
        check_eq("an entry with no function is named `?`", gaps({"critic_verdict": "fitted_to_code"}),
                 [word("gap_fitted_to_code", "?")])
        for junk in (None, "x", {}, 0, {"function": "f"}):
            found = validate_window(pure_window(expectation_changes=junk), root)
            check_eq(f"a key that is not a list ({junk!r}) is one gap, not a pass and not a crash",
                     [g.startswith("expectation_change:?") for g in found], [True])
        # names: non-ASCII and braces survive, several entries, the same function twice
        check("a non-ASCII function name is printed as it is",
              first(gaps(entry(function="m.éf☃"))).startswith("expectation_change:m.éf☃: "))
        check_eq("braces in a function name do not break the sentence",
                 first(gaps(entry(function="m.{f}"))), word("gap_no_verdict", "m.{f}"))
        check_eq("gaps come sorted, one per distinct sentence",
                 gaps(entry("b.f", verdict="fitted_to_code"), entry("a.f"), entry("a.f", "r2", "g2")),
                 sorted({word("gap_fitted_to_code", "b.f"), word("gap_no_verdict", "a.f")}))
        check_eq("the same function twice, one pair judged and one not: the gap stands",
                 gaps(entry(verdict="legitimate_correction"), entry(red="r2")), [word("gap_no_verdict", "m.f")])
        # edge 5: legacy - no key, no gap, no raise
        legacy_window = pure_window()
        check_eq("the fixture window has no key at all", "expectation_changes" in legacy_window, False)
        try:
            legacy = validate_window(legacy_window, root)
        except Exception as exc:  # the point of the check
            legacy = f"raised {type(exc).__name__}: {exc}"
        check_eq("a window WITHOUT the key is legacy: no gap and no raise", legacy, [])
        info: list = []
        check_eq("...and nothing is printed about it", (WR.verdict(root, legacy_window, [], info), info), ([], []))
        check_eq("expectation_change_gaps itself says nothing about a legacy window", expectation_change_gaps(legacy_window), [])
        # purity: the record is not touched and the detector is not consulted
        record = pure_window(entry(verdict="fitted_to_code"))
        frozen = copy.deepcopy(record)
        with Detector(AssertionError("validate_window must not call the detector")) as seen:
            validate_window(record, root)
        check_eq("validate_window stays pure over the record: it does not call the detector", seen.calls, [])
        check_eq("...and does not change the record", record, frozen)
        # the vocabulary unreadable: the gaps stand, the sentence says the words are missing, a good verdict is still no gap
        real = handoff.vocabulary
        handoff.vocabulary = lambda: (_ for _ in ()).throw(OSError("gone"))
        try:
            unreadable = gaps(entry(verdict="fitted_to_code"), entry("g.f", verdict="legitimate_correction"))
        finally:
            handoff.vocabulary = real
        check_eq("with the vocabulary unreadable the gap still stands, the good verdict is still no gap",
                 len(unreadable), 1)
        check_in("...its token is intact", "expectation_change:m.f: ", first(unreadable))
        check_in("...and the sentence says where the words should have been", "handoffs/vocabulary.yaml",
                 first(unreadable))
        # edge 7: with an empty list the window's other gaps, their order and texts are what they were. The
        # literals are what `validate_window` of the commit BEFORE this change returned on the same windows.
        other = pure_window(required_quality_checks=["lint"])
        del other["not_applicable_reason"]
        expected = ["empty_scope", "quality:lint"]
        check_eq("before the change (no key): the window's gaps, as they were", validate_window(other, root), expected)
        for label, extra in (("an empty list", {"expectation_changes": []}),
                             ("an unmeasured note beside an empty list",
                              {"expectation_changes": [], "expectation_changes_unmeasured": "why"}),
                             ("a change with a good verdict", {"expectation_changes": [entry(verdict="legitimate_correction")]})):
            check_eq(f"{label}: the same gaps, the same order, the same texts",
                     validate_window({**other, **extra}, root), expected)
        check_eq("an unresolved change is sorted in among them",
                 validate_window({**other, "expectation_changes": [entry(function="a.f")]}, root),
                 sorted(expected + [word("gap_no_verdict", "a.f")]))
    finally:
        cleanup(root)


def an_unmeasured_note_is_never_a_gap():
    """Edge 2, over the record: no gap, no problem line, one note line saying it was not measured."""
    root = temp_dir("qa-window-changes-note-")
    try:
        window = pure_window(expectation_changes=[], expectation_changes_unmeasured="the run blocks are unreadable")
        check_eq("the window is well formed", C.window_shape_errors(window), [])
        check_eq("validate_window has no gap over `expectation_changes_unmeasured`", validate_window(window, root), [])
        info: list = []
        check_eq("verdict has no problem line over it", WR.verdict(root, window, [], info), [])
        check_eq("and prints exactly one note line about it", len(info), 1)
        check_in("saying it could not be measured, with the vocabulary's word",
                 change_word("not_measured", why="").rstrip(), first(info))
        check_in("and why", "the run blocks are unreadable", first(info))
        info = []
        WR.verdict(root, pure_window(expectation_changes=[]), [], info)
        check_eq("a measured window prints no note about it", info, [])
        info = []
        WR.verdict(root, pure_window(expectation_changes=[], expectation_changes_unmeasured=""), [], info)
        check_in("an empty reason is said as such, never skipped", "no reason was recorded", "\n".join(info))
        # beside a real gap, the note stays a note: the gap is the only problem line
        both = pure_window(entry(verdict=None), expectation_changes_unmeasured="why")
        info = []
        problems = WR.verdict(root, both, [], info)
        check_eq("with a listed change too: one problem line, and it is the change", len(problems), 1)
        check_eq("...and the note is still a note", len(info), 1)
    finally:
        cleanup(root)


def the_verdict_names_whose_move_it_is():
    """Edge 6: each gap has its row in GAP_ORIGIN, and `verdict` prints the row of the gap's own kind."""
    root = temp_dir("qa-window-changes-origin-")
    try:
        window = pure_window(entry("a.f", verdict=None), entry("b.f", verdict="could_not_judge"),
                             entry("c.f", verdict="fitted_to_code"), entry("d.f", verdict="bogus"),
                             entry("e.f", verdict="legitimate_correction"),
                             entry("test_review_probe_outcome", verdict="fitted_to_code"))
        lines = WR.verdict(root, window, [])
        by = collections.defaultdict(str, {line.split(": ", 1)[0].split(":", 1)[1]: line for line in lines
                                           if line.startswith("expectation_change:")})
        check_eq("one line per gap, none for the good verdict", sorted(by),
                 ["a.f", "b.f", "c.f", "d.f", "test_review_probe_outcome"])
        check_in("a missing verdict is the critic's move", "the critic records one verdict per change through `manifest_put.py`",
                 by["a.f"])
        check_in("F-cj: could_not_judge is the CONDUCTOR's move, in the vocabulary's words",
                 "the conductor records the window as unresolved with the reason", by["b.f"])
        check_not_in("F-cj: and no longer sends the critic to record another verdict", "the critic reads", by["b.f"])
        check_in("F-cj: the vocabulary says the same road", "the conductor records the window as unresolved with the reason",
                 handoff.vocabulary()["expectation_change_verdicts"]["could_not_judge"])
        check_in("fitted_to_code is the automator's: restore the value and hand the test RED",
                 "the automator restores the Then's value and hands the test over RED with `contradicts_requirement`",
                 by["c.f"])
        check_in("an unknown verdict is the critic's too: rewrite it with an allowed word", "the critic rewrites it",
                 by["d.f"])
        for name in ("a.f", "b.f", "c.f"):
            check_in(f"{name}: the informed pass is named - `unresolved` and a `reason`", "`unresolved`", by[name])
        check_not_in("the line of a function named like a field is not explained as a missing review",
                     "critic_verdict` is not `approved`", by["test_review_probe_outcome"])
        check_in("...it is explained by its own kind", "automator restores", by["test_review_probe_outcome"])
        for code in ("no_verdict", "could_not_judge", "fitted_to_code", "unknown_verdict"):
            check(f"GAP_ORIGIN has a row for `{code}`", isinstance(WR.change_origin(code), tuple)
                  and len(WR.change_origin(code)) == 2 and bool(WR.change_origin(code)[0]), code)
        check_eq("the four rows are four different rows",
                 len({WR.change_origin(c) for c in ("no_verdict", "could_not_judge", "fitted_to_code", "unknown_verdict")}), 4)
        check_eq("every kind `acceptance` names has a row in the table `verdict` reads",
                 sorted({code for _gap, code in expectation_change_gaps(window)}),
                 ["could_not_judge", "fitted_to_code", "no_verdict", "unknown_verdict"])
    finally:
        cleanup(root)


def the_red_window_speaks_in_its_own_words():
    """HF2-4a (K3, K4): the door of a red no row explains is the row (FR-2: the automator's `manifest_put.py --fragment`,
    never the marker, never the critic's probe and never a person's word - none of the three closes a red); `verdict` prints
    the refusals of the reader (`red:<kind>`) like the blocked ones; the print helpers read the item's own block."""
    door = WR.RED_ROW_DOOR
    check_in("RED_ROW_DOOR: the road is the fragment", "manifest_put.py --task <T> --fragment <file>", door)
    check_in("RED_ROW_DOOR: the row it asks for", "reason: contradicts_requirement, instance_ids: [<this instance>], "
             "thens: [<the red Then>]", door)
    for dead_end in ("qa_unresolved", "waiver.py", "probe_by_code.py", "probe gap"):
        check_not_in(f"RED_ROW_DOOR names no dead end ({dead_end})", dead_end, door)
    check_eq("GAP_ORIGIN[product] names the manifest row, not 'S7 will see it'",
             WR.GAP_ORIGIN["product"][1], door)
    check_in("GAP_ORIGIN[product] says what is missing", "no `contradicts_requirement` row", WR.GAP_ORIGIN["product"][0])
    check_eq("GAP_ORIGIN[contradicts_requirement]: the pair is derived, S7 triages the red",
             WR.GAP_ORIGIN["contradicts_requirement"][1],
             "accepted as unresolved: `story_step.py finish` derives the pair; S7 triages the red")
    root = temp_dir("qa-window-red-words-")
    try:
        notes = [("i1", "red:names_other", "TC-1's contradicts_requirement row names [i2], not i1; SAID"),
                 ("i2", "blocked:stale", "STALE"), ("i3", "blocked:names", "BLOCKED SAID"),
                 ("i4", "probe", "NOT A PROBLEM LINE")]
        lines = WR.verdict(root, pure_window(), notes)
        check_eq("verdict prints a `red:` refusal and a `blocked:` one, and not a note of another field",
                 lines, [notes[0][2], notes[2][2]])
        info: list = []
        WR.verdict(root, pure_window(), notes, info)
        check_eq("...and a stale blocked row stays an info line", info, ["STALE"])
        check_eq("no refusal, no line", WR.verdict(root, pure_window(), []), [])
    finally:
        cleanup(root)
    row = {"case": "TC-1", "reason": "contradicts_requirement", "detail": "words", "remedy": {"kind": "x"},
           "instance_ids": ["a"], "thens": [2], "partitions": ["P-x"], "instance_id": "b", "partition": "P-y"}
    record = WR._red_row_record(row)
    check_eq("a row record is the case and the slice keys and `thens`, as the manifest holds them",
             record, {"case": "TC-1", "instance_id": "b", "instance_ids": ["a"], "partition": "P-y", "partitions": ["P-x"],
                      "thens": [2]})
    record["instance_ids"].append("z")
    check_eq("...a copy, never the row's own list", row["instance_ids"], ["a"])
    check_eq("a bare whole-case row is the case alone", WR._red_row_record({"case": "TC-2", "reason": "x"}),
             {"case": "TC-2"})
    two = {"instances": [{"instance_id": "a", "probe_not_applicable": {"rows": [{"case": "TC-1"}, {"case": "TC-2"},
                                                                              {"case": "TC-1", "thens": [2]}]}},
                         {"instance_id": "b", "probe_not_applicable": {"rows": [{"case": "TC-3"}]}},
                         {"instance_id": "c"}, "junk", {"instance_id": "d", "probe_not_applicable": {"rows": "x"}}]}
    check_eq("the cases of an item's rows, in order, once each", [WR._red_cases(i) for i in two["instances"]],
             [["TC-1", "TC-2"], ["TC-3"], [], [], []])
    gaps = ["contradicts_requirement:a — the latest run block ...", "contradicts_requirement:c",
            "contradicts_requirement:zz", "product:b"]
    check_eq("segments: the id and its cases from its own block, the bare id with none, nothing for a line no item holds",
             WR._red_segments(two, gaps), ["a (TC-1, TC-2)", "c"])
    check_eq("a line of another kind makes no segment", WR._red_segments(two, ["product:a"]), [])
    check_eq("two cases are a note, one is not, three are listed",
             WR._two_case_red_notes({"instances": two["instances"] + [{"instance_id": "e", "probe_not_applicable": {
                 "rows": [{"case": "TC-1"}, {"case": "TC-2"}, {"case": "TC-3"}]}}]}),
             ["a is red for the rows of TC-1 and TC-2; the S5 check asks to keep one",
              "e is red for the rows of TC-1, TC-2 and TC-3; the S5 check asks to keep one"])
    check_eq("an empty window says nothing", (WR._two_case_red_notes({}), WR._red_segments({}, gaps)), ([], []))


def a_persons_word_is_not_asked_for_again():
    """B1 (t-149, P13): a pair a person's word passed at the S5 exit has `passed_by_word: true` in the window,
    raises no gap while it has no verdict, and stays visible in the list and in the printed notes."""
    import waiver as W
    root = temp_dir("qa-window-word-")
    try:
        def gaps(*entries):
            return validate_window(pure_window(*entries), root)
        check_eq("(a) a word-passed pair with no verdict: no gap", gaps(entry(verdict=None, by_word=True)), [])
        check_eq("(a) whitespace is no verdict either: no gap", gaps(entry(verdict="  ", by_word=True)), [])
        check_eq("the same pair with no word: the gap of before", gaps(entry(verdict=None, by_word=False)),
                 [word("gap_no_verdict", "m.f")])
        for odd in ("yes", 1, "true", None):
            check_eq(f"only a literal true is a word: passed_by_word={odd!r} is no word", gaps(entry(by_word=odd)),
                     [word("gap_no_verdict", "m.f")])
        for verdict, name in (("fitted_to_code", "gap_fitted_to_code"), ("could_not_judge", "gap_could_not_judge")):
            check_eq(f"a verdict the critic DID write stands over the word ({verdict}): the gap stays",
                     gaps(entry(verdict=verdict, by_word=True)), [word(name, "m.f")])
        found = gaps(entry(verdict="bogus", by_word=True))
        check_eq("an unknown verdict is not 'no verdict': the word does not hide it", (len(found), "is not one of" in first(found)),
                 (1, True))
        check_eq("a good verdict beside the word: no gap", gaps(entry(verdict="legitimate_correction", by_word=True)), [])
        check_eq("one pair passed by word, another not: only the other gaps",
                 gaps(entry("a.f", by_word=True), entry("b.f")), [word("gap_no_verdict", "b.f")])
        # visible, in the printed notes - and never a problem line
        window = pure_window(entry("a.f", by_word=True), entry("b.f", verdict="fitted_to_code", by_word=True))
        info: list = []
        lines = WR.verdict(root, window, [], info)
        check_eq("verdict: a word-passed pair with no verdict is said in the notes, in the vocabulary's words",
                 [i for i in info if i.startswith("a.f: ")],
                 ["a.f: " + WORDS["not_recorded_passed_by_word"] + " - no verdict is owed for it"])
        check_eq("...and a pair with a verdict is not said to owe none", [i for i in info if i.startswith("b.f: ")], [])
        check_eq("...and only the written verdict is a problem line", [ln.startswith("expectation_change:b.f: ") for ln in lines],
                 [True])
        check_eq("the window's list keeps the pair, marked: nothing is dropped", [(e["function"], e.get("passed_by_word"))
                                                                              for e in window["expectation_changes"]],
                 [("a.f", True), ("b.f", True)])
    finally:
        cleanup(root)
    # against the real detector, the cmp1 shape, and a real pipeline.json
    project = temp_project("qa-window-word-real-")
    try:
        task = TP.filter_story(project)
        TP.cmp1_shape(task)
        manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))

        def with_word(match, at=None):
            pipeline = {"task": "QA-500"}
            if match:
                W.apply_stage_override(pipeline, "S5", match, "the person lets the test stand", at or W.now_iso())
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            return WR.owed_changes(task, ["TC-500"], manifest)
        pair = s5_precheck.expectation_changes(task, ["TC-500"], manifest)["pairs"][0]
        check_eq("no word: the pair is listed with no mark", with_word(None), ([entry(TP.KEY, TP.A1, TP.A4, None)], ""))
        marked = ([entry(TP.KEY, TP.A1, TP.A4, None, by_word=True)], "")
        check_eq("the stage-wide word: listed, marked", with_word("changed-after-red"), marked)
        check_eq("the pair's own tag: listed, marked", with_word(s5_precheck._pair_tag(pair)), marked)
        unmarked = ([entry(TP.KEY, TP.A1, TP.A4, None)], "")
        check_eq("fix 3: a stage-wide word given AFTER the green run (04:56): marked", with_word(
            "changed-after-red", "2026-09-30T06:00:00+00:00"), marked)
        check_eq("fix 3: a stage-wide word given BEFORE the green run: the entry is NOT marked - it gaps again",
                 with_word("changed-after-red", "2026-09-30T04:00:00+00:00"), unmarked)
        check_eq("fix 3: and the window built of it gaps for that pair",
                 len([g for g in validate_window(pure_window(*with_word("changed-after-red", "2026-09-30T04:00:00+00:00")[0]),
                                                 project) if g.startswith("expectation_change")]), 1)
        check_eq("fix 3: the pair's own tag given before the green run: marked (per pair, not compared)",
                 with_word(s5_precheck._pair_tag(pair), "2026-09-30T04:00:00+00:00"), marked)
        check_eq("a word for another function of the stage: not marked",
                 with_word("changed-after-red-test_gone"), ([entry(TP.KEY, TP.A1, TP.A4, None)], ""))
        check_eq("a word for another block: not marked", with_word("case-is-oracle"), ([entry(TP.KEY, TP.A1, TP.A4, None)], ""))
        rows = with_word("changed-after-red")[0]
        check_eq("and the window built of it has no expectation_change gap",
                 [g for g in validate_window(pure_window(*rows), project) if g.startswith("expectation_change")], [])
        record = {"function": TP.KEY, "red_attempt": TP.A1, "green_attempt": TP.A4,
                  "then_refs": [{"case": "TC-500", "then": 1}], "what_changed": "400 -> 422", "reason": "open"}
        check_eq("edge: a word given, then the author records a row for the same pair: the record answers it, the "
                 "mark goes, the pair waits for the critic's verdict as any recorded pair",
                 WR.owed_changes(task, ["TC-500"], dict(manifest, expectation_changes=[record])),
                 ([entry(TP.KEY, TP.A1, TP.A4, None)], ""))
        with_verdict = dict(record, critic_verdict="legitimate_correction", critic_note="ok")
        check_eq("and with the critic's verdict on that record: the verdict is copied",
                 WR.owed_changes(task, ["TC-500"], dict(manifest, expectation_changes=[with_verdict]))[0],
                 [entry(TP.KEY, TP.A1, TP.A4, "legitimate_correction")])
        # the helper cannot read the words: no mark, and the reason is said next to the list
        real = s5_precheck.passed_by_word
        s5_precheck.passed_by_word = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no pipeline"))
        try:
            rows, why = with_word("changed-after-red")
        finally:
            s5_precheck.passed_by_word = real
        check_eq("a helper that cannot tell marks nothing: the pair stays owed", rows, [entry(TP.KEY, TP.A1, TP.A4, None)])
        check_in("and the window says why (FR-41)", "RuntimeError: no pipeline", why)
    finally:
        cleanup(project)


def a_terminal_run_is_the_latest_by_the_clock():
    """F-order: `_terminal_runs` reads the blocks in the story's one order (the block's own clock, a reparse
    right after the block it supersedes), not in file-name order: the reparse of an OLD attempt whose id starts
    with a letter sorts after every `2026...` block by name and used to be 'the latest' outcome."""
    root = temp_dir("qa-window-order-")
    try:
        runs = root / "work" / "run-blocks"
        runs.mkdir(parents=True)

        def block(name, attempt, started, status, **extra):
            data = {"block_id": attempt, "attempt_id": attempt, "attempt_started_at": started,
                    "results": [{"instance_id": "i1", "status": status}], **extra}
            (runs / name).write_text(json.dumps(data), encoding="utf-8")
        first = "20260930T050000000000Z-f302aa.json"
        block(first, "f302aa", "2026-09-30T05:00:00+00:00", "failed")
        block("20260930T051000000000Z-b2bb.json", "b2bb", "2026-09-30T05:10:00+00:00", "passed")
        block("f302aa-reparse-0123.json", "f302aa", "2026-09-30T05:00:00+00:00", "failed",
              reparse_of="work/run-blocks/" + first, supersedes_block_id="f302aa")
        found = WR._terminal_runs(root)
        row, data, path = found["i1"]
        check_eq("the latest terminal row of the instance is the LATER attempt's pass, not the old reparse's red",
                 (C.result_status(row), data["attempt_id"]), ("passed", "b2bb"))
        check_eq("and the path it carries is the block's own file", path, runs / "20260930T051000000000Z-b2bb.json")
        # a block that is not a JSON object, or has no results, is skipped as before
        (runs / "20260930T052000000000Z-bad.json").write_text("[1]", encoding="utf-8")
        (runs / "20260930T053000000000Z-none.json").write_text(json.dumps({"results": None}), encoding="utf-8")
        check_eq("an unreadable block and one with no results change nothing",
                 WR._terminal_runs(root)["i1"][2].name, "20260930T051000000000Z-b2bb.json")
        # the same clock and depth (an attempt with reparse blocks made before and after the producer fix):
        # the name hash decides, as it does for the detector
        block("20260930T060000000000Z-aaaa.json", "aaaa", "2026-09-30T06:00:00+00:00", "failed")
        block("aaaa-reparse-0001.json", "aaaa", "2026-09-30T06:00:00+00:00", "passed",
              reparse_of="work/run-blocks/20260930T060000000000Z-aaaa.json")
        block("aaaa-reparse-9999.json", "aaaa", "2026-09-30T06:00:00+00:00", "failed",
              reparse_of="work/run-blocks/20260930T060000000000Z-aaaa.json")
        check_eq("two reparse blocks of one attempt (same time, same depth): the name decides, as for the detector",
                 WR._terminal_runs(root)["i1"][2].name, "aaaa-reparse-9999.json")
    finally:
        cleanup(root)


# ---- t-134 R8 (P5-G): a window item carries the novelty its row had, RESOLVED at build time ---------------
# `build` over a stand-in controller and a stand-in detector: no story, seconds. The acceptance side is asked
# through `validate_window` (the window's own path), never through `proof_required` directly.

NOVELTY_DISPATCH = {"id": CRITIC, "role": "qa-code-critic", "stage": "S5", "scope": ["TC-1"], "input_hash": "h"}
NOVELTY_FILE = "tests/test_tc-1.py"
NO_KEY = object()


class StandInController:
    """`controller.Controller(task_root).state()` for `build`: one critic dispatch over TC-1 (or over `scope`, when a test
    sets it), nothing else. `_cases_without_instances` is the REAL controller's rule over this task root (t-827 FX-2:
    `window_record` reads that rule, so the stand-in must answer it, not a copy of it)."""
    scope = None
    NO_INSTANCE_REASONS = Controller.NO_INSTANCE_REASONS

    def __init__(self, task_root):
        import types
        self.store = types.SimpleNamespace(root=task_root)

    def state(self):
        dispatch = dict(NOVELTY_DISPATCH)
        if self.scope is not None:
            dispatch["scope"] = list(self.scope)
        return {"dispatches": {CRITIC: dispatch}, "required_quality_checks": [],
                "source_revision": "src-1"}

    def _cases_without_instances(self):
        return Controller._cases_without_instances(self)


def novelty_row(instance, novelty=NO_KEY, disposition="unchanged", **over) -> dict:
    """One manifest row over the real test file of TC-1; `novelty` is written only when it is not NO_KEY."""
    row = {"instance_id": instance, "covers": ["TC-1"], "file": NOVELTY_FILE,
           "trace_binding": {"selector": f"{NOVELTY_FILE}::{instance}", "test_content_sha": SHAS.get("TC-1", "")},
           "change_disposition": disposition, "change_basis_ref": "manifest:TC-1", "critic_verdict": "approved"}
    if novelty is not NO_KEY:
        row["novelty"] = novelty
    row.update(over)
    return row


def row_novelty(project: Path, *, value="unchanged", basis="the function is the same at the base", sha=None) -> dict:
    """A row-form novelty as `manifest_from_tests.py` writes it (R3): measured on the test file as it is now."""
    return {"value": value, "basis": basis, "base": {"kind": "s0", "sha": "a" * 40},
            "measured_on": {NOVELTY_FILE: sha or digest(project / NOVELTY_FILE)},
            "measured_by": "manifest_from_tests.py", "measured_at": "2026-09-30T12:00:00"}


def built_items(task: Path, *rows) -> tuple:
    """`window_record.build` over `rows` with nothing else on disk: (window, {instance id: item})."""
    write(task / "work/automation-manifest.json", {"schema_version": 2, "tests": list(rows)})
    real, CONTROLLER.Controller = CONTROLLER.Controller, StandInController
    try:
        with Detector({"pairs": [], "unmeasured": []}):
            window, _notes = WR.build(task, CRITIC)
    finally:
        CONTROLLER.Controller = real
    return window, {item["instance_id"]: item for item in window["instances"]}


def a_blocked_instance_is_built_with_its_outcome_and_list():
    """t-219 (B2, B4): an instance the stand blocked (its unresolved[] row names it and carries a remedy) gets the
    outcome `blocked_by_env`, an empty fingerprint, no probe and, when it never ran, no evidence; the record ALWAYS
    carries `blocked_by_env[]`; and a window whose only gaps are such instances exits 0 "acceptable as unresolved"."""
    import contextlib
    import io
    project = temp_project("qa-window-blocked-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        test_file(project, "TC-1", "test_a")
        fix = {"kind": "service", "where": "frontend localhost:5173", "change": "the page must load",
               "restart": "re-run"}

        def story(verdict="unverified", remedy=fix, rows=True):
            row = novelty_row("test_a[x]", disposition="new_or_changed", critic_verdict=verdict,
                              obligation_refs=[{"obligation_id": "OB-1", "obligation_hash": "oh-1"}],
                              assertion_id="tests/test_tc-1.py:3", defect_location="src/tc1.py:9")
            unresolved = ([{"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["test_a[x]"],
                            "detail": "the page stayed on Loading", **({"remedy": remedy} if remedy else {})}]
                          if rows else [])
            write(task / "work/automation-manifest.json", {"schema_version": 2, "tests": [row], "unresolved": unresolved})

        def run_cli():
            out = io.StringIO()
            real, CONTROLLER.Controller = CONTROLLER.Controller, StandInController
            try:
                with Detector({"pairs": [], "unmeasured": []}), contextlib.redirect_stdout(out):
                    code = WR.run(TICKET, CRITIC)
            finally:
                CONTROLLER.Controller = real
            return code, out.getvalue()

        story()
        window, items = built_items_of(task)
        item = items["test_a[x]"]
        check_eq("t-219: the blocked instance has the outcome blocked_by_env, an empty fingerprint and no evidence",
                 (item["outcome"], item["execution_fingerprint"], item["evidence_refs"]), ("blocked_by_env", "", []))
        check_eq("t-219: a new_or_changed instance that never ran owes no probe - none is written", "probe" in item, False)
        check_eq("t-219: the record lists it with its row's detail and remedy, the stand `unknown` (no block, no pipeline)",
                 window["blocked_by_env"],
                 [{"instance_id": "test_a[x]", "cases": ["TC-1"], "detail": "the page stayed on Loading", "remedy": fix,
                   "stand": "unknown", "last_run": None}])
        code, out = run_cli()
        check_eq("t-219: the CLI exits 0", code, 0)
        check_in("t-219: 'acceptable as unresolved' with the instance, the fix's place and the stand",
                 "acceptable as unresolved: 1 instance(s) blocked by the stand - test_a[x]: frontend localhost:5173 on unknown",
                 out)
        check_not_in("t-219: and never the marker line of a window that is not acceptable", "NOT acceptable", out)
        story(verdict="approved")
        code, out = run_cli()
        check_eq("t-219: a verdict other than `unverified` on it is a review gap: exit 1, the blocked line among the others",
                 (code, "review:test_a[x]" in out, "blocked_by_env:test_a[x]" in out), (1, True, True))
        story(remedy=None)
        window, items = built_items_of(task)
        code, out = run_cli()
        check_eq("t-219: a row with no remedy is no block: the instance is a failure with no outcome, exit 1",
                 (code, "outcome" in items["test_a[x]"], window["blocked_by_env"]), (1, False, []))
        check_in("t-219: and the refusal names what the automator adds",
                 "test_a[x]: the blocked_by_env row has no remedy; the automator adds {kind, where, change, restart}", out)
        story(rows=False)
        window, _items = built_items_of(task)
        check_eq("t-219: the key is written even when nothing is blocked", window["blocked_by_env"], [])
    finally:
        cleanup(project)


def a_pending_instance_owes_no_probe_and_a_substituted_one_does():
    """t-2181 PC-4 (C5): an instance written for a side that does not exist yet (`acceptance.pending_instances`: a
    `pending_implementation` row names it, its test declares an `absent` side, the sides reader says `absent`) is never run, so
    the window asks no probe of it; the same instance on a SUBSTITUTED side runs, and its probe is owed exactly as before."""
    project = temp_project("qa-window-pending-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        test_file(project, "TC-1", "test_a")
        write(task / "pipeline.json", {"sides": {"ui": {"reality": "real", "source": "launch"},
                                                 "backend": {"reality": "absent", "source": "launch"}}})

        def story(declared):
            row = novelty_row("test_a[x]", disposition="new_or_changed", critic_verdict="unverified",
                              obligation_refs=[{"obligation_id": "OB-1", "obligation_hash": "oh-1"}],
                              assertion_id="tests/test_tc-1.py:3", defect_location="src/tc1.py:9", sides={"backend": declared})
            write(task / "work/automation-manifest.json", {"schema_version": 2, "tests": [row], "unresolved": [
                {"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a[x]"]}]})

        def probe_owed():
            _window, notes = built_with_notes(task)
            return [n for n in notes if n[0] == "test_a[x]" and n[1] == "probe"]

        story("absent")
        check_eq("PC-4: an instance of an absent side, named by its pending row, owes no probe", probe_owed(), [])
        story("substituted")
        check_eq("PC-4: the same instance declared substituted is not pending: its probe is owed", len(probe_owed()), 1)
        story("absent")
        write(task / "pipeline.json", {"sides": {"ui": {"reality": "real", "source": "launch"},
                                                 "backend": {"reality": "real", "source": "arrival"}}})
        check_eq("PC-4: the author's word `absent` is not enough - the sides reader says real: the probe is owed",
                 len(probe_owed()), 1)
    finally:
        cleanup(project)


def a_pending_instance_window_is_shaped_and_a_claim_alone_is_refused():
    """t-2181 PC-4 (B2): the window of a pending instance carries the excuse's own outcome with an empty fingerprint and no evidence,
    owes no probe in the shape check, passes `validate_window` without an outcome gap, and a record that merely CLAIMS the outcome
    (no row, a side the story does not call absent) is refused; the substituted twin keeps its probe demand."""
    project = temp_project("qa-window-pending2-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        test_file(project, "TC-1", "test_a")
        write(task / "pipeline.json", {"sides": {"ui": {"reality": "real", "source": "launch"},
                                                 "backend": {"reality": "absent", "source": "launch"}}})

        def story(declared, rows=True):
            row = novelty_row("test_a[x]", disposition="new_or_changed", critic_verdict="unverified",
                              obligation_refs=[{"obligation_id": "OB-1", "obligation_hash": "oh-1"}],
                              assertion_id="tests/test_tc-1.py:3", defect_location="src/tc1.py:9", sides={"backend": declared})
            write(task / "work/automation-manifest.json", {"schema_version": 2, "tests": [row], "unresolved": [
                {"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a[x]"]}] if rows else []})

        def item_of(window):
            return next(i for i in window["instances"] if i["instance_id"] == "test_a[x]")

        story("absent")
        window, notes = built_with_notes(task)
        item = item_of(window)
        check_eq("PC-4 B2: the item carries the pending outcome, an empty fingerprint and no evidence",
                 (item.get("outcome"), item.get("execution_fingerprint"), item.get("evidence_refs"), "probe" in item),
                 ("pending_implementation", "", [], False))
        check_eq("PC-4 B2: no note asks the author for an outcome, a fingerprint, a probe or evidence",
                 [n for n in notes if n[0] == "test_a[x]" and n[1] in ("outcome", "execution_fingerprint", "probe", "evidence")], [])
        check_eq("PC-4 B2: the built window has no shape error (no probe owed, the outcome is a window outcome)",
                 C.window_shape_errors(window), [])
        gaps = validate_window(window, task)
        check_eq("PC-4 B2: validate_window names no outcome, probe or staleness gap for it (the excuse is the reader's)",
                 [g for g in gaps if g.endswith(":test_a[x]") and g.split(":")[0] in
                  ("product", "sensitivity", "semantic_sensitivity", "stale_run", "pending_implementation")], [])
        # a forged claim: the record says pending, the manifest has no row
        story("absent", rows=False)
        forged = copy.deepcopy(window)
        check_in("PC-4 B2: a record that only CLAIMS the outcome, with no row behind it, is a gap",
                 "product:test_a[x]", validate_window(forged, task))
        story("substituted")
        check_in("PC-4 B2: a claim on a side the manifest declares substituted is a gap as well",
                 "product:test_a[x]", validate_window(forged, task))
        story("substituted")
        window2, _notes = built_with_notes(task)
        check_in("PC-4 B2: the substituted twin keeps its probe demand", "probe is missing",
                 " ".join(C.window_shape_errors(window2)))
    finally:
        cleanup(project)


# ---- t-299 (B-253 item g, Q7 B'): the window no longer promises a person's word it does not read ----------
#
# cmp2r, 02.10 (08-window-6b.txt, 08-waiver-s5.txt): the critic's window was NOT acceptable over two instances the
# stand blocked, and its last line said "A person's word still passes the window: ... waiver.py --block ...". The
# person's word `review is missing` was recorded, `waiver.py` said the block was lifted - and the very next
# `window_record.py` printed the same gaps: nothing reads a word for a gap of the window. Now the blanket promise
# is gone, every gap line names its own door, and a recorded word nothing reads is PRINTED as such.

BLANKET = "A person's word still passes the window"
READ_NOTHING = "recorded, not read by this window: "


def blocked_story_without_a_verdict(project: Path) -> Path:
    """The 08-window-6b shape in one instance: the stand blocked it, and the critic recorded no verdict - a
    shape error (`review is missing`), a review gap and a blocked gap."""
    task = project / "qa-factory" / "artifacts" / TICKET
    (task / "work").mkdir(parents=True)
    test_file(project, "TC-1", "test_a")
    fix = {"kind": "service", "where": "frontend localhost:5173", "change": "the page must load", "restart": "re-run"}
    row = novelty_row("test_a[x]", disposition="new_or_changed", critic_verdict=None,
                      obligation_refs=[{"obligation_id": "OB-1", "obligation_hash": "oh-1"}],
                      assertion_id="tests/test_tc-1.py:3", defect_location="src/tc1.py:9")
    write(task / "work/automation-manifest.json", {
        "schema_version": 2, "tests": [row],
        "unresolved": [{"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["test_a[x]"],
                        "detail": "the page stayed on Loading", "remedy": fix}]})
    return task


def say_word(task: Path, match: str, decision: str, *, stage="S5", revoked=False) -> None:
    """Record a person's word the way `waiver.py --stage ... --block ... --decision ...` does."""
    import waiver as W
    path = task / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"task": TICKET}
    W.apply_stage_override(pipeline, stage, match, decision, W.now_iso())
    if revoked:
        W.revoke_stage_override(pipeline, stage, match, "the person took it back", W.now_iso())
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def window_main(task: Path) -> tuple:
    """`window_record.main()` - the CLI entry - over the stand-in controller: (exit code, what it printed)."""
    import contextlib
    import io
    out = io.StringIO()
    real_argv, real_controller = sys.argv, CONTROLLER.Controller
    sys.argv = ["window_record.py", "--task", TICKET, "--dispatch", CRITIC]
    CONTROLLER.Controller = StandInController
    try:
        with Detector({"pairs": [], "unmeasured": []}), contextlib.redirect_stdout(out):
            code = WR.main()
    finally:
        sys.argv, CONTROLLER.Controller = real_argv, real_controller
    return code, out.getvalue()


def a_word_nothing_reads_is_printed_and_changes_nothing():
    """K8, S8, S9, S10 of t-294 node B."""
    from role_cli import REPAIR_MARKER
    project = temp_project("qa-window-unread-")
    use_project(project)
    try:
        task = blocked_story_without_a_verdict(project)
        code0, out0 = window_main(task)
        check_eq("K8: the 6b-shaped window is not acceptable: exit 1", code0, 1)
        check_in("K8: ... with the shape error the person's word named", "test_a[x]: review is missing", out0)
        check_in("K8: ... and the review gap, with its real door: the critic records `unverified` through manifest_put.py",
                 "review:test_a[x]", out0)
        gap_line = next(line for line in out0.splitlines() if line.strip().startswith("- review:test_a[x]"))
        check("K8: the review gap of a blocked instance names `unverified` and `manifest_put.py`",
              "`unverified`" in gap_line and "`manifest_put.py`" in gap_line, gap_line)
        check_not_in("K8: the blanket promise is gone", BLANKET, out0)
        check_not_in("S10: ... and so is the waiver command it carried", "waiver.py --task", out0)
        check_in("K8: the last line is the honest one, still marked a repair of the role's own",
                 f"{REPAIR_MARKER}. Where a person's word passes a gap, the line above says how.", out0)
        check_not_in("no word was recorded: nothing is said to be unread", READ_NOTHING, out0)
        import story_run
        check_eq("S10: the driver still hands the refusal back to the role (it routes on the marker, not the sentence)",
                 (story_run.match_known(out0) or ("", ""))[1], "resume_repair")

        # the person's word of the rehearsal, recorded
        words = "TC_004 and TC_008 were blocked by the dev stand and their static review stands"
        say_word(task, "review is missing", words)
        code1, out1 = window_main(task)
        check_eq("S9: the exit code is the same with the word recorded", code1, code0)
        unread = [line for line in out1.splitlines() if READ_NOTHING in line]
        check_eq("K8: one note says the word is recorded and not read, with the person's words", len(unread), 1)
        check_in("K8: ... the note starts as a note", "note: " + READ_NOTHING + words, unread[0])
        check_in("K8: ... and names the door of the line the word matched: the critic's manifest_put.py record of `unverified`",
                 "`unverified`", unread[0])
        check_in("K8: ... through manifest_put.py", "`manifest_put.py`", unread[0])
        check_eq("S9: everything else the window printed is the same, line for line",
                 [line for line in out1.splitlines() if READ_NOTHING not in line], out0.splitlines())
        # S9 at the function: the problem lines are identical with and without the words, and with `info` or not
        real_controller = CONTROLLER.Controller
        CONTROLLER.Controller = StandInController
        try:
            with Detector({"pairs": [], "unmeasured": []}):
                window, notes = WR.build(task, CRITIC)
        finally:
            CONTROLLER.Controller = real_controller
        info: list = []
        with_info = WR.verdict(task, window, notes, info)
        check_eq("S9: verdict() without `info` returns the same problems", WR.verdict(task, window, notes), with_info)
        (task / "pipeline.json").rename(task / "pipeline.off")
        check_eq("S9: ... and the same problems with no word recorded at all", WR.verdict(task, window, notes, []), with_info)
        (task / "pipeline.off").rename(task / "pipeline.json")
        check_eq("K8: the problem lines never name the recorded word (it is a note, not a problem)",
                 [line for line in with_info if READ_NOTHING in line], [])
        check_eq("K8: ... the note is in `info`, once", len([i for i in info if i.startswith(READ_NOTHING)]), 1)

        # other words
        def notes_for(match, decision="the person's words", **kwargs):
            (task / "pipeline.json").unlink(missing_ok=True)
            say_word(task, match, decision, **kwargs)
            got: list = []
            WR.verdict(task, window, notes, got)
            return [i for i in got if i.startswith(READ_NOTHING)]
        check_eq("a word whose match is in no line says nothing", notes_for("no such line anywhere"), [])
        check_eq("a word for another stage says nothing", notes_for("review is missing", stage="S6"), [])
        check_eq("a word the person took back (revoked) says nothing", notes_for("review is missing", revoked=True), [])
        check_eq("a word with no decision is no word", notes_for("review is missing", "  "), [])
        blocked = notes_for("blocked_by_env", "the stand is the person's to fix")
        check_eq("a word for the stand-blocked gap is not read either: one note", len(blocked), 1)
        check_in("... with THAT gap's door: the finish derives the unresolved pair from the record", "derives the `unresolved` pair",
                 blocked[0])
        every = notes_for("*", "go on")
        doors = {line.split(" — ", 1)[1] for line in every}
        check_eq("`*` matches every unread line: one note per distinct door, none twice", len(every), len(doors))
        check("... and there are two here: the critic's record of `unverified`, and the unresolved pair of the blocked gap",
              any("`manifest_put.py`" in d for d in doors) and any("derives the `unresolved` pair" in d for d in doors)
              and len(every) == 2, str(every))
        long_words = "word " * 400
        check_in("a long word is printed whole (a person's words are carried in full), whitespace folded",
                 long_words.strip(), notes_for("review is missing", "  " + long_words.replace(" ", " \n "))[0])

        # S10: the old sentence lives in the fixtures and in nothing the driver reads
        sources = {"window_record.py": (SCRIPTS / "window_record.py").read_text(encoding="utf-8")}
        sources.update({path.name: text for path, text in driver_sources()})
        check_eq("S10: `word still passes` is in neither window_record.py nor any file of the driver set",
                 [name for name, text in sources.items() if "word still passes" in text], [])
        control = (Path(__file__).resolve().parent / "test_story_run_loop_b_loop.py").read_text(encoding="utf-8")
        check("S10 positive control: the SAME pattern finds the fixture's own copy in test_story_run_loop_b_loop.py",
              "word still passes" in control)
    finally:
        cleanup(project)


def a_word_a_reader_passes_is_not_called_unread():
    """The kinds a recorded word is read for are not reported: a `quality` gap and a pair changed after its red run;
    the `empty_scope` gap beside them is."""
    import waiver as W
    root = temp_dir("qa-window-read-")
    try:
        window = pure_window(entry("m.f", verdict="fitted_to_code"), required_quality_checks=["lint"])
        del window["not_applicable_reason"]
        pipeline = {}
        for match in ("quality:lint", "expectation_change:m.f", "empty_scope"):
            W.apply_stage_override(pipeline, "S5", match, f"the person's word for {match}", W.now_iso())
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        info: list = []
        problems = WR.verdict(root, window, [], info)
        check_eq("the window has the three gaps", sorted(re.match(r"[a-z_]+", p).group(0) for p in problems),
                 ["empty_scope", "expectation_change", "quality"])
        said = [i for i in info if i.startswith(READ_NOTHING)]
        check_eq("only the gap nobody reads a word for is reported", [i.split(" — ")[0] for i in said],
                 [READ_NOTHING + "the person's word for empty_scope"])
        check_in("... with its own door", "the automator writes the tests", said[0])
        check_in("the quality gap still names the word that passes it (Q7 B': kept as it was)", '--block "not receipted"',
                 next(p for p in problems if p.startswith("quality:")))
        # a clean window has no line for a word to match: nothing is said, and a gap with no door of its own
        # gets the honest fallback in words, never an invented command
        info = []
        WR.verdict(root, pure_window(), [], info)
        check_eq("a clean window says nothing about words", [i for i in info if i.startswith(READ_NOTHING)], [])
        check_in("the fallback door is said in words", "no recorded word is read for it", WR.NO_DOOR)
    finally:
        cleanup(root)


def built_items_of(task: Path) -> tuple:
    """`build` over what is on disk now, the stand-in controller and the stand-in detector: (window, {id: item})."""
    real, CONTROLLER.Controller = CONTROLLER.Controller, StandInController
    try:
        with Detector({"pairs": [], "unmeasured": []}):
            window, _notes = WR.build(task, CRITIC)
    finally:
        CONTROLLER.Controller = real
    return window, {item["instance_id"]: item for item in window["instances"]}


def sensitivity_gaps(window: dict, task: Path) -> list:
    """The `sensitivity:` gaps of the window's own acceptance check: who is asked for a live check."""
    return [gap for gap in validate_window(window, task) if gap.startswith("sensitivity:")]


def the_item_carries_the_novelty_its_row_had_resolved():
    """R8 items 1-3 and edges (i)-(v): the key is written only for a row that has it, resolved through the one
    reader; a stale or malformed novelty is stored as `unknown`; acceptance reads the item-form block."""
    import proof_level
    project = temp_project("qa-window-novelty-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        test_file(project, "TC-1", "test_a")
        proof_level._reset()
        fresh = row_novelty(project)
        stored = {value: {"value": value, "basis": f"stored {value}"} for value in ("new", "changed", "unknown")}
        rows = [novelty_row("legacy[1]"),
                novelty_row("fresh[1]", fresh),
                novelty_row("new[1]", stored["new"]),
                novelty_row("changed[1]", stored["changed"]),
                novelty_row("unknown[1]", stored["unknown"]),
                novelty_row("stale[1]", row_novelty(project, sha="0" * 64)),
                novelty_row("null[1]", None),
                novelty_row("list[1]", ["unchanged"]),
                novelty_row("capitals[1]", {"value": "UNCHANGED"})]
        window, items = built_items(task, *rows)
        check_eq("R8.2: a legacy row (no `novelty` key) gives its item NO key: today's rule applies to it",
                 "novelty" in items["legacy[1]"], False)
        check_eq("R8.1: a fresh row-form `unchanged` is stored resolved, in the item form (no measured_on/by)",
                 items["fresh[1]"]["novelty"],
                 {"value": "unchanged", "basis": "the function is the same at the base", "resolved": True})
        for value, block in stored.items():
            check_eq(f"R8.1: a stored `{value}` is copied with its basis, resolved", items[f"{value}[1]"]["novelty"],
                     {**block, "resolved": True})
        stale = items["stale[1]"]["novelty"]
        check_eq("edge (ii): a stale row-form `unchanged` is stored `unknown`, resolved - not copied as it was",
                 (stale["value"], stale.get("resolved"), sorted(stale)), ("unknown", True, ["basis", "resolved", "value"]))
        check_in("edge (ii): and its basis says the measured file changed", "changed since the measurement", stale["basis"])
        for label in ("null", "list", "capitals"):
            check_eq(f"edge (iii): a malformed novelty ({label}) is stored `unknown` with the reader's own words, resolved",
                     items[f"{label}[1]"]["novelty"],
                     {"value": "unknown", "basis": proof_level.WHY_NOVELTY_MALFORMED, "resolved": True})
        check_eq("the record keeps its shape: no structural gap for a window carrying the block",
                 [e for e in C.window_shape_errors(window) if "novelty" in e], [])

        # Acceptance reads the item-form block through its own path (R8.3): a live check is owed for every value
        # but a fresh `unchanged`, and a legacy item is judged by today's rule alone.
        owed_ids = [gap.split(":", 1)[1] for gap in sensitivity_gaps(window, task)]
        check_eq("R8.3: acceptance owes a check to new, changed, unknown, the stale one and every malformed one",
                 sorted(owed_ids), sorted(["new[1]", "changed[1]", "unknown[1]", "stale[1]", "null[1]", "list[1]",
                                           "capitals[1]"]))
        check_eq("R8.3: ...and none to the fresh `unchanged` nor to the legacy row", [
            i for i in ("fresh[1]", "legacy[1]") if i in owed_ids], [])
        legacy_new, legacy_items = built_items(task, novelty_row("legacy[2]", disposition="new_or_changed"))
        check_eq("R8.2: a legacy row whose disposition says new_or_changed is still owed a check (today's rule)",
                 ["novelty" in legacy_items["legacy[2]"], sensitivity_gaps(legacy_new, task)],
                 [False, ["sensitivity:legacy[2]"]])

        # edge (i): the reader says "no key" for a keyed row (cannot happen by its contract): no key on the item
        real, proof_level.novelty_of = proof_level.novelty_of, lambda _entry, project=None: (None, "")
        try:
            _w, none_items = built_items(task, novelty_row("none[1]", fresh))
        finally:
            proof_level.novelty_of = real
        check_eq("edge (i): `novelty_of` answering (None, '') for a keyed row: no key on the item",
                 "novelty" in none_items["none[1]"], False)

        # edge (ii)+(iv): the window is immutable once built; a rebuild re-resolves from the row
        proof_level._reset()
        path = project / NOVELTY_FILE
        original = path.read_bytes()
        first, first_items = built_items(task, novelty_row("fresh[1]", fresh))
        kept = copy.deepcopy(first)
        check_eq("edge (iv): the first window holds `unchanged`", first_items["fresh[1]"]["novelty"]["value"], "unchanged")
        path.write_bytes(original + b"# edited after the measurement\n")
        proof_level._reset()
        second, second_items = built_items(task, novelty_row("fresh[1]", fresh))
        check_eq("edge (iv): a window rebuilt after the test file changed re-resolves the row: `unknown`",
                 (second_items["fresh[1]"]["novelty"]["value"], second_items["fresh[1]"]["novelty"].get("resolved")),
                 ("unknown", True))
        check_eq("edge (iv): the first window's item is untouched (a window is immutable once built)", first, kept)
        path.write_bytes(original)
        proof_level._reset()
        check_eq("edge (ii): the bytes put back do not revive the stored `unknown` inside that window",
                 (second_items["fresh[1]"]["novelty"]["value"], sensitivity_gaps(second, task)),
                 ("unknown", ["sensitivity:fresh[1]"]))
        third, third_items = built_items(task, novelty_row("fresh[1]", fresh))
        check_eq("edge (iv): ...a NEW window is re-resolved from the row, and reads `unchanged` again",
                 third_items["fresh[1]"]["novelty"]["value"], "unchanged")

        # edge (v): the project cannot be resolved at build time: a row-form `unchanged` reads `unknown`, no raise
        real_project, proof_level._project = proof_level._project, lambda: None
        try:
            proof_level._reset()
            blind, blind_items = built_items(task, novelty_row("fresh[1]", fresh),
                                             novelty_row("new[1]", {"value": "new", "basis": "b"}))
        finally:
            proof_level._project = real_project
        check_eq("edge (v): project unresolvable: a row-form `unchanged` is stored `unknown` (R5), no exception",
                 (blind_items["fresh[1]"]["novelty"]["value"], blind_items["fresh[1]"]["novelty"].get("resolved")),
                 ("unknown", True))
        check_eq("edge (v): ...and a stored `new` is still `new`", blind_items["new[1]"]["novelty"]["value"], "new")
        check_eq("V10: nothing in this script reads an `unmeasured_line` (the owner declined that group)",
                 hasattr(WR, "unmeasured_line"), False)
    finally:
        proof_level._reset()
        cleanup(project)


# The four ORIGIN entries of the row fields as they stood BEFORE HF2-12 moved the field names into the carrier
# (copied from the file before the edit): the window's words for a missing field did not change with it.
ORIGIN_BEFORE_HF2_12 = {
    "assertion_id": ("the manifest row carries no `assertion_id`",
                     "the automator names the assertion that fails when the behaviour breaks"),
    "defect_location": ("the manifest row carries no `defect_location`",
                        "the automator names the product location the obligation damages"),
    "change_disposition": ("the manifest row carries no `change_disposition`",
                           "`new_or_changed` or `unchanged`, written by the automator"),
    "change_basis_ref": ("the manifest row carries no `change_basis_ref`",
                         "the automator names what the disposition is read from"),
}


def the_window_reads_its_row_fields_from_the_carrier():
    """HF2-12a K3: `build` takes the names of the item's text fields and the empty-field deletion from
    `REQUIRED_ROW_FIELDS` (window=True, filled_by automator); the ORIGIN texts for the four fields are what they were."""
    import proof_level
    for field, text in ORIGIN_BEFORE_HF2_12.items():
        check_eq(f"K3: ORIGIN[{field}] is byte for byte what it was before the carrier", WR.ORIGIN[field], text)
        check_eq(f"K3: ...and `_origin_text` joins the two halves as before ({field})",
                 WR._origin_text(field), text[0] + "; " + text[1])
    check_eq("K3: the text fields the window copies are the carrier's window=True automator fields, in its order",
             WR.window_text_fields(), ("assertion_id", "defect_location", "change_disposition", "change_basis_ref"))
    project = temp_project("qa-window-carrier-")
    use_project(project)
    carrier = dict(WR.REQUIRED_ROW_FIELDS)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        test_file(project, "TC-1", "test_a")
        proof_level._reset()
        full = novelty_row("full[1]", assertion_id="a:1", defect_location="s:2", profile_id="api", zzz_field="z")
        bare = novelty_row("bare[1]", change_disposition="")
        _window, items = built_items(task, full, bare)
        check_eq("K3: a row's four fields reach the item", [items["full[1]"].get(f) for f in WR.window_text_fields()],
                 ["a:1", "s:2", "unchanged", "manifest:TC-1"])
        check_eq("K3: an empty or absent field is LEFT OUT of the item, never filled with a placeholder",
                 sorted(f for f in WR.window_text_fields() if f in items["bare[1]"]), ["change_basis_ref"])
        check_eq("K3: `profile_id` (window=False) is not copied into the item", "profile_id" in items["full[1]"], False)
        WR.REQUIRED_ROW_FIELDS["zzz_field"] = WR.RowField("a field added to the carrier only", "always", (),
                                                          "automator", WR.FRAGMENT_DOOR, True)
        _window, items = built_items(task, full, bare)
        check_eq("K3: a field added to the carrier (window=True) is copied by `build` with no other edit",
                 [items["full[1]"].get("zzz_field"), "zzz_field" in items["bare[1]"]], ["z", False])
        WR.REQUIRED_ROW_FIELDS["zzz_field"] = WR.RowField("added, but not for the window", "always", (),
                                                          "automator", WR.FRAGMENT_DOOR, False)
        _window, items = built_items(task, full, bare)
        check_eq("K3: ...and window=False keeps it out of the item", "zzz_field" in items["full[1]"], False)
    finally:
        WR.REQUIRED_ROW_FIELDS.clear()
        WR.REQUIRED_ROW_FIELDS.update(carrier)
        proof_level._reset()
        cleanup(project)


# ---- the story group: the window built from a real story, and accepted by the controller ----------------

def the_window_carries_the_list_on_a_story(project: Path, task: Path):
    """Edges 1, 2 and 8 through `build`: the key is always there, the detector is called once per build with the
    dispatch's scope and the manifest and writes nothing; an unmeasured detector is a note, and the story goes on."""
    before = tree_hash(task)
    window, notes = WR.build(task, CRITIC)
    check_eq("the key is there, empty, when no test changed after a red run", window.get("expectation_changes"), [])
    check_eq("and the detector measured everything: no `expectation_changes_unmeasured`",
             "expectation_changes_unmeasured" in window, False)
    check_eq("building the window writes nothing into the story (the detector is read-only)", tree_hash(task), before)
    check_eq("an empty list is no gap", validate_window(window, task), [])
    with Detector({"pairs": [], "unmeasured": []}) as seen:
        WR.build(task, CRITIC)
    check_eq("the detector is called ONCE per build", len(seen.calls), 1)
    check_eq("with the story, the dispatch's scope and the manifest",
             (seen.calls[0][0], seen.calls[0][1], sorted(t["instance_id"] for t in seen.calls[0][2]["tests"])),
             (task, ["TC-1", "TC-2"], ["test_a[x]", "test_b[y]"]))
    # a detector that raises: the story goes on
    with Detector(RuntimeError("boom")):
        broken, notes = WR.build(task, CRITIC)
    check_eq("a detector that raises leaves the list empty and the key present", broken["expectation_changes"], [])
    check_in("and the window says what failed", "RuntimeError: boom", broken["expectation_changes_unmeasured"])
    check_eq("it is no gap", validate_window(broken, task), [])
    info: list = []
    check_eq("nor a problem line", WR.verdict(task, broken, notes, info), [])
    check_eq("but one note line", [line.startswith("expectation changes not measured: ")
                                   for line in without_freshness(info)], [True])
    # end to end with a REAL unmeasured: a run block that is not JSON. The CLI still accepts the window.
    (task / "work/run-blocks/broken.json").write_text("{not json", encoding="utf-8")
    try:
        result = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, cwd=project)
        check_eq("the CLI still accepts the window: the story goes on", result.returncode, 0)
        check_in("and prints the note", "note: expectation changes not measured: work/run-blocks/broken.json",
                 result.stdout)
        record = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        check_eq("the file carries the list, empty, and the reason next to it",
                 (record["expectation_changes"], "broken.json" in record["expectation_changes_unmeasured"]), ([], True))
    finally:
        (task / "work/run-blocks/broken.json").unlink()
    result = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, cwd=project)
    record = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
    check_eq("measured again: the CLI's file carries the key, empty, and no note", (
        result.returncode, record["expectation_changes"], "expectation_changes_unmeasured" in record), (0, [], False))


def accept_window(project: Path, task: Path, window: dict, key: str, **extra):
    """The controller's own accept of a window record, from a file - the gate the position invariant is about."""
    path = write(task / "work/windows" / (CRITIC + ".json"), window)
    findings = task / "work/test-code/critic-findings.md"
    findings.parent.mkdir(parents=True, exist_ok=True)
    findings.write_text("# findings\n\nnone blocking\n", encoding="utf-8")
    completion = task / f"work/completion-{key}.json"
    completion.write_text(json.dumps({
        "id": CRITIC, "status": "accepted", "stage_complete": True,
        "evidence_refs": [{"path": "work/test-code/critic-findings.md", "sha256": digest(findings)}],
        "idempotency_key": "a-critic-" + key, **extra}), encoding="utf-8")
    return run_script("controller.py", "--task-root", task, "--operation", "accept", "--input", completion,
                      "--window", path, cwd=project)


def a_listed_change_is_accepted_only_as_unresolved(project: Path, task: Path):
    """The position invariant, at the controller: a window with a listed change that has no good verdict is
    taken ONLY through the unresolved-acceptance path (`unresolved` + `reason`), never as a clean window.
    A pair passed by a person's word has no such gap while it has no verdict (B1, P13): the next test takes a
    window carrying one. The controller is unchanged - this is what it already does with any semantic gap.
    Runs last on its story: it accepts."""
    # the critic's own receipts first, as the CLI leaves them (`--review-receipt`)
    built = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
    check("the window is receipted", built.returncode == 0, built.stdout + built.stderr)
    window = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
    for number, verdict in enumerate((None, "could_not_judge", "fitted_to_code", "bogus")):
        held = {**window, "expectation_changes": [entry("m.f", verdict=verdict)]}
        refused = accept_window(project, task, held, f"n{number}")
        check(f"verdict {verdict!r}: the window is refused as a clean acceptance", refused.returncode != 0,
              refused.stdout + refused.stderr)
        check_in(f"verdict {verdict!r}: the controller says it is an unresolved window and names the gap",
                 "unresolved window: expectation_change:m.f: ", refused.stdout + refused.stderr)
    # a pair passed by a person's word at the S5 exit (B1): the window lists it, marked, and raises no gap
    # for it while it has no verdict - the word is never asked for again. Its clean acceptance is the next test.
    with Detector({"pairs": [canned("m.f", "r1", "g1", record=False, by_word=True)], "unmeasured": []}):
        by_word, _ = WR.build(task, CRITIC)
    check_eq("passed by a person's word, the pair is still listed, with no verdict, marked",
             by_word["expectation_changes"], [entry("m.f", "r1", "g1", None, by_word=True)])
    check_eq("and the window has no expectation_change gap for it",
             [g for g in validate_window({**window, "expectation_changes": by_word["expectation_changes"]}, task)
              if g.startswith("expectation_change")], [])
    held = {**window, "expectation_changes": [entry("m.f", verdict="fitted_to_code")]}
    bare = accept_window(project, task, held, "u0", unresolved=["expectation_change:m.f"])
    check("`unresolved` without a `reason` is not the informed pass", bare.returncode != 0, bare.stdout + bare.stderr)
    green = accept_window(project, task, held, "u1", unresolved=["expectation_change:m.f"],
                          reason=UNRESOLVED_REASON, passed_green=True)
    check_in("and it cannot be passed_green: the controller's own words", "cannot be passed_green",
             green.stdout + green.stderr)
    check_eq("nothing was accepted by any of the refusals", Controller(task).state()["dispatches"][CRITIC]["status"],
             "running")
    done = accept_window(project, task, held, "u2",
                         unresolved=["expectation_change:m.f"], reason=UNRESOLVED_REASON)
    check("with `unresolved` and a `reason` the window is accepted: the informed pass", done.returncode == 0,
          done.stdout + done.stderr)
    check_eq("the critic's dispatch is accepted", Controller(task).state()["dispatches"][CRITIC]["status"], "accepted")


def the_novelty_reaches_the_window_and_its_acceptance_on_a_story():
    """R8.3 end to end: the CLI builds the window from a story whose rows carry a `novelty`, prints no note about
    tests that were not measured (V10), refuses a window whose resolved value owes a live check that has no
    receipt, and the controller accepts the window whose only keyed row without a receipt is a fresh `unchanged`."""
    project = temp_project("qa-window-novelty-story-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        path = task / "work/automation-manifest.json"

        def set_novelty(a, b):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for row in manifest["tests"]:
                key = {"test_a[x]": a, "test_b[y]": b}[row["instance_id"]]
                row.pop("novelty", None)
                if key is not NO_KEY:
                    row["novelty"] = key
            write(path, manifest)

        def measured(case, value="unchanged"):
            return {"value": value, "basis": "measured on the story", "base": {"kind": "s0", "sha": "a" * 40},
                    "measured_on": {f"tests/test_{case.lower()}.py": SHAS[case]},
                    "measured_by": "manifest_from_tests.py", "measured_at": "2026-09-30T12:00:00"}
        # test_a is new_or_changed and has its receipt; test_b is `unchanged` and has none
        set_novelty(measured("TC-1", "new"), measured("TC-2"))
        result, record = window_of(project, task)
        items = {i["instance_id"]: i for i in record["instances"]}
        check("a fresh `unchanged` row without a receipt, and a `new` one with its receipt: acceptable",
              result.returncode == 0, result.stdout + result.stderr)
        check_eq("the file carries each row's resolved block",
                 (items["test_a[x]"]["novelty"], items["test_b[y]"]["novelty"]),
                 ({"value": "new", "basis": "measured on the story", "resolved": True},
                  {"value": "unchanged", "basis": "measured on the story", "resolved": True}))
        check_eq("V10: the CLI prints no `note:` about unmeasured tests (nor any other note on this story)",
                 without_freshness([line for line in result.stdout.splitlines() if line.startswith("note: ")]), [])
        for value in ("new", "changed", "unknown"):
            set_novelty(measured("TC-1", "new"), measured("TC-2", value))
            result, refused = window_of(project, task)
            check_eq(f"a resolved `{value}` with no receipt: refused, and the gap names the instance",
                     (result.returncode, "sensitivity:test_b[y]" in result.stdout), (1, True))
        set_novelty(measured("TC-1", "new"), {"value": "unchanged", "basis": "stale",
                                              "measured_on": {"tests/test_tc-2.py": "0" * 64}})
        result, stale = window_of(project, task)
        check_eq("a stale row-form `unchanged` with no receipt: stored `unknown`, refused",
                 (stale["instances"][1]["novelty"]["value"], result.returncode), ("unknown", 1))
        set_novelty(NO_KEY, NO_KEY)
        result, legacy = window_of(project, task)
        check_eq("legacy rows (no key): no key on any item, and today's rule accepts the window",
                 ([("novelty" in i) for i in legacy["instances"]], result.returncode), ([False, False], 0))
        set_novelty(measured("TC-1", "new"), measured("TC-2"))
        built = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        check("the keyed window is receipted", built.returncode == 0, built.stdout + built.stderr)
        window = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        done = accept_window(project, task, window, "nv")
        check("the controller accepts the window that carries the resolved blocks", done.returncode == 0,
              done.stdout + done.stderr)
        check_eq("and the critic's dispatch is accepted", Controller(task).state()["dispatches"][CRITIC]["status"],
                 "accepted")
    finally:
        cleanup(project)


def a_window_with_only_good_verdicts_is_accepted_as_before():
    """The other side of the invariant: changes that all carry a good verdict (an orphaned red too) gap nothing,
    and the controller takes the window with nothing unresolved, exactly as it took one before this change."""
    project = temp_project("qa-window-changes-good-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        built = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        check("the window is receipted", built.returncode == 0, built.stdout + built.stderr)
        window = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        held = {**window, "expectation_changes": [entry("m.f", verdict="legitimate_correction"),
                                                  entry("o.f", green=None, verdict="legitimate_correction"),
                                                  entry("w.f", verdict=None, by_word=True)]}
        done = accept_window(project, task, held, "g0")
        check("listed changes with a good verdict, and one a person's word passed (no verdict, marked): accepted "
              "with nothing unresolved (B1)", done.returncode == 0, done.stdout + done.stderr)
        check_eq("and the critic's dispatch is accepted", Controller(task).state()["dispatches"][CRITIC]["status"],
                 "accepted")
    finally:
        cleanup(project)


def a_rejected_review_on_a_run_instance_is_receipted_and_sent_back():
    """t-1603: the critic's `rejected` on an instance that RAN sends the window back: receipt written, exit 1,
    never 'acceptable'. The control is the same story with `approved` (exit 0)."""
    project = temp_project("qa-window-rejected-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        path = task / "work/automation-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for row in manifest["tests"]:
            row["critic_verdict"] = "rejected"
        path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        (task / PROBE_REF).unlink()     # t-1604 F1: the probe is gone, the binding still names it
        built = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        check_eq("a rejected review exits 1", built.returncode, 1)
        check_in("the probe gap is really there (the kill test of the kinds)", "sensitivity:", built.stdout)
        check_in("and says the window is sent back to its author", "sent back to its author", built.stdout)
        check_not_in("and never says the window is acceptable", "the window is acceptable", built.stdout)
        check("and the receipt is written", (task / "work/review-receipts" / (CRITIC + ".json")).is_file(),
              built.stdout + built.stderr)
        refs = [b.get("review_receipt_ref") for b in json.loads(path.read_text(encoding="utf-8")).get("obligation_bindings", [])]
        check("and published on the bindings", bool(refs) and all(refs), str(refs))
    finally:
        cleanup(project)


def the_changes_on_one_story():
    project = temp_project("qa-window-changes-story-")
    use_project(project)
    try:
        task, _ = a_story_at_s5(project)
        the_window_carries_the_list_on_a_story(project, task)
        a_listed_change_is_accepted_only_as_unresolved(project, task)
    finally:
        cleanup(project)


# t-238: the receipt dict was pulled out of `write_review_receipt` (`receipt_dict`) so that
# `coverage_contract.witnessed_binding` can rebuild it from the accepted window. The file the writer
# produces must stay byte-for-byte what it was: this text was captured from the writer BEFORE the
# extraction (line endings normalised: the writer's atomic_json writes the platform's).
RECEIPT_WINDOW = {
    "schema_version": 2, "author_dispatch_id": "S5-qa-automator-1", "reviewer_dispatch_id": "S5-qa-code-critic-2",
    "input_hash": "h-window", "source_revision": "abc123",
    "scope_instances": {"TC-1": ["test_a[x]"], "TC-2": ["test_b[y]"]},
    "required_quality_checks": ["lint"], "quality_receipts": [{"id": "lint", "status": "passed"}],
    "expectation_changes": [], "blocked_by_env": [],
    "instances": [
        {"instance_id": "test_a[x]", "input_hash": "sha-a", "outcome": "passed", "assertion_id": "tests/a.py:9",
         "review": {"verdict": "approved", "input_hash": "sha-a"}, "obligation_ids": ["OB-1"],
         "evidence_refs": [{"path": "run.txt", "sha256": "00"}],
         "probe": {"evidence_ref": "work/p.json", "input_hash": "sha-a"}},
        {"instance_id": "test_b[y]", "input_hash": "sha-b", "outcome": "passed",
         "review": {"verdict": "approved", "input_hash": "sha-b"}, "note": "café"}]}
RECEIPT_BYTES = (
    '{\n  "schema_version": 2,\n  "receipt_kind": "s5_review_window",\n  "immutable": true,\n'
    '  "reviewer_dispatch_id": "S5-qa-code-critic-2",\n  "author_dispatch_id": "S5-qa-automator-1",\n'
    '  "input_hash": "h-window",\n  "scope_instances": {\n    "TC-1": [\n      "test_a[x]"\n    ],\n'
    '    "TC-2": [\n      "test_b[y]"\n    ]\n  },\n  "required_quality_checks": [\n    "lint"\n  ],\n'
    '  "quality_receipts": [\n    {\n      "id": "lint",\n      "status": "passed"\n    }\n  ],\n'
    '  "instances": [\n    {\n      "instance_id": "test_a[x]",\n      "input_hash": "sha-a",\n'
    '      "outcome": "passed",\n      "assertion_id": "tests/a.py:9",\n      "review": {\n'
    '        "verdict": "approved",\n        "input_hash": "sha-a"\n      },\n      "obligation_ids": [\n'
    '        "OB-1"\n      ],\n      "evidence_refs": [\n        {\n          "path": "run.txt",\n'
    '          "sha256": "00"\n        }\n      ],\n      "probe": {\n        "evidence_ref": "work/p.json",\n'
    '        "input_hash": "sha-a"\n      },\n      "assertion_refs": [\n        "tests/a.py:9"\n      ]\n'
    '    },\n    {\n      "instance_id": "test_b[y]",\n      "input_hash": "sha-b",\n'
    '      "outcome": "passed",\n      "review": {\n        "verdict": "approved",\n'
    '        "input_hash": "sha-b"\n      },\n      "note": "café",\n      "assertion_refs": []\n'
    '    }\n  ],\n'
    '  "receipt_hash": "c3d4ee6a097e7db39e76b4dc693d5b44dd714e63edbaebf8683f03bdd313ad85"\n}\n').encode("utf-8")


def the_review_receipt_bytes_did_not_change_with_the_extraction():
    window = copy.deepcopy(RECEIPT_WINDOW)
    root = temp_dir("qa-window-receipt-bytes-")
    try:
        ref = WR.write_review_receipt(root, window, "S5-qa-code-critic-2")
        data = (root / ref["path"]).read_bytes()
        check_eq("the receipt file is byte-identical to the one the writer produced before the extraction",
                 data.replace(b"\r\n", b"\n"), RECEIPT_BYTES)
        check_eq("and its ref is where it was", ref["path"], "work/review-receipts/S5-qa-code-critic-2.json")
        check_eq("the ref's digest is the file's", ref["sha256"], hashlib.sha256(data).hexdigest())
        check_eq("the writer wrote exactly `receipt_dict` of the window", json.loads(data), WR.receipt_dict(window))
        check_eq("`receipt_dict` is pure: the window is as it was", window, RECEIPT_WINDOW)
        check_eq("and it carries the hash of its own content", WR.receipt_dict(window)["receipt_hash"],
                 content_hash({k: v for k, v in WR.receipt_dict(window).items() if k != "receipt_hash"}))
        again = WR.write_review_receipt(root, copy.deepcopy(RECEIPT_WINDOW), "S5-qa-code-critic-2")
        check_eq("a second write of the same window keeps the file as it was", (again, (root / ref["path"]).read_bytes()),
                 (ref, data))
    finally:
        cleanup(root)


def the_item_carries_the_identity_the_run_recorded():
    """HF2-11a (K3): `run_identity` is copied from the latest terminal run row - both per-test shas, and the attempt
    when the row names it - and ONLY then: a row with neither, one, or empty shas, and an instance with no run at all,
    give the item no key (an empty placeholder would read as a value, FR-59). The row is the latest by the clock."""
    project = temp_project("qa-window-run-identity-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        test_file(project, "TC-1", "test_a")

        def block(name, instance, status="passed", **row_over):
            write(task / "work/run-blocks" / name, {
                "schema_version": 2, "block_id": name, "attempt_id": name, "dispatch_id": AUTHOR,
                "input_fingerprint": "fp", "execution_status": status, "purpose": "initial",
                "results": [{"instance_id": instance, "status": status, "attempt_id": name,
                             "input_fingerprint": "fp", **row_over}],
                "evidence": [{"summary": "", "reporter": "none", "report_path": "", "report_sha256": ""}]})
        shas = {"instance_content_sha": "c1", "instance_code_sha": "k1"}
        block("20260924T090000000000Z-old.json", "both[1]", **{"instance_content_sha": "c0", "instance_code_sha": "k0"})
        block("20260924T090100000000Z-new.json", "both[1]", **shas)
        block("20260924T090200000000Z-empty.json", "empty[1]", instance_content_sha="", instance_code_sha="")
        block("20260924T090300000000Z-raw.json", "raw[1]", instance_content_sha="c1")
        block("20260924T090400000000Z-code.json", "code[1]", instance_code_sha="k1")
        block("20260924T090500000000Z-bare.json", "bare[1]")
        block("20260924T090600000000Z-red.json", "red[1]", status="failed", **shas)
        window, items = built_items(task, *[novelty_row(i) for i in
                                            ("both[1]", "empty[1]", "raw[1]", "code[1]", "bare[1]", "red[1]", "none[1]")])
        check_eq("HF2-11a K3: the latest run's two shas and its attempt are copied", items["both[1]"].get("run_identity"),
                 dict(shas, attempt_id="20260924T090100000000Z-new.json"))
        for label in ("empty", "raw", "code", "bare", "none"):
            check_not_in(f"HF2-11a K3: {label} - no `run_identity` key (not a placeholder)", "run_identity",
                         sorted(items[f"{label}[1]"]))
        check_eq("HF2-11a K3: a red run's identity is copied like a green one's", items["red[1]"].get("run_identity"),
                 dict(shas, attempt_id="20260924T090600000000Z-red.json"))
        check_eq("HF2-11a K3: and the record keeps its shape (the extra key is no structural error)",
                 [e for e in C.window_shape_errors(window) if "run_identity" in e], [])
    finally:
        cleanup(project)


def pure_group():
    the_item_carries_the_identity_the_run_recorded()
    the_review_receipt_bytes_did_not_change_with_the_extraction()
    the_owed_pairs_are_copied_from_the_real_detector()
    the_copy_is_stable_and_owed_only()
    the_list_gaps_the_way_the_spec_says()
    an_unmeasured_note_is_never_a_gap()
    the_verdict_names_whose_move_it_is()
    the_red_window_speaks_in_its_own_words()
    a_persons_word_is_not_asked_for_again()
    a_terminal_run_is_the_latest_by_the_clock()
    the_item_carries_the_novelty_its_row_had_resolved()
    the_window_reads_its_row_fields_from_the_carrier()
    a_blocked_instance_is_built_with_its_outcome_and_list()
    a_word_nothing_reads_is_printed_and_changes_nothing()
    a_word_a_reader_passes_is_not_called_unread()
    a_window_of_handed_instances_is_acceptable_as_unresolved()
    a_hand_edited_handed_claim_is_refused_with_its_door()


def a_window_of_handed_cases_with_no_instance_is_acceptable_as_unresolved():
    """t-721 C2-3 (T7, section 3.2): a window whose only gap is `empty_scope` over cases the manifest carries as
    `handed_to_person` exits 0 "acceptable as unresolved" (the finish derives the pair), and says in the case note that
    the manifest carries it. A case the manifest does not carry as handed (nothing, or `impossible`) keeps exit 1."""
    project = temp_project("qa-window-handed-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)

        def story(unresolved):
            write(task / "work/automation-manifest.json", {"schema_version": 2, "tests": [], "unresolved": unresolved})
            return window_main(task)
        handed = {"case": "TC-1", "reason": "handed_to_person", "detail": "by hand - the steps of TC-1"}
        code, out = story([handed])
        check_eq("T7: a window of one handed case with no instance exits 0", code, 0)
        check_in("T7: 'acceptable as unresolved' names the case the person runs",
                 "acceptable as unresolved: 1 instance(s) or case(s) the person runs - TC-1", out)
        check_in("T7: and says the finish derives the pair", "it derives the `unresolved` pair from this record", out)
        real, CONTROLLER.Controller = CONTROLLER.Controller, StandInController
        try:
            with Detector({"pairs": [], "unmeasured": []}):
                _window, notes = WR.build(task, CRITIC)
        finally:
            CONTROLLER.Controller = real
        check_in("T7: the case note (the origin of the gap) says the manifest carries it as handed",
                 "carried by the manifest as handed_to_person: the person runs it", str(notes))
        check_not_in("T7: and not that no row covers it", "no `tests[]` row", str(notes))
        for label, rows in (("no row at all", []), ("an `impossible` row", [dict(handed, reason="impossible")])):
            code, out = story(rows)
            check_eq(f"T7: {label} - the window is not acceptable, exit 1", code, 1)
            check_not_in(f"T7: {label} - and no 'acceptable as unresolved' line", "acceptable as unresolved", out)
    finally:
        cleanup(project)


def an_area_keyed_scope_takes_the_controllers_rule_not_a_looser_one():
    """t-827 FX-2 (F2, section 3.2): `window_record._handed_empty_cases` reads the controller's rule
    (`_cases_without_instances`, EXACT scope keys) - the one `story_step._handed_no_instance` and the S5 completion go
    through. An area-keyed scope (`speakers/TC-009`) over a BARE manifest row is NOT handed by that rule, so the window exits
    1 with no 'acceptable as unresolved' line (it must not promise a pair that `finish` then refuses), and story_step
    agrees: it derives no pair. Since t-845 C3-12 the rule is keyed through `contract.scope_keys`: the same scope over an
    AREA-KEYED row (`speakers/TC-009`) exits 0 and story_step names the case. The control is the exact bare key: the same
    window over a scope `TC-009` and a row `TC-009` exits 0 and story_step names the case."""
    import story_step as SS
    project = temp_project("qa-window-area-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)

        def story(scope, case):
            write(task / "work/automation-manifest.json", {"schema_version": 2, "tests": [], "unresolved": [
                {"case": case, "reason": "handed_to_person", "detail": "by hand - the steps of TC-009"}]})
            StandInController.scope = scope
            try:
                code, out = window_main(task)
                real, CONTROLLER.Controller = CONTROLLER.Controller, StandInController
                try:
                    with Detector({"pairs": [], "unmeasured": []}):
                        window, _notes = WR.build(task, CRITIC)
                finally:
                    CONTROLLER.Controller = real
            finally:
                StandInController.scope = None
            return code, out, SS._handed_no_instance(window, StandInController(task))
        code, out, derived = story(["speakers/TC-009"], "TC-009")
        check_eq("FX-2: area-keyed scope over a bare manifest row - the window is not acceptable, exit 1", code, 1)
        check_not_in("FX-2: area-keyed scope over a bare manifest row - no 'acceptable as unresolved' promise",
                     "acceptable as unresolved", out)
        check_eq("FX-2: area-keyed scope over a bare manifest row - story_step derives no pair either (they agree)", derived, [])
        # t-845 C3-12: the controller's map is keyed through `contract.scope_keys`, so the area-keyed ROW is the case's own key
        code, out, derived = story(["speakers/TC-009"], "speakers/TC-009")
        check_eq("C3-12: area-keyed scope over the area-keyed manifest row - acceptable, exit 0", code, 0)
        check_in("C3-12: ... and names the case",
                 "acceptable as unresolved: 1 instance(s) or case(s) the person runs - speakers/TC-009", out)
        check_eq("C3-12: ... and story_step names the same case (they agree)", derived, ["speakers/TC-009"])
        code, out, derived = story(["TC-009"], "TC-009")
        check_eq("FX-2 control: the exact key is acceptable, exit 0", code, 0)
        check_in("FX-2 control: and names the case", "acceptable as unresolved: 1 instance(s) or case(s) the person runs - TC-009", out)
        check_eq("FX-2 control: story_step names the same case", derived, ["TC-009"])
    finally:
        cleanup(project)


# ---- B-375: an instance the manifest hands to the person has a receipt road; a claim the manifest does not hold has none ---------

HANDED_ROW = {"case": "TC-1", "reason": "handed_to_person", "detail": "web: npx playwright test tests/test_tc-1.py"}


HANDED_FIELDS = {"obligation_refs": [{"obligation_id": "OB-1", "obligation_hash": "oh-1"}],
                 "assertion_id": "tests/test_tc-1.py:3", "defect_location": "src/tc1.py:9"}


def built_with_notes(task: Path) -> tuple:
    """`build` over what is on disk, the stand-in controller and detector: (window, notes)."""
    real, CONTROLLER.Controller = CONTROLLER.Controller, StandInController
    try:
        with Detector({"pairs": [], "unmeasured": []}):
            return WR.build(task, CRITIC)
    finally:
        CONTROLLER.Controller = real


def run_printed(task: Path) -> tuple:
    """`window_record.run` over the stand-in controller: (exit code, what it printed). `build` may be patched by the caller."""
    import contextlib
    import io
    out = io.StringIO()
    real, CONTROLLER.Controller = CONTROLLER.Controller, StandInController
    try:
        with Detector({"pairs": [], "unmeasured": []}), contextlib.redirect_stdout(out):
            code = WR.run(TICKET, CRITIC)
    finally:
        CONTROLLER.Controller = real
    return code, out.getvalue()


def a_window_of_handed_instances_is_acceptable_as_unresolved():
    """W-T1 (B-375, B-1): an instance the manifest hands to the person (a `tests[]` row and a `handed_to_person` row for its case,
    no run block) is built `handed_to_person` with no evidence and no 'no run block' note, and the window exits 0 'acceptable as
    unresolved'. A run of the instance outranks the row: it is built `passed`, and the stale row is a NOTE (info), never a problem
    line (exit 0 stays exit 0). An instance that also proves a case the person does not run is NOT handed (`handed:partial`)."""
    project = temp_project("qa-window-handed-inst-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        sha = test_file(project, "TC-1", "test_a")

        def story(covers=("TC-1",), unresolved=(HANDED_ROW,)):
            row = novelty_row("test_a[x]", covers=list(covers), critic_verdict="unverified", **HANDED_FIELDS)
            write(task / "work/automation-manifest.json", {"schema_version": 2, "tests": [row], "unresolved": list(unresolved)})
        story()
        code, out = window_main(task)
        check_eq("W-T1: a window of one handed instance exits 0", code, 0)
        check_in("W-T1: and names it as the person's", "acceptable as unresolved: 1 instance(s) or case(s) the person runs - test_a[x]", out)
        window, notes = built_with_notes(task)
        item = window["instances"][0]
        check_eq("W-T1: the item is handed, with an empty fingerprint and no evidence",
                 (item["outcome"], item["execution_fingerprint"], item["evidence_refs"]), ("handed_to_person", "", []))
        check_eq("W-T1: it owes no 'no run block' note", [n for n in notes if n[1] in ("evidence", "outcome")], [])
        check_eq("W-T1: and the window's own acceptance reads the same", validate_window(window, task), ["handed_to_person:test_a[x]"])
        # B-1: a run of the instance beside the handed row
        run_block(task, "20260924T090000000000Z-b1.json", "test_a[x]", "fp-a", sha)
        window, notes = built_with_notes(task)
        info: list = []
        problems = WR.verdict(task, window, notes, info)
        check_eq("B-1: the instance with a run is built passed, the run's outcome stands",
                 window["instances"][0]["outcome"], "passed")
        check_eq("B-1: no problem line speaks of the hand-off", [p for p in problems if "handed" in p], [])
        check_eq("B-1: the stale row is one note in `info`, said once", len([i for i in info if "handed_to_person row" in i]), 1)
        check_eq("B-1: the window's acceptance has no handed gap", [g for g in validate_window(window, task) if "handed" in g], [])
        # m-1: a SECOND instance of the same case, un-run, is still handed by that case-level row: the note must not call it stale
        test_file(project, "TC-1", "test_b")
        write(task / "work/automation-manifest.json", {"schema_version": 2, "unresolved": [HANDED_ROW], "tests": [
            novelty_row("test_a[x]", covers=["TC-1"], critic_verdict="unverified", **HANDED_FIELDS),
            novelty_row("test_b[x]", covers=["TC-1"], critic_verdict="unverified", **HANDED_FIELDS)]})
        StandInController.scope = ["TC-1"]
        try:
            window, notes = built_with_notes(task)
            info = []
            problems = WR.verdict(task, window, notes, info)
        finally:
            StandInController.scope = None
        said = [i for i in info if "handed_to_person row" in i]
        check_eq("m-1: test_a passed, test_b handed: one note", len(said), 1)
        check_in("m-1: it says the row still hands the other instance", "still hands test_b[x]", said[0] if said else "")
        check_eq("m-1: and never calls the row stale", [i for i in said if "stale" in i], [])
        check_eq("m-1: the window stays acceptable as unresolved: only test_b's derivable handed gap, no refusal",
                 [p.split(" - ")[0].split(" — ")[0] for p in problems if "handed" in p], ["handed_to_person:test_b[x]"])
        story()
        (task / "work/run-blocks/20260924T090000000000Z-b1.json").unlink()
        # F-4: the instance proves TC-1 (handed) and TC-2 (not): not handed, refused with its repair
        test_file(project, "TC-2", "test_b")
        story(covers=("TC-1", "TC-2"))
        StandInController.scope = ["TC-1", "TC-2"]
        try:
            code, out = window_main(task)
            window, notes = built_with_notes(task)
        finally:
            StandInController.scope = None
        check_eq("W-T1: a half-handed test makes the window not acceptable, exit 1", code, 1)
        check_in("W-T1: the line names the handed and the other case", "(handed to the person) and TC-2 (not handed)", out)
        check_eq("W-T1: and the item is NOT handed", window["instances"][0].get("outcome"), None)
    finally:
        cleanup(project)


def a_hand_edited_handed_claim_is_refused_with_its_door():
    """W-T2 (B-375, W-T5, m-4): a window built `passed` whose item is edited to `handed_to_person` while the manifest holds no such
    row is `handed_unconfirmed:<iid>` (the door is named by the window_record road; at accept it is the bare gap); no pair is derived over it (`story_step._derived_pair`), and `run` exits 1
    with no 'acceptable as unresolved' line even when the edited window reaches it (the kind is not in `derivable`)."""
    import story_step as SS
    project = temp_project("qa-window-handed-claim-")
    use_project(project)
    try:
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work").mkdir(parents=True)
        sha = test_file(project, "TC-1", "test_a")
        write(task / "work/automation-manifest.json", {"schema_version": 2, "unresolved": [],
                                                       "tests": [novelty_row("test_a[x]", critic_verdict="unverified", **HANDED_FIELDS)]})
        run_block(task, "20260924T090000000000Z-b1.json", "test_a[x]", "fp-a", sha)
        window, notes = built_with_notes(task)
        check_eq("W-T2: the control - the same window as built is not a handed one", window["instances"][0]["outcome"], "passed")
        item = window["instances"][0]
        item.update(outcome="handed_to_person", execution_fingerprint="", evidence_refs=[])
        lines = WR.verdict(task, window, notes)
        claim = [line for line in lines if line.startswith("handed_unconfirmed:test_a[x]")]
        check_eq("W-T2: the claim is refused, one line", len(claim), 1)
        check_in("W-T2: with the door - the manifest row through manifest_put.py", "manifest_put.py --task <T> --fragment", claim[0])
        check_in("W-T2: and the rebuild", "window_record.py", claim[0])
        check_not_in("W-T2: and never `run_suite.py` (the profile is the person's)", "run_suite.py", claim[0])
        check_eq("W-T2: never a product finding or a handed gap", [l for l in lines if l.startswith(("product:", "handed_to_person"))], [])
        check_eq("W-T2: no pair is derived over it", SS._derived_pair(validate_window(window, task), "shown"), ())
        check("W-T5: the gap kind has its origin row, door included",
              WR.HANDED_UNCONFIRMED_KIND in WR.GAP_ORIGIN and "manifest_put.py" in WR.GAP_ORIGIN[WR.HANDED_UNCONFIRMED_KIND][1])
        # m-4: through `run`, with `build` returning the edited window (a rebuild would re-derive it from the manifest)
        real = WR.build
        WR.build = lambda task_root, dispatch: (copy.deepcopy(window), notes)
        try:
            code, out = run_printed(task)
        finally:
            WR.build = real
        check_eq("m-4: `run` exits 1 on the unconfirmed claim", code, 1)
        check_not_in("m-4: and never says 'acceptable as unresolved'", "acceptable as unresolved", out)
        check_in("m-4: the gap is printed", "handed_unconfirmed:test_a[x]", out)
    finally:
        cleanup(project)


def a_headline_match_keeps_the_failures_detail():
    """W-T3 (B-380): a probe whose reason matched on the failure's first line keeps the failure's lines in `reason_detail` (the pair
    `expected_reason`/`actual_reason` is byte for byte what it was) and the stdout carries the note; a whole-text match carries
    `rule: whole` and no note."""
    code, out, probe, _gaps = window_for_reasons("headline", "Assert.Equal() Failure", "Assert.Equal() Failure\nExpected: 4\nActual:   0")
    check_eq("W-T3: the detail is recorded", probe["reason_detail"],
             {"rule": "headline", "actual_lines": ["Assert.Equal() Failure", "Expected: 4", "Actual: 0"], "actual_lines_total": 3})
    check_in("W-T3: the note names what was not compared",
             "note: probe reason matched on the failure's first line only (\"Assert.Equal() Failure\"); 2 other line(s) of the "
             "failure were not compared: \"Expected: 4\" | \"Actual: 0\" (test_a[x])", out)
    check("W-T3: and the window is accepted as before", code == 0, out)
    code, out, probe, _gaps = window_for_reasons("whole", "Expected the cart\ntotal to be 4", "AssertionError:  Expected the   cart total\nto be 4")
    check_eq("W-T3: a whole match records its rule", probe["reason_detail"]["rule"], "whole")
    check_not_in("W-T3: and prints no such note", "first line only", out)


def an_older_receipt_without_the_reason_detail_is_not_a_collision():
    """W-T4 (B-380, E11): the review receipt is immutable; one written by 0.10.8 holds no `probe.reason_detail`. A rebuild of the same
    window leaves its bytes alone and does not raise; a change of any other field is still a collision."""
    project = temp_project("qa-window-detail-receipt-")
    use_project(project)
    try:
        task, _controller = a_story_at_s5(project, "Assert.Equal() Failure", "Assert.Equal() Failure\nExpected: 4\nActual:   0")
        first = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        receipt_path = task / "work/review-receipts" / (CRITIC + ".json")
        check_eq("W-T4: the receipt is written", (first.returncode, receipt_path.is_file()), (0, True))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        stripped = 0
        for item in receipt["instances"]:
            if isinstance(item.get("probe"), dict) and item["probe"].pop("reason_detail", None) is not None:
                stripped += 1
        check("W-T4: the receipt held the field on the probe instance", stripped == 1, str(stripped))
        receipt.pop("receipt_hash")
        receipt["receipt_hash"] = content_hash(receipt)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        before = digest(receipt_path)
        second = run_script("window_record.py", "--task", TICKET, "--dispatch", CRITIC, "--review-receipt", cwd=project)
        check_eq("W-T4: the rebuild exits 0, no raise", second.returncode, 0)
        check_not_in("W-T4: and no collision is printed", "immutable review receipt collision", second.stdout + second.stderr)
        check_eq("W-T4: the receipt's bytes are unchanged", (digest(receipt_path), before == digest(receipt_path)), (before, True))
        window = json.loads((task / "work/windows" / (CRITIC + ".json")).read_text(encoding="utf-8"))
        changed = copy.deepcopy(window)
        changed["instances"][0]["input_hash"] = "other-bytes"
        try:
            WR.write_review_receipt(task, changed, CRITIC)
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in("W-T4: a change of any other field is still a collision", "immutable review receipt collision", raised)
    finally:
        cleanup(project)


def main():
    if sys.argv[1:] == ["pure"]:
        pure_group()
        finish("window record (pure group)")
        return
    the_record_is_built_and_accepted()
    a_second_review_receipt_writes_nothing()
    a_stale_projection_is_not_a_refused_receipt()
    a_trx_headline_receipt_is_accepted()
    an_old_receipt_with_a_whole_text_match_is_still_accepted()
    a_headline_match_keeps_the_failures_detail()
    an_older_receipt_without_the_reason_detail_is_not_a_collision()
    pure_group()
    the_changes_on_one_story()
    the_novelty_reaches_the_window_and_its_acceptance_on_a_story()
    a_window_with_only_good_verdicts_is_accepted_as_before()
    a_rejected_review_on_a_run_instance_is_receipted_and_sent_back()
    per_test_fields_are_copied_from_the_receipt_or_left_out()
    a_live_receipt_on_the_row_reaches_the_window()
    a_receipt_for_other_bytes_is_not_the_windows_probe()
    an_old_mutable_probe_record_counts_as_live_in_the_window()
    an_unknown_level_and_a_false_claim_are_named_with_their_doors()
    the_vocabulary_missing_is_said_not_guessed()
    a_missing_run_block_is_named_with_its_command()
    a_pending_instance_owes_no_probe_and_a_substituted_one_does()
    a_pending_instance_window_is_shaped_and_a_claim_alone_is_refused()
    a_window_of_handed_cases_with_no_instance_is_acceptable_as_unresolved()
    an_area_keyed_scope_takes_the_controllers_rule_not_a_looser_one()
    finish("window record")


if __name__ == "__main__":
    main()
