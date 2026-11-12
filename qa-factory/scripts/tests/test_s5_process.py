#!/usr/bin/env python3
"""A repair round is a round about the test, and a UI window is small and shares its notes.

Session 57cf578c (TP1-15045, 0.7.6) spent 12.5 hours and 16 S5 dispatches on 14 cases
and delivered four. Its repair rounds went to manifest bookkeeping, an env file the conftest
did not read, and the critic's own five parallel UI runs on a one-account stand; the one
finding that WAS about a test — a `sleep` in TC-002, five lines — arrived in the last review
and could not be fixed because "the cap was reached". Its UI windows held six and four cases
and each re-learned the UI repository at 130-178 tool calls.

A mechanical fix made on the critic's word is closed by the author's own green run on the
new bytes (`mechanical_round` on the window record), never by a second critic — 0.7.8's
"closing" reviewer dispatch is gone.

The dispatch shapes below are the ones that run's `controller.json` holds.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, check_not_in, finish, s5_window_form, temp_dir, cleanup  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import waiver  # noqa: E402
from controller import (Controller, mechanical_rounds, projection, repair_ledger,  # noqa: E402
                        repair_rounds, split_windows)
from event_store import StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
from test_controller_rework_scope import evidence, plan_row  # noqa: E402


def receipt(identifier, role="qa-automator", scope=("TC-1", "TC-2"), status="accepted", **extra):
    return dict({"id": identifier, "stage": "S5", "role": role, "scope": list(scope),
                 "status": status}, **extra)


def ledger_of(*receipts):
    return {r["id"]: r for r in receipts}


# --- what counts as a round ------------------------------------------------------------------

def only_a_round_about_the_test_is_counted():
    window = receipt("next")
    real = ledger_of(
        receipt("S5-qa-automator-1", status="never_started"),
        receipt("S5-qa-automator-2", status="superseded"),
        receipt("S5-qa-automator-3", parent_retry="S5-qa-automator-2"),
        receipt("S5-qa-automator-4", purpose="repair_verify"),
        receipt("S5-qa-automator-5", purpose="repair_verify"))
    check_eq("receipts written by 0.7.6 carry no cause and every round counts as before",
             repair_rounds(real, window), 2)
    check_eq("a resumed opener is still the opener, not a lost round",
             [r["id"] for r in repair_ledger(real, window)["rounds"]],
             ["S5-qa-automator-4", "S5-qa-automator-5"])

    real["S5-qa-automator-4"]["repair_cause"] = "tooling"        # manifest bookkeeping
    real["S5-qa-automator-5"]["repair_cause"] = "environment"    # the env file conftest reads
    check_eq("bookkeeping and a missing env file spend nothing", repair_rounds(real, window), 0)
    check_eq("and the ledger says what each round was for",
             repair_ledger(real, window)["by_cause"], {"tooling": 1, "environment": 1})

    real["S5-qa-automator-6"] = receipt("S5-qa-automator-6", repair_cause="reviewer_error")
    real["S5-qa-automator-7"] = receipt("S5-qa-automator-7", repair_cause="mechanical")
    real["S5-qa-automator-8"] = receipt("S5-qa-automator-8", repair_cause="test_defect")
    check_eq("the reviewer's own mistake and a mechanical fix spend nothing either",
             repair_rounds(real, window), 1)
    check_eq("mechanical rounds are counted on their own", mechanical_rounds(real, window), 1)
    real["S5-qa-automator-9"] = receipt("S5-qa-automator-9", repair_cause="nonsense")
    check_eq("an unknown cause on an old receipt reads as a round about the test",
             repair_rounds(real, window), 2)

    # A repair round that ran out of turns and was resumed is ONE round with its cause.
    chain = ledger_of(receipt("a1"), receipt("a2", status="superseded", repair_cause="environment"),
                      receipt("a3", parent_retry="a2"))
    check_eq("a resumed round keeps the cause it was opened with",
             repair_ledger(chain, window)["rounds"], [{"id": "a3", "cause": "environment"}])
    check_eq("another window of the same role spends nobody's cap",
             repair_rounds(real, receipt("x", scope=("TC-9",))), 0)
    check_eq("the reviewer's rounds are its own",
             repair_rounds(real, receipt("x", role="qa-code-critic")), 0)


# --- the cap, the mechanical round and the person's word ---------------------------------------

def s5_task(root, cases=("TC-1", "TC-2"), levels=None):
    """A task accepted through S0..S4 with an approved plan of `automate` rows."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    c = Controller(root)
    c.apply("initialize", {"scope": list(cases), "source_revision": "src-1",
                           "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    rows = []
    for index, case in enumerate(cases, start=1):
        row = plan_row(index, "automate")
        row["required_scenarios"] = [case]
        row["level"] = (levels or {}).get(case, "api")
        rows.append(row)
    BASE.seed_plan(root, rows)
    (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": case, "version": "cv_1"} for case in cases]}), encoding="utf-8")
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                "authorization_source": "human", "source_revision": "src-1", "scope": list(cases),
                "input_revision": "src-1", "idempotency_key": "gate-a"}
    c.apply("decision", BASE.bind_gate_a(root, decision))
    return c


def dispatch(c, root, identifier, role="qa-automator", scope=("TC-1", "TC-2"), accept=True, **extra):
    with s5_window_form(c, root):       # SC1-14 B1b: the plan order is not what these keys are about
        c.apply("dispatch", dict({"id": identifier, "stage": "S5", "role": role, "scope": list(scope),
                                  "input_hash": "h", "budget": {}, "known_paths": {},
                                  "idempotency_key": identifier}, **extra))
    if accept:
        # These windows are mid-flight: the critic is followed by a mechanical author round,
        # so its acceptance says what is still open. A bare `stage_complete: false` on the
        # role that closes S5 is refused since TP2-2553.
        c.apply("accept", {"id": identifier, "status": "accepted", "stage_complete": False,
                           "unresolved": True, "reason": "the window's repair round is still open",
                           "evidence_refs": [evidence(root, identifier + ".txt")],
                           "idempotency_key": identifier + "-ok"})


def refusal(call):
    try:
        call()
    except (StateConflict, ValueError) as exc:
        return str(exc)
    return ""


def the_cap_names_what_it_counted():
    root = temp_dir("qa-s5-cap-")
    try:
        c = s5_task(root)
        dispatch(c, root, "a1")
        dispatch(c, root, "a2", repair_cause="tooling", reason="manifest rows had no reporter id")
        dispatch(c, root, "a3", repair_cause="environment", reason="NON_OWNER_* not in the .env conftest loads")
        dispatch(c, root, "a4")
        dispatch(c, root, "a5", repair_cause="test_defect")
        check_eq("five dispatches, two of them about the test",
                 repair_rounds(c.state()["dispatches"], receipt("x")), 2)
        refused = refusal(lambda: dispatch(c, root, "a6"))
        check_in("the third round about the test is refused", "repair round(s) about the test", refused)
        check_in("naming the rounds it counted", "a4, a5", refused)
        check_in("and the ones it did not, with their cause", "a2 (tooling), a3 (environment)", refused)
        check_in("and how a round that is not about the test is sent", "repair_cause", refused)
        check_in("and the person's way past it", "waiver.py", refused)
        check_not_in("whose block words are in the refused line", '--block "repair cap"', refused)

        # The 15045 sleep: found in the last review, five lines, "the cap was reached".
        dispatch(c, root, "a6", repair_cause="mechanical",
                 reason="TC-002: page.wait_for_timeout(500) -> expect(popup).to_be_visible()")
        check_eq("a mechanical fix goes to the author past the cap",
                 c.state()["dispatches"]["a6"]["repair_cause"], "mechanical")
        second = refusal(lambda: dispatch(c, root, "a7", repair_cause="mechanical", reason="again"))
        check_in("once per window", "mechanical repair round(s); the cap is 1", second)
        check_in("with the person's way past that too (C1-5a: the pass of that round)",
                 '--block "mechanical pass 2 for qa-automator on S5:', second)
        check_not_in("and not the stage-wide word of the old door", '--block "mechanical repair round"', second)
        # The critic is not dispatched again after a mechanical fix: the author's green run
        # on the new bytes closes the round (S4 closes exact replacements by code the same way).
        again = refusal(lambda: dispatch(c, root, "k1", role="qa-code-critic",
                                         repair_cause="mechanical", reason="check the sleep fix"))
        check_in("a reviewer dispatch for a mechanical round is refused",
                 "not dispatched for a mechanical repair round", again)
        check_in("saying what closes the round instead", "author's own green run", again)
        check_in("with the person's way past it (C1-5a: the pass of that round)",
                 '--block "mechanical pass 1 for qa-code-critic on S5:', again)
        check_not_in("and not the stage-wide word of the old door", '--block "mechanical repair round"', again)
        check_eq("only the author's dispatches count against the mechanical cap",
                 mechanical_rounds(c.state()["dispatches"], receipt("x")), 1)
        check_in("an unknown cause is refused with the closed list", "reviewer_error",
                 refusal(lambda: dispatch(c, root, "a7", repair_cause="weather", reason="x")))
        check_in("B-364: the closed list names the driver's word too", "ticket_changed",
                 refusal(lambda: dispatch(c, root, "a7", repair_cause="weather", reason="x")))
        check_in("a round that spends nothing must say what happened", "needs `reason`",
                 refusal(lambda: dispatch(c, root, "a7", repair_cause="environment")))
        dispatch(c, root, "a7", repair_cause="reviewer_error",
                 reason="the critic ran five UI instances at once on a one-account stand")
        check_eq("a round caused by the reviewer passes at the cap",
                 c.state()["dispatches"]["a7"]["status"], "accepted")

        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"dispatch": {"mechanical_rounds": 2}}), encoding="utf-8")
        dispatch(c, root, "a8", repair_cause="mechanical", reason="raw locator -> page object")
        check_eq("the project's own mechanical cap is what decides",
                 mechanical_rounds(c.state()["dispatches"], receipt("x")), 2)

        pipeline_path = root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        waiver.apply_stage_override(pipeline, "S5", "repair round", "one more, it is one line",
                                    waiver.now_iso())
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        dispatch(c, root, "a9")
        check_eq("a person's word buys a round about the test",
                 c.state()["dispatches"]["a9"]["status"], "accepted")

        packet = c.prepare({"stage": "S5", "role": "qa-automator", "scope": ["TC-1", "TC-2"]})
        check_eq("prepare tells the orchestrator the numbers instead of leaving them to a prompt",
                 (packet["repair_budget"]["counted"], packet["repair_budget"]["cap"],
                  packet["repair_budget"]["mechanical"], packet["repair_budget"]["mechanical_cap"]),
                 (3, 2, 2, 2))
        passes = packet["repair_budget"]["passes"]
        check_eq("C1-5a: and the round pass of BOTH roles of the loop, the next round each would spend",
                 sorted(passes), ["qa-automator", "qa-code-critic"])
        check_in("C1-5a: the author's pass names round 4 (counted 3) and its role", "round pass 4 for qa-automator on S5:",
                 passes["qa-automator"])
        check_in("C1-5a: the critic's pass names its own round 1 (it has had none)", "round pass 1 for qa-code-critic on S5:",
                 passes["qa-code-critic"])
    finally:
        cleanup(root)


def run_block(root, name, dispatch_id, fingerprint, test_sha, instance, status="passed", job=True,
              test_files=None):
    """What `run_suite.py` leaves after a run: the block under `work/run-blocks/` (the shape of the
    blocks of session 57cf578c, cut to the fields acceptance reads) and the job it came from under
    `state/execution-jobs/` (its `job_id` is the block's `attempt_id`). The job's request records
    the RAW sha256 of the test file it ran; the block's own test_content_sha is the run's
    fingerprint over test and helper files, another quantity (t-016 Amendment 4)."""
    folder = root / "work" / "run-blocks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({
        "schema_version": 2, "block_id": name, "attempt_id": name, "dispatch_id": dispatch_id,
        "purpose": "repair_verify", "input_fingerprint": fingerprint,
        "source_fingerprint": {"source_sha": "src-1", "test_content_sha": "fingerprint-of-" + test_sha},
        "execution_status": status,
        "results": [{"instance_id": instance, "status": status, "attempt_id": name}]}),
        encoding="utf-8")
    if job:
        jobs = root / "state" / "execution-jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        records = test_files or [{"path": str(root / "tests" / "test_x.py"), "sha256": test_sha, "kind": "test_files"}]
        (jobs / f"job-{name}.json").write_text(json.dumps({
            "job_id": name, "status": "completed", "request": {
                "dispatch_id": dispatch_id, "input_fingerprint": fingerprint,
                "fingerprint_files": records + [{"path": str(root / "tests" / "conftest.py"),
                                                 "sha256": "c" * 64, "kind": "helper_files"}]}}),
            encoding="utf-8")
    return path


ROUND = {"author_dispatch_id": "a2", "reviewer_dispatch_id": "k1", "reviewed_input_hash": "H0"}


def a_mechanical_fix_is_closed_by_the_authors_green_run():
    """The review and the probe stay bound to the bytes they were made on; a mechanical fix
    made on the critic's word is proved by the author's own green run on the new bytes —
    a run block of the mechanical dispatch on the instance's current hash — never by a
    second critic."""
    from acceptance import validate_window
    root = temp_dir("qa-s5-bytes-")
    try:
        def window(now, round_=None, fingerprint="fp-1"):
            record = {"required_quality_checks": [], "instances": [{
                "instance_id": "test_x", "input_hash": now, "outcome": "passed",
                "execution_fingerprint": fingerprint,
                "review": {"verdict": "approved", "input_hash": "H0"},
                "change_disposition": "new_or_changed", "change_basis_ref": "diff",
                "probe": {"verdict": "intended_failure", "input_hash": "H0",
                          "expected_location": "a", "actual_location": "a",
                          "expected_reason": "r", "actual_reason": "r",
                          "failure_kind": "assertion"},
                "evidence_refs": [evidence(root, "proof.json")]}]}
            if round_ is not None:
                record["mechanical_round"] = round_
            return record

        check_eq("a window reviewed and probed on its final bytes is accepted",
                 validate_window(window("H0"), root), [])
        check_eq("a sleep removed AFTER the review leaves both proofs stale",
                 validate_window(window("H1"), root), ["sensitivity:test_x", "stale_review:test_x"])
        check_eq("a mechanical_round record alone proves nothing: no green run on the new bytes yet",
                 validate_window(window("H1", ROUND), root),
                 ["mechanical_green:test_x", "sensitivity:test_x", "stale_review:test_x"])
        run_block(root, "b1", "a2", "fp-1", "H1", "test_x")
        check_eq("the author's green run block on the new bytes closes the round",
                 validate_window(window("H1", ROUND), root), [])
        check_eq("without the record the same block is not read",
                 validate_window(window("H1"), root), ["sensitivity:test_x", "stale_review:test_x"])
        check_eq("a block of another dispatch is not the mechanical author's proof",
                 validate_window(window("H1", dict(ROUND, author_dispatch_id="a9")), root),
                 ["mechanical_green:test_x", "sensitivity:test_x", "stale_review:test_x"])
        check_eq("a block on other bytes than the instance claims is not either",
                 validate_window(window("H2", ROUND), root),
                 ["mechanical_green:test_x", "sensitivity:test_x", "stale_review:test_x"])
        check_eq("nor a block the instance's execution_fingerprint does not name",
                 validate_window(window("H1", ROUND, fingerprint="fp-other"), root),
                 ["mechanical_green:test_x", "sensitivity:test_x", "stale_review:test_x"])
        run_block(root, "b2", "a2", "fp-2", "H1", "test_x", status="failed")
        check_eq("a red run of the author is no proof",
                 validate_window(window("H1", ROUND, fingerprint="fp-2"), root),
                 ["mechanical_green:test_x", "sensitivity:test_x", "stale_review:test_x"])
        check_eq("a review bound to a third hash is stale whatever the record says",
                 validate_window(window("H1", dict(ROUND, reviewed_input_hash="H9")), root),
                 ["sensitivity:test_x", "stale_review:test_x"])
        check_eq("a malformed record is no record",
                 validate_window(window("H1", {"author_dispatch_id": "a2"}), root),
                 ["sensitivity:test_x", "stale_review:test_x"])
        # Amendment 4: the bytes come from the job the block names; missing pieces are named
        from acceptance import green_on_current_bytes_why
        run_block(root, "b3", "a2", "fp-3", "H1", "test_x", job=False)
        green, why = green_on_current_bytes_why(window("H1", ROUND, fingerprint="fp-3")["instances"][0],
                                                window("H1", ROUND, fingerprint="fp-3"), root)
        check_eq("a block whose job is gone is not green", green, False)
        check_in("...and says which job is missing", "names job b3, and no such job is under state/execution-jobs/",
                 why)
        run_block(root, "b4", "a2", "fp-4", "H1", "test_x", test_files=[
            {"path": str(root / "tests" / "test_x.py"), "sha256": "H1", "kind": "test_files"},
            {"path": str(root / "tests" / "test_y.py"), "sha256": "H7", "kind": "test_files"}])
        green, why = green_on_current_bytes_why(window("H1", ROUND, fingerprint="fp-4")["instances"][0],
                                                window("H1", ROUND, fingerprint="fp-4"), root)
        check_eq("two test files and no manifest to say which is the instance's: not green", green, False)
        check_in("...and says why", "names no test file for this instance and the job's request records 2 test files",
                 why)
        (root / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [
            {"instance_id": "test_x", "file": "tests/test_x.py"}]}), encoding="utf-8")
        check_eq("with the manifest naming the file, its record decides: green",
                 green_on_current_bytes_why(window("H1", ROUND, fingerprint="fp-4")["instances"][0],
                                            window("H1", ROUND, fingerprint="fp-4"), root), (True, ""))
        green, why = green_on_current_bytes_why(window("H7", ROUND, fingerprint="fp-4")["instances"][0],
                                                window("H7", ROUND, fingerprint="fp-4"), root)
        check_eq("another file's bytes are not this instance's", green, False)
        check_in("...named with both hashes", "ran the test file as sha256 H1, the instance now holds H7", why)
        (root / "work" / "automation-manifest.json").unlink()
    finally:
        cleanup(root)


def the_mechanical_author_completes_the_window():
    """S5 completion by the author's mechanical dispatch: the critic reviewed and probed,
    the fix was made on its word, the author ran green on the new bytes — no second critic."""
    from event_store import content_hash
    root = temp_dir("qa-s5-complete-")
    try:
        c = s5_task(root, ("TC-1",))
        check_eq("a fresh task is a coverage v2 task, so the completion rule with roles applies",
                 c.state().get("coverage_contract_version"), 2)
        dispatch(c, root, "a1", scope=("TC-1",))
        dispatch(c, root, "k1", role="qa-code-critic", scope=("TC-1",))
        dispatch(c, root, "a2", scope=("TC-1",), accept=False, repair_cause="mechanical",
                 reason="TC-1: page.wait_for_timeout(500) -> expect(popup).to_be_visible()")
        obligation = next(ob for row in json.loads((root / "work/test-plan.json").read_text(encoding="utf-8"))["rows"]
                          for ob in row.get("coverage_obligations") or [])
        refs = [{"obligation_id": obligation["obligation_id"], "obligation_hash": content_hash(obligation)}]
        proof = evidence(root, "proof.json")

        def window(round_=None, probe_over=None):
            record = {"schema_version": 2, "input_hash": "h", "required_quality_checks": [],
                      "author_dispatch_id": "a1", "reviewer_dispatch_id": "k1",
                      "quality_receipts": [], "scope_instances": {"TC-1": ["test_x"]},
                      "instances": [{"schema_version": 2, "instance_id": "test_x", "input_hash": "H1",
                                     "outcome": "passed", "execution_fingerprint": "fp-1",
                                     "review": {"verdict": "approved", "input_hash": "H0"},
                                     "change_disposition": "new_or_changed", "change_basis_ref": "diff",
                                     "obligation_ids": [obligation["obligation_id"]], "obligation_refs": refs,
                                     "obligation_hash": content_hash(refs), "assertion_id": "t.py:9",
                                     "defect_location": "src.py:4",
                                     "probe": {"verdict": "intended_failure", "input_hash": "H0",
                                               "expected_location": "a", "actual_location": "a",
                                               "expected_reason": "r", "actual_reason": "r",
                                               "failure_kind": "assertion",
                                               # D-0010: the check is live - an assertion mutation
                                               # is what `probe_by_code.py` makes and it owes no more
                                               "mutation_kind": "assertion", "proof_level": "live",
                                               "obligation_ids": [obligation["obligation_id"]],
                                               "obligation_refs": refs, "obligation_hash": content_hash(refs),
                                               "assertion_id": "t.py:9", "defect_location": "src.py:4",
                                               "evidence_ref": proof["path"]},
                                     "evidence_refs": [proof]}]}
            if round_ is not None:
                record["mechanical_round"] = round_
            record["instances"][0]["probe"].update(probe_over or {})
            return record

        def complete(round_=None, key="done", probe_over=None):
            record = window(round_, probe_over)
            (root / "work").mkdir(exist_ok=True)
            (root / "work" / "s5-window.json").write_text(json.dumps(record), encoding="utf-8")
            receipt = {"path": "work/s5-window.json",
                       "sha256": hashlib.sha256((root / "work" / "s5-window.json").read_bytes()).hexdigest()}
            return c.apply("accept", {"id": "a2", "status": "accepted", "stage_complete": True,
                                      "window": record, "evidence_refs": [proof, receipt],
                                      "idempotency_key": key})

        refused = refusal(lambda: complete(key="no-record"))
        check_in("an author dispatch without the record cannot complete the window",
                 "no well-formed `mechanical_round`", refused)
        check_in("with the person's way past it", '--block "mechanical round"', refused)
        refused = refusal(lambda: complete(dict(ROUND, reviewer_dispatch_id="a1"), key="wrong-reviewer"))
        check_in("the round must name the accepted critic of this window",
                 "reviewer_dispatch_id is a1", refused)
        refused = refusal(lambda: complete(ROUND, key="no-green"))
        check_in("with the record but no green run on the new bytes the window has gaps",
                 "mechanical_green:test_x", refused)
        run_block(root, "b1", "a2", "fp-1", "H1", "test_x")
        refused = refusal(lambda: complete(ROUND, key="odd-level", probe_over={"proof_level": "mystery"}))
        check_in("a probe of a level the vocabulary does not know is its own gap", "probe_level:test_x", refused)
        refused = refusal(lambda: complete(ROUND, key="false-claim",
                                           probe_over={"proof_level": "catches_broken_product"}))
        check_in("a probe that claims to catch a broken product with an assertion mutation is refused",
                 "probe_mutation_kind:test_x", refused)
        complete(ROUND)
        state = c.state()
        check_eq("the author's mechanical dispatch completed S5",
                 (state["dispatches"]["a2"]["status"], state["stages"]["S5"]["status"]),
                 ("accepted", "completed"))
        # Gate B and delivery read the same window through `coverage_contract.witnessed_binding`.
        from coverage_contract import coverage_projection
        binding = {"obligation_id": obligation["obligation_id"], "obligation_hash": content_hash(obligation),
                   "instance_ids": ["test_x"], "design_assessment": "sufficient", "code_validity": "valid",
                   "sensitivity": "proven", "proof_kind": "executed_red_probe", "probe_receipt_ref": proof["path"],
                   "change_disposition": "new_or_changed", "change_basis_ref": "diff",
                   "assertion_refs": ["t.py:9"], "quality_not_applicable_reason": "no quality gate",
                   "review_receipt_ref": "work/s5-window.json"}
        report = {"current_results": [{"instance_id": "test_x", "status": "passed", "input_fingerprint": "fp-1"}]}
        projected = coverage_projection(root, report, {"obligation_bindings": [binding]})
        check_eq("and the obligation is verified through the mechanical round at the gate",
                 [o["verified"] for o in projected["obligations"]], [True])
    finally:
        cleanup(root)


def the_critic_closes_a_window_the_stand_blocked():
    """t-219 (B6): an instance the stand blocked has no run, so no fingerprint - the controller exempts exactly
    that outcome from the rule - and its gap closes the window only as an unresolved acceptance that NAMES
    `blocked_by_env` (the manifest, the ledger and gate B read the same word). A claim with no row behind it in the
    manifest is a plain `product:` gap: `validate_window` re-derives the block, the outcome alone buys nothing."""
    from controller import names_blocked
    from event_store import content_hash
    root = temp_dir("qa-s5-blocked-")
    try:
        c = s5_task(root, ("TC-1",))
        dispatch(c, root, "a1", scope=("TC-1",))
        dispatch(c, root, "k1", role="qa-code-critic", scope=("TC-1",), accept=False)
        obligation = next(ob for row in json.loads((root / "work/test-plan.json").read_text(encoding="utf-8"))["rows"]
                          for ob in row.get("coverage_obligations") or [])
        refs = [{"obligation_id": obligation["obligation_id"], "obligation_hash": content_hash(obligation)}]
        findings = evidence(root, "critic-findings.md", "a static review: the stand never loaded the page")
        fix = {"kind": "service", "where": "frontend localhost:5173", "change": "the page must load", "restart": "re-run"}
        row = {"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["test_x"], "detail": "Loading", "remedy": fix}

        def put_manifest(unresolved):
            (root / "work").mkdir(exist_ok=True)
            (root / "work" / "automation-manifest.json").write_text(json.dumps({
                "tests": [{"instance_id": "test_x", "case": "TC-1", "covers": ["TC-1"], "status": "red",
                           "critic_verdict": "unverified", "change_disposition": "new_or_changed",
                           "sensitivity_proof_missing_reason": "blocked_by_env: " + fix["where"]}],
                "unresolved": unresolved}), encoding="utf-8")
        record = {"schema_version": 2, "input_hash": "h", "required_quality_checks": [], "quality_receipts": [],
                  "author_dispatch_id": "a1", "reviewer_dispatch_id": "k1", "scope_instances": {"TC-1": ["test_x"]},
                  "instances": [{"schema_version": 2, "instance_id": "test_x", "input_hash": "H1",
                                 "outcome": "blocked_by_env", "execution_fingerprint": "",
                                 "review": {"verdict": "unverified", "input_hash": "H0"},
                                 "change_disposition": "new_or_changed", "change_basis_ref": "diff",
                                 "obligation_ids": [obligation["obligation_id"]], "obligation_refs": refs,
                                 "obligation_hash": content_hash(refs), "assertion_id": "t.py:9",
                                 "defect_location": "src.py:4", "evidence_refs": []}],
                  "blocked_by_env": []}

        def complete(key, **more):
            return c.apply("accept", {"id": "k1", "status": "accepted", "stage_complete": True, "window": record,
                                      "evidence_refs": [findings], "idempotency_key": key, **more})
        put_manifest([row])
        for label, more in (("no pair", {}), ("a pair that does not name the word",
                                              {"unresolved": "could_not_judge", "reason": "the critic's own words"})):
            refused = refusal(lambda: complete("plain-" + label[:2], **more))
            check_in(f"B6: {label}: refused, naming the gap", "blocked_by_env:test_x", refused)
            check_in(f"B6: {label}: the words expected", "naming `blocked_by_env`", refused)
            check_in(f"B6: {label}: and the command that derives the pair", "story_step.py finish --task", refused)
        check_eq("B6: nothing was accepted by the refusals", c.state()["dispatches"]["k1"]["status"], "running")
        put_manifest([])
        refused = refusal(lambda: complete("claim"))
        check_in("B3: the outcome claimed with no unresolved row behind it is a `product:` gap", "product:test_x", refused)
        check_not_in("B3: and not a blocked one", "the stand blocked", refused)
        put_manifest([row])
        complete("named", unresolved="blocked_by_env", reason="blocked_by_env: test_x - the page stayed on Loading")
        state = c.state()
        check_eq("B6: naming the word closes the window - no fingerprint is demanded of an instance that never ran",
                 (state["dispatches"]["k1"]["status"], state["stages"]["S5"]["status"],
                  state["dispatches"]["k1"].get("unresolved")), ("accepted", "completed", "blocked_by_env"))
        check_eq("names_blocked reads the word the way names_handed does",
                 [names_blocked({"unresolved": True, "reason": "blocked_by_env: x"}),
                  names_blocked({"unresolved": [{"reason": "blocked_by_env"}]}),
                  names_blocked({"unresolved": True, "reason": "gaps"}), names_blocked({})], [True, True, False, False])
    finally:
        cleanup(root)


# --- a suspect stand is not the test's fault ---------------------------------------------------

def run_summary(root, name, signal=None, age_s=0):
    folder = root / "evidence" / "runs" / name
    folder.mkdir(parents=True, exist_ok=True)
    summary = {"task": root.name, "label": name, "exit_code": 1}
    if signal:
        summary["stand_signal"] = signal
    path = folder / f"{name}.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    (folder / "request.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    stamp = time.time() + 2 - age_s
    os.utime(path, (stamp, stamp))
    os.utime(folder / "request.json", (stamp + 1, stamp + 1))
    return path


SIGNAL = {"signal": "stand_suspect", "reason": "same_failure",
          "evidence": ["TC-001", "TC-002", "TC-003"],
          "sentence": "Three different cases failed in a row with the same line."}


def a_stand_signal_makes_the_round_environment():
    root = temp_dir("qa-s5-stand-")
    try:
        c = s5_task(root)
        run_summary(root, "earlier-window", SIGNAL, age_s=3600)
        dispatch(c, root, "a1")
        check_not_in("a window nobody has run yet inherits no signal from an earlier one",
                     "repair_cause", json.dumps(c.state()["dispatches"]["a1"]))
        run_summary(root, "w1-run1", SIGNAL)
        dispatch(c, root, "a2")
        stamped = c.state()["dispatches"]["a2"]
        check_eq("the round after a suspect stand is environment by default",
                 stamped.get("repair_cause"), "environment")
        check_eq("and the receipt names the run that said so",
                 stamped.get("repair_cause_source"), "stand_signal:evidence/runs/w1-run1/w1-run1.json")
        check_eq("so it spends nothing", repair_rounds(c.state()["dispatches"], receipt("x")), 0)
        replay = c.apply("dispatch", {"id": "a2", "stage": "S5", "role": "qa-automator",
                                      "scope": ["TC-1", "TC-2"], "input_hash": "h", "budget": {},
                                      "known_paths": {}, "idempotency_key": "a2"})
        check_eq("a replayed dispatch keeps the stamp it was committed with",
                 replay["payload"].get("repair_cause"), "environment")
        dispatch(c, root, "a3", repair_cause="test_defect")
        check_eq("a cause the orchestrator named is never overwritten",
                 c.state()["dispatches"]["a3"]["repair_cause"], "test_defect")
        run_summary(root, "w1-run2")
        dispatch(c, root, "a4")
        check_not_in("the latest run decides: a clean one clears the default",
                     "repair_cause", json.dumps(c.state()["dispatches"]["a4"]))
        packet = c.prepare({"stage": "S5", "role": "qa-automator", "scope": ["TC-1", "TC-2"]})
        check_eq("prepare shows no signal then", packet["repair_budget"]["stand_signal"], None)
    finally:
        cleanup(root)


# --- windows ---------------------------------------------------------------------------------

def windows_are_small_and_never_mixed():
    ui = {"TC-001", "TC-002", "TC-003", "TC-004", "TC-005"}
    cases = [f"TC-{n:03d}" for n in range(1, 11)]
    windows = split_windows(cases, lambda case: case in ui)
    check_eq("everything that is not UI goes first, four to a window; UI follows, two to a window",
             [(w["surface"], w["scope"]) for w in windows],
             [("other", ["TC-006", "TC-007", "TC-008", "TC-009"]), ("other", ["TC-010"]),
              ("ui", ["TC-001", "TC-002"]), ("ui", ["TC-003", "TC-004"]), ("ui", ["TC-005"])])
    check_eq("windows are numbered in dispatch order", [w["index"] for w in windows], [1, 2, 3, 4, 5])
    check_eq("an empty scope has no windows", split_windows([], lambda case: True), [])

    root = temp_dir("qa-s5-windows-")
    try:
        cases = ("TC-1", "TC-2", "TC-3", "TC-4", "TC-5")
        c = s5_task(root, cases, {"TC-1": "e2e-ui", "TC-2": "e2e-ui", "TC-3": "e2e-ui"})
        scope = c.stage_scope("S5")
        check_eq("the whole scope is still there", scope["scope"], list(cases))
        check_eq("UI is the plan row's level e2e-ui, reached through the case's plan row",
                 [(w["surface"], w["scope"]) for w in scope["windows"]],
                 [("other", ["TC-4", "TC-5"]), ("ui", ["TC-1", "TC-2"]), ("ui", ["TC-3"])])
        dispatch(c, root, "a1", scope=("TC-4", "TC-5"))
        dispatch(c, root, "k1", role="qa-code-critic", scope=("TC-4", "TC-5"), accept=False)
        done = c.stage_scope("S5")["windows"]
        check_eq("a window shows the accepted dispatch that covered it",
                 done[0]["accepted_by"], {"qa-automator": "a1"})
        check_eq("and an untouched window shows none", done[1]["accepted_by"], {})
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"dispatch": {"ui_window_cases": 1, "api_window_cases": "many"}}),
            encoding="utf-8")
        sized = c.stage_scope("S5")["windows"]
        check_eq("the project's own window size is what decides, and nonsense is the default",
                 [w["scope"] for w in sized], [["TC-4", "TC-5"], ["TC-1"], ["TC-2"], ["TC-3"]])
        check_eq("a stage whose scope is not derived has no windows", c.stage_scope("S4")["windows"], [])
        check_in("the prepare packet carries the windows with the scope",
                 "windows", c.prepare({"stage": "S5"})["stage_scope"])
    finally:
        cleanup(root)


# --- the notes the next window reads first -----------------------------------------------------

def the_next_window_reads_the_notes_first():
    root = temp_dir("qa-s5-notes-")
    try:
        c = s5_task(root)
        first = c.prepare({"stage": "S5", "role": "qa-automator", "scope": ["TC-1", "TC-2"]})
        check_not_in("no notes yet, nothing to read first", "read_first",
                     json.dumps(first["dispatch_request"]))
        dispatch(c, root, "a1")
        (root / "work" / "s5-notes.md").write_text(
            "- stand: one account, never run two at once\n- ids: UI params start with chromium-\n",
            encoding="utf-8")
        packet = c.prepare({"stage": "S5", "role": "qa-code-critic", "scope": ["TC-1", "TC-2"]})
        check_eq("once a window wrote them the S5 packet names them",
                 packet["dispatch_request"].get("read_first"), ["work/s5-notes.md"])
        dispatch(c, root, "k1", role="qa-code-critic", accept=False)
        check_eq("and the receipt the role is handed carries them whatever the prompt said",
                 c.state()["dispatches"]["k1"].get("read_first"), ["work/s5-notes.md"])
        rework = c.build_rework_request("S5", "qa-automator", ["TC-1"], "sleep in TC-1",
                                        cause="mechanical")
        check_eq("a rework request carries both the notes and its cause",
                 (rework.get("read_first"), rework.get("repair_cause")),
                 (["work/s5-notes.md"], "mechanical"))
        check_in("a rework cause outside the closed list is refused by name", "must be one of",
                 refusal(lambda: c.build_rework_request("S5", "qa-automator", ["TC-1"], "x",
                                                        cause="weather")))
    finally:
        cleanup(root)


# --- a journal written before 0.7.8 ------------------------------------------------------------

def an_old_journal_replays():
    events, previous = [], 0
    for index, payload in enumerate([
            {"id": "S5-qa-automator-6", "stage": "S5", "role": "qa-automator", "scope": ["TC-001"],
             "input_hash": "h", "budget": {}, "known_paths": {}},
            {"id": "S5-qa-automator-7", "stage": "S5", "role": "qa-automator", "scope": ["TC-001"],
             "input_hash": "h", "budget": {}, "known_paths": {},
             "parent_retry": "S5-qa-automator-6"}], start=1):
        events.append({"sequence": index, "type": "dispatch", "payload": payload,
                       "created_at": 1000.0 + index})
        previous = index
    state = projection(events)
    check_eq("dispatches with no repair_cause and no windows project as they always did",
             (previous, state["dispatches"]["S5-qa-automator-6"]["status"],
              state["dispatches"]["S5-qa-automator-7"]["status"]), (2, "superseded", "running"))
    check_eq("and spend no round", repair_rounds(state["dispatches"], receipt("x", scope=("TC-001",))), 0)


def main():
    only_a_round_about_the_test_is_counted()
    the_cap_names_what_it_counted()
    a_mechanical_fix_is_closed_by_the_authors_green_run()
    the_mechanical_author_completes_the_window()
    the_critic_closes_a_window_the_stand_blocked()
    a_stand_signal_makes_the_round_environment()
    windows_are_small_and_never_mixed()
    the_next_window_reads_the_notes_first()
    an_old_journal_replays()
    finish("test_s5_process")


if __name__ == "__main__":
    main()
