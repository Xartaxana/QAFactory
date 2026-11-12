#!/usr/bin/env python3
"""A dispatch nobody is doing, and the word that frees it.

TP2-2523: a rework dispatch of an accepted S3 stage. The role started, refused the
work and stopped; nothing recorded its return. For two days `next` answered
`wait_existing_job` with `cancel_allowed: false`, `recover` changed nothing, and the person's
own "it's dead, go on" — written down — freed exactly nothing. That is the standing rule of
this factory broken in the one place it is easiest to break it.

Also here: the review receipts a `qa-code-critic` acceptance requires (eight findings
returned as chat text and never written to a file), rework for the stages whose roles have no
cases, and the instance map `stage-scope` hands to the run request.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     mark_project, run_script, s5_apply, temp_project)

sys.path.insert(0, str(SCRIPTS))
import waiver  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework_scope as SCOPED  # noqa: E402
import test_dispatch_liveness as LIFE  # noqa: E402

STRATEGIST = "S3-qa-test-strategist-1"


def at_s3_rework(root):
    """The 2523 shape: an accepted S3 sent back over one plan row, and the role gone."""
    mark_project(root)      # callers pass a plain folder too (test_post_commit_refresh): the marker is idempotent
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")])
    for number in range(4):
        BASE.accept_stage(controller, root, f"S{number}")
    controller.apply("dispatch", {"id": STRATEGIST, "stage": "S3", "role": "qa-test-strategist",
                                  "scope": [], "input_hash": "plan-input", "budget": {"requests": 30},
                                  "known_paths": {"root": str(root)}, "idempotency_key": "d-strat"})
    controller.apply("accept", {"id": STRATEGIST, "status": "accepted", "stage_complete": False,
                                "evidence_refs": [BASE.evidence_ref(root, "plan.txt")],
                                "idempotency_key": "a-strat"})
    return controller


def journal_stop(root, agent, when=None):
    path = root / "qa-factory" / "records" / "journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "event": "subagent_stop", "agent": agent, "task": root.name, "status": "completed",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                time.gmtime(when if when is not None else time.time()))}) + "\n")


# --- the deadlock ------------------------------------------------------------------------

def a_role_that_stopped_no_longer_holds_the_story():
    root = temp_project("qa-2523-")
    try:
        controller = at_s3_rework(root)
        request = controller.build_rework_request(
            "S3", "qa-test-strategist", [], "carry the two missing risks into the plan",
            rows=["TS-1"])
        check_eq("a stage whose role has no cases reworks without --cases", request["scope"], [])
        check_eq("and carries the plan rows instead", request["plan_rows"], ["TS-1"])
        controller.apply("dispatch", dict(request))
        rework_id = request["id"]
        check_eq("the stuck state is the one the colleague saw",
                 Controller(root).next_action()["action"], "wait_existing_job")
        # The role started and stopped. This is the only record of it the host kept.
        journal_stop(root, "qa-factory:qa-test-strategist")
        action = Controller(root).next_action()
        check_eq("next asks the orchestrator to settle the return, not to wait",
                 action["action"], "resolve_return")
        check_eq("naming the dispatch whose role is gone", action["dispatch_id"], rework_id)
        check_in("and what can be done with it", "accept", json.dumps(action["options"]))
        state = Controller(root).state()
        check_eq("the dispatch is closed as what it is",
                 state["dispatches"][rework_id]["status"], "returned_unaccepted")
        check_eq("the accepted stage keeps its acceptance", state["stages"]["S3"]["status"], "completed")
        check_eq("and stops pointing at a role nobody is running",
                 state["stages"]["S3"].get("active_dispatch_id"), None)
        check_eq("recover has nothing left to close",
                 Controller(root).recover()["journalled_repairs"], [])
        # The work it did write is still acceptable: the hook recorded a fact, not a verdict.
        Controller(root).apply("accept", {"id": rework_id, "status": "accepted",
                                          "stage_complete": False,
                                          "evidence_refs": [BASE.evidence_ref(root, "plan-2.txt")],
                                          "idempotency_key": "a-rework"})
        check_eq("a returned dispatch can still be accepted on its evidence",
                 Controller(root).state()["dispatches"][rework_id]["status"], "accepted")
    finally:
        cleanup(root)


# --- accepting a return does not go stale because of the return (B-311) ------------------------
#
# TP2-2406: the orchestrator prepared the accept of a dispatch, the role stopped, the hook
# (or `next`, through the liveness repair) journalled the stop, and the accept - carrying the
# revision it had read - was refused as "stale expected revision" although nothing it was about
# had changed. The rebase is narrow on purpose: only the dispatch's OWN return receipt may stand
# in the gap. A legacy fork rebased on any gap, which also let an accept through over a decision
# or another dispatch the orchestrator never saw.

def returned_rework(root, via):
    """A rework of the accepted S3 sent out, the revision read, and then the role stops."""
    controller = at_s3_rework(root)
    request = controller.build_rework_request("S3", "qa-test-strategist", [], "accept its evidence")
    controller.apply("dispatch", dict(request))
    before = controller.state()["revision"]
    if via == "hook":
        check_eq("the hook journals the stop", Controller(root).record_return(request["id"], "halted"), True)
    else:
        journal_stop(root, "qa-factory:qa-test-strategist")
        Controller(root).next_action()
    return controller, request, before


def an_accept(root, dispatch_id, revision, key, name="race-plan.txt", **extra):
    request = {"id": dispatch_id, "status": "accepted", "stage_complete": False,
               "evidence_refs": [BASE.evidence_ref(root, name)], "idempotency_key": key, **extra}
    if revision is not None:
        request["expected_revision"] = revision
    return request


def refusal(call):
    try:
        call()
    except (ValueError, StateConflict) as exc:
        return str(exc)
    return ""


def receipt_projection_does_not_make_a_returned_acceptance_stale():
    """A SubagentStop receipt may land after prepare but before the accept writer."""
    for via, kinds in (("repair", ["state_repair"]), ("hook", ["returned"])):
        root = temp_project("qa-return-accept-race-")
        try:
            controller, request, before = returned_rework(root, via)
            check_eq(f"{via}: the receipt projection advanced the journal revision by its own event",
                     [e["type"] for e in Controller(root).store.read()[before:]], kinds)
            check_eq(f"{via}: the dispatch is the returned one",
                     Controller(root).state()["dispatches"][request["id"]]["status"], "returned_unaccepted")
            check_eq(f"{via}: accepting with the revision read before the return is not stale",
                     refusal(lambda: Controller(root).apply(
                         "accept", an_accept(root, request["id"], before, "a-race-" + via))), "")
            check_eq(f"{via}: a returned dispatch accepts its already-produced evidence",
                     Controller(root).state()["dispatches"][request["id"]]["status"], "accepted")
        finally:
            cleanup(root)


def anything_else_in_the_gap_keeps_the_acceptance_stale():
    root = temp_project("qa-return-accept-gap-")
    try:
        controller = at_s3_rework(root)
        request = controller.build_rework_request("S3", "qa-test-strategist", [], "accept its evidence")
        controller.apply("dispatch", dict(request))
        rid = request["id"]
        store = controller.store
        count = lambda: len(store.read())  # noqa: E731

        # A status other than `returned_unaccepted` is judged as before, gap or no gap.
        running_at = count()
        store.commit("decision", {"id": "dec-0", "gate": "A", "status": "approved"}, "k-dec-0")
        check_in("a RUNNING dispatch is not rebased over an unrelated event", "stale expected revision",
                 refusal(lambda: Controller(root).apply("accept", an_accept(root, rid, running_at, "a-run"))))

        before_stop = count()
        journal_stop(root, "qa-factory:qa-test-strategist")
        Controller(root).next_action()
        check_eq("the stop is journalled as the dispatch's own receipt",
                 [e["type"] for e in store.read()[before_stop:]], ["state_repair"])
        revision_after_stop = count()

        def stale_at(label, revision):
            """The accept carrying `revision` is refused as stale, and writes nothing."""
            before = count()
            message = refusal(lambda: Controller(root).apply(
                "accept", an_accept(root, rid, revision, "a-" + label.replace(" ", "-"))))
            check_in(label + ": the acceptance stays stale", "stale expected revision", message)
            check_eq(label + ": and nothing was written", count(), before)

        def junk(label, commit):
            """One event that is NOT the dispatch's own receipt, with the revision just before it."""
            at = count()
            commit()
            check_eq(label + ": exactly one event landed", count(), at + 1)
            stale_at(label, at)
            return at

        junk("a decision", lambda: store.commit(
            "decision", {"id": "dec-1", "gate": "A", "status": "approved"}, "k-dec-1"))
        # The dispatch's own receipt AND something else: the whole gap must be receipts.
        stale_at("a receipt followed by a decision", before_stop)
        junk("a manifest patch", lambda: store.commit("manifest_patch", {"fragment": {}}, "k-patch"))
        junk("a dispatch of another role", lambda: Controller(root).apply("dispatch", {
            "id": "S3-qa-other-1", "stage": "S3", "role": "qa-other", "scope": [],
            "input_hash": "other", "budget": {}, "known_paths": {}, "idempotency_key": "d-other"}))
        junk("a return of another dispatch", lambda: store.commit(
            "returned", {"dispatch_id": "S3-qa-other-1", "digest": "x", "agent": "a"}, "k-ret-other"))
        fix = {"kind": "returned_unaccepted", "dispatch_id": "S3-qa-other-1", "stage": "S3",
               "role": "qa-other", "digest": "", "reason": "t"}
        junk("a repair of another dispatch", lambda: store.commit(
            "state_repair", {"fixes": [fix], "reason": "t"}, "k-rep-other"))
        junk("a repair that names this dispatch and another", lambda: store.commit(
            "state_repair", {"fixes": [dict(fix, dispatch_id=rid), fix], "reason": "t"}, "k-rep-both"))
        junk("a repair with no fixes", lambda: store.commit(
            "state_repair", {"fixes": [], "reason": "t"}, "k-rep-none"))
        junk("a release", lambda: Controller(root).release_dispatch("S3-qa-other-1", "it is dead"))

        # The dispatch it is about never moved, so the control: the same accept is valid at the
        # revision the journal has now, and a revision ahead of the journal is stale too.
        now = count()
        check_eq("the dispatch is still the returned one",
                 Controller(root).state()["dispatches"][rid]["status"], "returned_unaccepted")
        stale_at("a revision ahead of the journal", now + 3)
        check_eq("the same accept at the current revision is accepted",
                 refusal(lambda: Controller(root).apply("accept", an_accept(root, rid, now, "a-now"))), "")
        check_eq("so the refusals above were about the gap and nothing else",
                 Controller(root).state()["dispatches"][rid]["status"], "accepted")
        check("a revision below the revision after the stop is the case this test is about",
              revision_after_stop < now, (revision_after_stop, now))
    finally:
        cleanup(root)


def the_rebase_changes_the_number_and_nothing_else():
    root = temp_project("qa-return-accept-invariants-")
    try:
        controller, request, before = returned_rework(root, "repair")
        rid, store = request["id"], controller.store
        events = len(store.read())

        # `validate` still runs on the events inside the lock: an accept with no evidence is
        # refused for that, not waved through because its revision was forgiven.
        empty = an_accept(root, rid, before, "a-empty")
        empty.pop("evidence_refs")
        check_in("the rebased accept is still validated", "requires evidence",
                 refusal(lambda: Controller(root).apply("accept", empty)))
        check_eq("and wrote nothing", len(store.read()), events)

        # An event that lands AFTER `apply` read the journal is the commit's own check.
        late = {"done": False}
        original = controller._revision_past_own_return

        def land_late(dispatch_id, revision, current):
            result = original(dispatch_id, revision, current)
            if not late["done"]:
                late["done"] = True
                store.commit("decision", {"id": "dec-late", "gate": "A", "status": "approved"}, "k-late")
            return result
        controller._revision_past_own_return = land_late
        check_in("an event after apply's own read is still stale", "stale expected revision",
                 refusal(lambda: controller.apply("accept", an_accept(root, rid, before, "a-late"))))
        del controller._revision_past_own_return
        check_eq("and the late event is the only thing written", len(store.read()), events + 1)

        # With the late decision in the journal, the forgiven gap is gone: stale, as it should be.
        check_in("a decision now stands between the revision read and now", "stale expected revision",
                 refusal(lambda: Controller(root).apply("accept", an_accept(root, rid, before, "a-after"))))
        # No expected revision at all stays unchecked, as it always was.
        check_eq("an accept that names no revision is not checked against one",
                 refusal(lambda: Controller(root).apply("accept", an_accept(root, rid, None, "a-none"))), "")
        check_eq("and is accepted", Controller(root).state()["dispatches"][rid]["status"], "accepted")
    finally:
        cleanup(root)


def a_repeated_accept_returns_the_stored_event():
    root = temp_project("qa-return-accept-replay-")
    try:
        controller, request, before = returned_rework(root, "repair")
        rid = request["id"]
        first = Controller(root).apply("accept", an_accept(root, rid, before, "a-replay"))
        # Something else happens afterwards, then the orchestrator repeats the same request.
        controller.store.commit("decision", {"id": "dec-2", "gate": "A", "status": "approved"}, "k-dec-2")
        events = len(controller.store.read())
        again = Controller(root).apply("accept", an_accept(root, rid, before, "a-replay"))
        check_eq("the same idempotency key answers with the stored event",
                 (again["event_id"], again["sequence"]), (first["event_id"], first["sequence"]))
        check_eq("and writes nothing", len(controller.store.read()), events)
    finally:
        cleanup(root)


def the_hook_records_the_return_itself():
    root = temp_project("qa-return-hook-")
    try:
        controller = at_s3_rework(root)
        request = controller.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
        controller.apply("dispatch", dict(request))
        check_eq("the hook's write is a fact about a running dispatch",
                 Controller(root).record_return(request["id"], "halted: no non-owner account"), True)
        action = Controller(root).next_action()
        check_eq("which next reads as a return", action["action"], "resolve_return")
        check_in("carrying the role's own last word", "no non-owner account", action["digest"])
        check_eq("a second stop of the same dispatch changes nothing",
                 Controller(root).record_return(request["id"], "again"), False)
        check_eq("and an unknown dispatch is never invented",
                 Controller(root).record_return("no-such-dispatch", "x"), False)
        check_eq("nor is a missing id an exception in a hook",
                 Controller(root).record_return("", ""), False)
    finally:
        cleanup(root)


# --- a person's word ----------------------------------------------------------------------

def a_persons_word_releases_a_dispatch():
    root = temp_project("qa-release-")
    try:
        controller = at_s3_rework(root)
        request = controller.build_rework_request("S3", "qa-test-strategist", [], "redo the plan")
        controller.apply("dispatch", dict(request))
        LIFE.without_hooklib()
        check_eq("with no evidence either way the story waits",
                 Controller(root).next_action()["action"], "wait_existing_job")
        result = Controller(root).release_dispatch(request["id"], "it's dead, go on")
        check_eq("a person's word frees it", result["status"], "released_by_person")
        check_in("the artifacts are not part of the bargain", "never the work", result["artifacts"])
        check("and the story moves", result["next_action"]["action"] != "wait_existing_job",
              result["next_action"])
        state = Controller(root).state()
        check_eq("their words are what was recorded",
                 state["dispatches"][request["id"]]["released_by_person"], "it's dead, go on")
        # Reopening belongs to a CLOSED story (I-92). This one is mid-flight, so a release
        # frees a dispatch and nothing more: a story that never closed cannot be reopened,
        # and a `reopened_at` on it would make every reader think a person had gone back to
        # work that was never finished.
        check_eq("a release before gate B reopens nothing — there is nothing to reopen",
                 json.loads((root / "pipeline.json").read_text(encoding="utf-8")).get("reopened_at"),
                 None)
        check_eq("the evidence the role did write is untouched",
                 (root / "plan.txt").is_file(), True)
        check_eq("and the stage is startable again",
                 Controller(root).apply("dispatch", {
                     "id": "S3-qa-test-strategist-9", "stage": "S3", "role": "qa-test-strategist",
                     "scope": [], "input_hash": "plan-input", "budget": {}, "known_paths": {},
                     "idempotency_key": "d-again"})["payload"]["id"], "S3-qa-test-strategist-9")
        refused = ""
        try:
            Controller(root).release_dispatch(request["id"], "again")
        except StateConflict as exc:
            refused = str(exc)
        check_in("releasing what is already free says so", "holds nothing back", refused)
        refused = ""
        try:
            Controller(root).release_dispatch("S3-qa-test-strategist-9", "")
        except ValueError as exc:
            refused = str(exc)
        check_in("and a release without the person's words is not a release",
                 "their decision", refused)
    finally:
        cleanup(root)


def the_cli_releases_and_names_what_it_freed():
    root = temp_project("qa-release-cli-")
    try:
        controller = at_s3_rework(root)
        request = controller.build_rework_request("S3", "qa-test-strategist", [], "redo the plan")
        controller.apply("dispatch", dict(request))
        result = run_script("controller.py", "--task-root", root, "--operation", "release",
                            "--dispatch", request["id"], "--words", "nobody is working on this")
        check("the CLI releases in one call", result.returncode == 0, result.stderr)
        answer = json.loads(result.stdout)
        check_eq("and says what it freed", answer["dispatch_id"], request["id"])
        check_eq("with the next action in the same answer",
                 answer["next_action"]["action"] != "wait_existing_job", True)
        result = run_script("controller.py", "--task-root", root, "--operation", "release",
                            "--dispatch", "nope", "--words", "w")
        check_in("an unknown dispatch is answered with the ones this story has",
                 request["id"], result.stderr)
    finally:
        cleanup(root)


# --- the code critic leaves a file, not a reply --------------------------------------------

def manifest(root, **extra):
    path = root / "work" / "automation-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema_version": 2,
                "tests": [{"instance_id": "TC-1::test_one", "test": "tests/test_one.py::test_one",
                           "case_version_links": [{"case_id": "TC-1", "version": "cv1"}],
                           "new_or_changed": True, "sensitivity_proof": None}],
                "obligation_bindings": [{"obligation_id": "OB-TS-1", "instance_ids": ["TC-1::test_one"],
                                         "review_receipt_ref": ""}]}
    document.update(extra)
    path.write_text(json.dumps(document), encoding="utf-8")
    return document


def a_code_review_without_receipts_is_not_accepted():
    root = temp_project("qa-code-review-")
    try:
        controller = SCOPED.gate_a_task(root)
        s5_apply(controller, {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                                      "scope": ["TC-1"], "input_hash": "s5", "budget": {},
                                      "known_paths": {}, "idempotency_key": "d-auto"})
        controller.apply("accept", {"id": "S5-qa-automator-1", "status": "accepted",
                                    "stage_complete": False,
                                    "evidence_refs": [BASE.evidence_ref(root, "author.txt")],
                                    "idempotency_key": "a-auto"})
        s5_apply(controller, {"id": "S5-qa-code-critic-1", "stage": "S5",
                                      "role": "qa-code-critic", "scope": ["TC-1"], "input_hash": "s5",
                                      "budget": {}, "known_paths": {}, "idempotency_key": "d-critic"})
        manifest(root)
        # `stage_complete: false` on the role that CLOSES S5 is refused on its own since
        # TP2-2553, so the completion says what is still open — this review is about
        # the receipt rules, not about closing the stage.
        accept = {"id": "S5-qa-code-critic-1", "status": "accepted", "stage_complete": False,
                  "unresolved": True, "reason": "the window's second half is not reviewed yet",
                  "evidence_refs": [BASE.evidence_ref(root, "review-digest.txt")],
                  "idempotency_key": "a-critic"}
        refused = ""
        try:
            controller.apply("accept", dict(accept))
        except StateConflict as exc:
            refused = str(exc)
        check_in("a review with no findings file is refused", "findings file", refused)
        check_in("so is a manifest with no review receipt", "review_receipt_ref", refused)
        check_in("and a sensitivity proof missing without a reason", "sensitivity proof", refused)
        check_in("the refusal names the probe that makes it (FR-1, FR-2: the critic's own door)",
                 "probe_by_code.py", refused)
        check_in("the refusal says whose defect a missing proof is", "owned by the factory", refused)
        check_in("and it is not the person's to repair", "not the person's to produce", refused)
        check_in("with the way their word passes it", "waiver.py", refused)

        document = manifest(root)
        document["tests"][0]["sensitivity_proof_missing_reason"] = "the probe tool gave no receipt"
        document["obligation_bindings"][0]["review_receipt_ref"] = "work/s5-window.json"
        (root / "work" / "automation-manifest.json").write_text(json.dumps(document), encoding="utf-8")
        (root / "work").mkdir(exist_ok=True)
        accept["evidence_refs"] = [BASE.evidence_ref(root, "critic-findings.md", "# 8 findings")]
        controller.apply("accept", dict(accept))
        check_eq("with the file and the receipt the review is accepted",
                 controller.state()["dispatches"]["S5-qa-code-critic-1"]["status"], "accepted")
    finally:
        cleanup(root)


def the_live_check_is_asked_of_new_or_changed_tests_only():
    """D-0010 / D-0012 in the controller: `proof_level.proof_required` is the predicate, a receipt
    reached only through an obligation binding is a proof, a handed test is never asked, an
    unchanged one is not probed, and the refusal names the door - `probe_by_code.py`."""
    root = temp_project("qa-code-review-live-")
    try:
        controller = SCOPED.gate_a_task(root)
        findings = {"evidence_refs": [{"path": "work/test-code/critic-findings.md"}]}
        (root / "work" / "sensitivity-receipts").mkdir(parents=True, exist_ok=True)
        (root / "work" / "sensitivity-receipts" / "r.json").write_text("{}", encoding="utf-8")

        def problems(row, **extra):
            document = {"schema_version": 2, "tests": [dict({"instance_id": "TC-1::test_one",
                                                             "covers": ["TC-1"]}, **row)]}
            document.update(extra)
            (root / "work" / "automation-manifest.json").write_text(json.dumps(document), encoding="utf-8")
            return " || ".join(p for p in controller._code_review_problems(findings) if "sensitivity" in p)

        said = problems({"new_or_changed": True})
        check_in("a new or changed test with no receipt and no reason is refused", "TC-1::test_one", said)
        check_in("the refusal names the door: the live probe", "probe_by_code.py", said)
        check_in("with the words for it", "the check is live", said)
        check_in("and the person's word still passes it (the phrase every line of this rule carries)",
                 "the qa-code-critic window is not receipted", said)
        check_in("change_disposition new_or_changed counts, as it does in the ledger and delivery",
                 "TC-1::test_one", problems({"change_disposition": "new_or_changed"}))
        check_in("sensitivity_proof_required counts", "TC-1::test_one", problems({"sensitivity_proof_required": True}))
        check_eq("an unchanged test is not probed and asks for nothing",
                 problems({"change_disposition": "unchanged"}), "")
        check_eq("a row that says nothing asks for nothing", problems({}), "")
        check_eq("a receipt on the row is a proof", problems({"new_or_changed": True,
                                                            "sensitivity_proof": {"receipt_ref": {"path": "x"}}}), "")
        check_eq("a reason for its absence passes",
                 problems({"new_or_changed": True, "sensitivity_proof_missing_reason": "the tool could not run"}), "")
        handed = {"unresolved": [{"case": "TC-1", "reason": "handed_to_person", "detail": "ios: a device"}]}
        check_eq("a HANDED test is never asked for a probe: nothing runs here for it",
                 problems({"new_or_changed": True}, **handed), "")
        binding = {"obligation_bindings": [{"obligation_id": "OB-1", "instance_ids": ["TC-1::test_one"],
                                            "sensitivity": "proven", "probe_receipt_ref": "work/sensitivity-receipts/r.json",
                                            "review_receipt_ref": "work/w.json"}]}
        check_eq("proven through an obligation binding only: not newly refused",
                 problems({"new_or_changed": True}, **binding), "")
        gone = {"obligation_bindings": [dict(binding["obligation_bindings"][0],
                                             probe_receipt_ref="work/sensitivity-receipts/gone.json")]}
        check_in("a binding whose receipt file is gone proves nothing", "TC-1::test_one",
                 problems({"new_or_changed": True}, **gone))
        unproven = {"obligation_bindings": [dict(binding["obligation_bindings"][0], sensitivity="not_required")]}
        check_in("a binding that does not say `proven` proves nothing", "TC-1::test_one",
                 problems({"new_or_changed": True}, **unproven))
    finally:
        cleanup(root)


def a_persons_word_passes_the_review_rule():
    root = temp_project("qa-code-review-waiver-")
    try:
        controller = SCOPED.gate_a_task(root)
        s5_apply(controller, {"id": "S5-qa-code-critic-1", "stage": "S5",
                                      "role": "qa-code-critic", "scope": ["TC-1"], "input_hash": "s5",
                                      "budget": {}, "known_paths": {}, "idempotency_key": "d-critic"})
        manifest(root)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        waiver.apply_stage_override(pipeline, "S5", "not receipted",
                                    "accept it, the findings are in the chat and I read them",
                                    waiver.now_iso())
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        controller.apply("accept", {"id": "S5-qa-code-critic-1", "status": "accepted",
                                    "stage_complete": False, "unresolved": True,
                                    "reason": "the window's second half is not reviewed yet",
                                    "evidence_refs": [BASE.evidence_ref(root, "digest.txt")],
                                    "idempotency_key": "a-critic"})
        check_eq("a person's recorded word passes it, like every other block here",
                 controller.state()["dispatches"]["S5-qa-code-critic-1"]["status"], "accepted")
    finally:
        cleanup(root)


def a_story_without_a_manifest_is_not_refused():
    """0.7.4 stories and reviews that are not about automation have no manifest at all."""
    root = temp_project("qa-code-review-legacy-")
    try:
        controller = SCOPED.gate_a_task(root)
        s5_apply(controller, {"id": "S5-qa-code-critic-1", "stage": "S5",
                                      "role": "qa-code-critic", "scope": ["TC-1"], "input_hash": "s5",
                                      "budget": {}, "known_paths": {}, "idempotency_key": "d-critic"})
        controller.apply("accept", {"id": "S5-qa-code-critic-1", "status": "accepted",
                                    "stage_complete": False, "unresolved": True,
                                    "reason": "the window's second half is not reviewed yet",
                                    "evidence_refs": [BASE.evidence_ref(root, "digest.txt")],
                                    "idempotency_key": "a-critic"})
        check_eq("a review with no manifest to receipt is accepted as before",
                 controller.state()["dispatches"]["S5-qa-code-critic-1"]["status"], "accepted")
    finally:
        cleanup(root)


# --- the scope both halves of the run conversation speak ------------------------------------

def stage_scope_hands_over_the_instances():
    root = temp_project("qa-scope-instances-")
    try:
        controller = SCOPED.gate_a_task(root)
        check_eq("with no manifest yet every case has an empty list, not a refusal",
                 controller.stage_scope("S5")["instances"], {"TC-1": []})
        path = root / "work" / "automation-manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"tests": [
            {"instance_id": "TC-1::test_a[one]",
             "case_version_links": [{"case_id": "TC-1", "version": "cv1"}]},
            {"instance_id": "TC-1::test_a[two]",
             "case_version_links": [{"case_id": "TC-1", "version": "cv1"}]},
            {"instance_id": "TC-9::test_b", "case_version_links": [{"case_id": "TC-9"}]}]}),
            encoding="utf-8")
        scope = controller.stage_scope("S5")
        check_eq("the manifest's instances come back keyed by case",
                 scope["instances"], {"TC-1": ["TC-1::test_a[one]", "TC-1::test_a[two]"]})
        check_not_in("and nothing outside the stage's scope leaks in",
                     "TC-9", json.dumps(scope["instances"]))
    finally:
        cleanup(root)


def main():
    a_role_that_stopped_no_longer_holds_the_story()
    receipt_projection_does_not_make_a_returned_acceptance_stale()
    anything_else_in_the_gap_keeps_the_acceptance_stale()
    the_rebase_changes_the_number_and_nothing_else()
    a_repeated_accept_returns_the_stored_event()
    the_hook_records_the_return_itself()
    a_persons_word_releases_a_dispatch()
    the_cli_releases_and_names_what_it_freed()
    a_code_review_without_receipts_is_not_accepted()
    the_live_check_is_asked_of_new_or_changed_tests_only()
    a_persons_word_passes_the_review_rule()
    a_story_without_a_manifest_is_not_refused()
    stage_scope_hands_over_the_instances()
    finish("test_controller_release")


if __name__ == "__main__":
    main()
