#!/usr/bin/env python3
"""window words: a part of test_controller_rework.py, split by tools/test_split.py (TD-11c). The shared helpers are in controller_rework_common."""
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     mark_project, run_script, s5_apply, temp_dir, temp_project)
sys.path.insert(0, str(SCRIPTS))
from controller import BINDING_KEYS, Controller, apply_rerun_after, projection, repair_ledger
from event_store import StateConflict  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework_scope as SCOPED  # noqa: E402  (plan_row/gate_a_task fixtures)
import test_story_closed as CLOSED  # noqa: E402  (closed_story fixture)
from controller_rework_common import (  # noqa: E402
    DESIGNER, WORDS, designer_story, pin, redo, refusal, settle, story_to_s8, words_file,
)


# --- a rework is never the opener of a window (B-007, F7-1) ----------------------------------------

def _receipt(identifier, scope=("TC-1",), status="accepted", role="qa-automator", stage="S5", **extra):
    return dict({"id": identifier, "stage": stage, "role": role, "scope": list(scope), "status": status}, **extra)


def a_rework_is_never_the_opener_of_a_window():
    """S7 and S4 register their reworks on a window whose plain opener sits under another key
    (a wider S5 window, the designer's own scope): the first repair was read as the opener and
    cost nothing, so the cap allowed one round more than the round text said."""
    window = _receipt("next")

    def ledger(*receipts):
        return {r["id"]: r for r in receipts}

    s7 = ledger(_receipt("S5-qa-automator-2", rework_of="S5-qa-automator-1", repair_cause="test_defect"),
                _receipt("S5-qa-automator-3", rework_of="S5-qa-automator-2", repair_cause="test_defect"))
    found = repair_ledger(s7, window)
    check_eq("S7-shaped: two reworks on [TC-1] and no plain opener are two rounds", found["counted"], 2)
    check_eq("and the window is opened by them", found["opened"], True)
    check_eq("each round is named", [r["id"] for r in found["rounds"]],
             ["S5-qa-automator-2", "S5-qa-automator-3"])

    s5 = ledger(_receipt("S5-qa-automator-1"),
                _receipt("S5-qa-automator-2", rework_of="S5-qa-automator-1", repair_cause="test_defect"))
    check_eq("S5-shaped: the plain opener and one rework are one round", repair_ledger(s5, window)["counted"], 1)

    later = ledger(_receipt("S5-qa-automator-2", rework_of="S5-qa-automator-1", repair_cause="test_defect"),
                   _receipt("S5-qa-automator-1"))
    check_eq("the plain dispatch is the opener wherever it stands in the journal",
             [r["id"] for r in repair_ledger(later, window)["rounds"]], ["S5-qa-automator-2"])

    resumed = ledger(_receipt("S5-qa-automator-2", status="superseded", rework_of="S5-qa-automator-1",
                              repair_cause="test_defect"),
                     _receipt("S5-qa-automator-3", parent_retry="S5-qa-automator-2"))
    check_eq("a resumed rework is one round, not the opener",
             repair_ledger(resumed, window)["counted"], 1)

    dead_opener = ledger(_receipt("S5-qa-automator-1", status="never_started"),
                         _receipt("S5-qa-automator-2", rework_of="S5-qa-automator-1", repair_cause="test_defect"))
    check_eq("an opener that never started leaves the rework a round", repair_ledger(dead_opener, window)["counted"], 1)

    check_eq("a window with nothing live is not opened",
             (repair_ledger({}, window)["opened"], repair_ledger({}, window)["counted"]), (False, 0))
    other = ledger(_receipt("S5-qa-automator-2", scope=("TC-9",), rework_of="x", repair_cause="test_defect"))
    check_eq("another window's rework spends nobody's cap here", repair_ledger(other, window)["counted"], 0)
    tooling = ledger(_receipt("S5-qa-automator-2", rework_of="x", repair_cause="tooling"))
    check_eq("a rework about the tooling is a round of its own cause and spends no cap",
             (repair_ledger(tooling, window)["by_cause"], repair_ledger(tooling, window)["counted"]),
             ({"tooling": 1}, 0))


def s4_rounds_survive_a_changed_case_list():
    """The S4 designer's rounds are counted for the story, not for one case list: a repair that adds
    or drops a case changes the scope hash, and the count used to start again from 0 (critic t-064:
    5 cases -> 1, 6 cases -> 1, 7 cases -> 0), so the S4 loop could run past its cap."""
    window = _receipt("next", role="qa-case-designer", stage="S4", scope=("TC-1", "TC-2", "TC-3"))

    def ledger(*receipts):
        return {r["id"]: r for r in receipts}

    drift = ledger(_receipt("S4-qa-case-designer-1", role="qa-case-designer", stage="S4", scope=("TC-1", "TC-2", "TC-3")),
                   _receipt("S4-qa-case-designer-2", role="qa-case-designer", stage="S4", scope=("TC-1", "TC-2"),
                            rework_of="S4-qa-case-designer-1", repair_cause="test_defect"),
                   _receipt("S4-qa-case-designer-3", role="qa-case-designer", stage="S4", scope=("TC-1", "TC-2", "TC-3"),
                            rework_of="S4-qa-case-designer-2", repair_cause="test_defect"))
    check_eq("S4: rounds over three different case lists are still two rounds",
             repair_ledger(drift, window)["counted"], 2)
    check_eq("and a fourth case list asks the same ledger",
             repair_ledger(drift, _receipt("x", role="qa-case-designer", stage="S4", scope=("TC-1", "TC-2", "TC-3", "TC-4")))["counted"], 2)
    plain = ledger(_receipt("S5-qa-automator-1", scope=("TC-1", "TC-2")),
                   _receipt("S5-qa-automator-2", scope=("TC-1",), rework_of="S5-qa-automator-1", repair_cause="test_defect"))
    check_eq("S5 keeps its per-window key: another case list is another window",
             repair_ledger(plain, _receipt("x", scope=("TC-1", "TC-2", "TC-3")))["counted"], 0)

    root = temp_project("qa-s4-drift-")
    try:
        cases = ["TC-1", "TC-2", "TC-3"]
        controller = Controller(root)
        controller.apply("initialize", {"scope": cases, "source_revision": "src-1",
                                        "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")])
        for number in range(4):
            BASE.accept_stage(controller, root, f"S{number}")
        controller.apply("dispatch", {"id": "S4-qa-case-designer-1", "stage": "S4", "role": "qa-case-designer",
                                      "scope": cases, "input_hash": "design-input", "known_paths": {"root": str(root)},
                                      "budget": {}, "idempotency_key": "d-designer"})
        BASE.record_stage_acceptance(root, "S4", "S4-qa-case-designer-1")  # E-B11: a closing accept of S4 needs the acceptor's record
        controller.apply("accept", {"id": "S4-qa-case-designer-1", "status": "accepted", "stage_complete": True,
                                    "evidence_refs": [BASE.evidence_ref(root, "designer.txt")],
                                    "idempotency_key": "a-designer"})

        def budget_for(scope):
            return Controller(root).prepare({"stage": "S4", "role": "qa-case-designer", "scope": scope})["repair_budget"]

        check_eq("S4: a fresh story has spent nothing", budget_for(cases)["counted"], 0)
        first = controller.build_rework_request("S4", "qa-case-designer", ["TC-1", "TC-2"], "round one")
        controller.apply("dispatch", dict(first))
        controller.apply("accept", {"id": first["id"], "status": "accepted", "stage_complete": False,
                                    "evidence_refs": [BASE.evidence_ref(root, "designer-2.txt")],
                                    "idempotency_key": "a-" + first["id"]})
        check_eq("S4: after one rework the next round reads 1 of 2", (budget_for(cases)["counted"], budget_for(cases)["cap"]), (1, 2))
        second = controller.build_rework_request("S4", "qa-case-designer", cases, "round two, a case was added")
        controller.apply("dispatch", dict(second))
        controller.apply("accept", {"id": second["id"], "status": "accepted", "stage_complete": False,
                                    "evidence_refs": [BASE.evidence_ref(root, "designer-3.txt")],
                                    "idempotency_key": "a-" + second["id"]})
        check_eq("S4: the second rework, over another case list, is counted: the budget says 2 of 2",
                 (budget_for(["TC-1"])["counted"], budget_for(cases)["counted"], budget_for(cases)["cap"]), (2, 2, 2))
        message = ""
        try:
            controller.apply("dispatch", dict(controller.build_rework_request("S4", "qa-case-designer", ["TC-1", "TC-3"], "round three")))
        except StateConflict as exc:
            message = str(exc)
        check_in("S4: a third rework is refused by the controller's own cap check, on the same key", "repair round(s)", message)
        check_in("and says the cap", "the cap is 2", message)
    finally:
        cleanup(root)


DROP = object()  # a request field a forged-stamp row removes (R9)


def pipeline_of(root):
    return json.loads((root / "pipeline.json").read_text(encoding="utf-8"))


def person_rework(controller, stage="S5", role="qa-automator", **extra):
    """The request of a rework whose reason is the person's own words (what `--words-file` builds)."""
    return controller.build_rework_request(stage, role, ["TC-1"], WORDS, words_given=True, **extra)


def rework_cli(root, *tail, stage="S5", role="qa-automator"):
    return run_script("controller.py", "--task-root", root, "--operation", "rework", "--stage", stage,
                      "--role", role, "--cases", "TC-1", *tail)


def dispatch_states(state, *ids):
    return {i: state["dispatches"][i]["status"] for i in ids}


def a_person_rework_carries_the_stamp():
    """R1: the request names the completed stages after S5, the critic's review, and the decisions after it."""
    root = temp_project("qa-rerun-r1-")
    try:
        controller = story_to_s8(root)
        revision = controller.state()["revision"]
        stamp = person_rework(controller).get("rerun_after")
        check_eq("R1: the stamp lists S6-S8, the S5 critic's review, and no decision (gate B is undecided)",
                 stamp, {"stages": ["S6", "S7", "S8"], "reviews": ["dS5"], "decisions": []})
        check_eq("R1: the author's own accepted dispatch is not a review of its own rework",
                 "dS5-author" in (stamp or {}).get("reviews", []), False)
        result = rework_cli(root, "--words-file", words_file(root), "--build-only")
        check("R1: the CLI builds it from --words-file", result.returncode == 0, result.stderr)
        built = json.loads(result.stdout)["request"]
        check_eq("R1: --build-only prints the stamp", built.get("rerun_after"), stamp)
        check_eq("R1: the reason is still the file's bytes, CRLF and both lines whole",
                 built["reason"].encode("utf-8"), WORDS.encode("utf-8"))
        check_eq("R1: building recorded nothing", Controller(root).state()["revision"], revision)
        check_eq("R1: the stamp is a COPY of what the state holds - building it twice gives the same one",
                 person_rework(controller).get("rerun_after"), stamp)
    finally:
        cleanup(root)


def the_replay_sets_aside_what_runs_after_the_rework():
    """R2: the dispatch event lowers S6-S8, stales the critic and their accepted dispatches, and `next` goes back to S5."""
    root = temp_project("qa-rerun-r2-")
    try:
        story_to_s8(root)
        result = rework_cli(root, "--words-file", words_file(root))
        check("R2: the CLI dispatches the stamped rework", result.returncode == 0, result.stderr)
        rework = json.loads(result.stdout)["request"]["id"]
        state = Controller(root).state()
        check_eq("R2: S5 is running again, and says which rework did it",
                 {k: state["stages"]["S5"].get(k) for k in ("status", "dispatch_id", "rerun_after")},
                 {"status": "running", "dispatch_id": rework, "rerun_after": rework})
        for name in ("S6", "S7", "S8"):
            entry = state["stages"][name]
            check_eq(f"R2: {name} is pending again, stamped with the rework",
                     (entry["status"], entry.get("rerun_after")), ("pending", rework))
            check_in(f"R2: {name} says why", f"runs again after the rework {rework} of S5", entry["reason"])
        check_eq("R2: the critic and every later accepted dispatch are stale; the author's work and S0-S4 stand",
                 dispatch_states(state, "dS5", "dS6", "dS7", "dS8", "dS5-author", "dS4", "dS0"),
                 {"dS5": "stale", "dS6": "stale", "dS7": "stale", "dS8": "stale",
                  "dS5-author": "accepted", "dS4": "accepted", "dS0": "accepted"})
        check_eq("R2: and they say which rework staled them",
                 {i: state["dispatches"][i].get("stale_by_rework") for i in ("dS5", "dS6", "dS8")},
                 {"dS5": rework, "dS6": rework, "dS8": rework})
        check_eq("R2: gate A is untouched (it is before S5)", state["decisions"]["gate-a"]["status"], "approved")
        controller = Controller(root)
        settle(controller, root, {"id": rework})
        action = Controller(root).next_action()
        check_eq("R2: the rework is accepted, not complete: next goes back to S5",
                 (action["action"], action.get("stage")), ("prepare_stage", "S5"))
        check_eq("R2: S5 is startable again", Controller(root).state()["stages"]["S5"]["status"], "pending")
    finally:
        cleanup(root)


def a_stage_closed_by_a_code_only_receipt_is_lowered():
    """R3 + H14: S6 closed by a receipt has no accepted dispatch; the stamp lowers it by status, and pipeline.json
    loses the receipt's marks with it."""
    root = temp_project("qa-rerun-r3-")
    try:
        controller = SCOPED.gate_a_task(root)
        BASE.accept_stage(controller, root, "S5")
        controller.apply("code_only", {"id": "zero-s6", "stage": "S6", "reason": "all current checks already have valid evidence",
                                       "evidence_refs": [BASE.evidence_ref(root, "zero-s6.txt")], "idempotency_key": "zero-s6"})
        for number in (7, 8):
            BASE.accept_stage(controller, root, f"S{number}")
        check_eq("R3 fixture: S6 is closed by a receipt and no dispatch ran on it",
                 (controller.state()["stages"]["S6"].get("code_only"),
                  [d for d in controller.state()["dispatches"].values() if d.get("stage") == "S6"]), (True, []))
        check_eq("R3 control: pipeline.json carries the receipt's marks before the rework",
                 (pipeline_of(root)["stages"]["S6"].get("code_only"), pipeline_of(root)["stages"]["S6"].get("receipt_id")),
                 (True, "zero-s6"))
        request = person_rework(controller)
        check_eq("R3: the stamp lowers S6 as well as S7-S8", (request.get("rerun_after") or {}).get("stages"), ["S6", "S7", "S8"])
        controller.apply("dispatch", dict(request))
        state = controller.state()
        check_eq("R3: S6 is pending, with no receipt marks", (state["stages"]["S6"]["status"],
                 "code_only" in state["stages"]["S6"], "receipt_id" in state["stages"]["S6"]), ("pending", False, False))
        pipeline_s6 = pipeline_of(root)["stages"]["S6"]
        check_eq("H14: pipeline.json drops code_only and receipt_id of the lowered stage",
                 (pipeline_s6["status"], "code_only" in pipeline_s6, "receipt_id" in pipeline_s6, pipeline_s6.get("rerun_after")),
                 ("pending", False, False, request["id"]))
    finally:
        cleanup(root)


def a_skipped_stage_is_never_touched():
    """R4: a policy-skipped S5/S6 stays skipped - not named by the stamp, and left alone when a stamp names it."""
    root = temp_project("qa-rerun-r4-")
    try:
        controller = SCOPED.gate_a_task(root)
        controller.apply("policy", {"id": "no-implementation", "mode": "preparatory", "reason": "implementation absent",
                                    "source_revision": "src-1", "scope": ["TC-1"],
                                    "evidence_refs": [BASE.evidence_ref(root, "policy.txt")], "idempotency_key": "no-implementation"})
        controller.apply("code_only", {"id": "prep-s7", "stage": "S7", "reason": "no execution blocks in preparatory mode",
                                       "evidence_refs": [BASE.evidence_ref(root, "s7.txt")], "idempotency_key": "prep-s7"})
        controller.apply("code_only", {"id": "prep-s8", "stage": "S8", "reason": "reduced preparatory report",
                                       "evidence_refs": [BASE.evidence_ref(root, "s8.txt")], "idempotency_key": "prep-s8"})
        request = person_rework(controller, "S4", "qa-worker")
        check_eq("R4: the stamp names S7-S8 and gate A, never the skipped S5-S6",
                 request.get("rerun_after"), {"stages": ["S7", "S8"], "reviews": [], "decisions": ["gate-a"]})
        forged = dict(request, rerun_after={"stages": ["S5", "S6", "S7", "S8"], "reviews": [], "decisions": []})
        controller.apply("dispatch", forged)
        state = controller.state()
        check_eq("R4: a stamp that DOES name a skipped stage leaves it skipped, policy and all",
                 [(state["stages"][s]["status"], state["stages"][s].get("policy_id")) for s in ("S5", "S6")],
                 [("skipped", "no-implementation")] * 2)
        check_eq("R4: while the code-only S7-S8 are lowered by status",
                 [state["stages"][s]["status"] for s in ("S7", "S8")], ["pending", "pending"])
    finally:
        cleanup(root)


def a_ticket_changed_rework_is_not_stamped():
    """R5: the B-364 road re-runs its own stages; two writers of one re-run never."""
    root = temp_project("qa-rerun-r5-")
    try:
        controller = story_to_s8(root)
        check_eq("R5 control: the same call with the default cause carries the stamp",
                 "rerun_after" in person_rework(controller), True)
        check_eq("R5: cause ticket_changed carries none",
                 "rerun_after" in person_rework(controller, cause="ticket_changed"), False)
    finally:
        cleanup(root)


def a_closed_story_is_not_stamped():
    """R6: a closed story's rework is a reopen (C1-6): today's reopen stamp, nothing else lowered."""
    root = temp_project("qa-rerun-r6-")
    try:
        controller = CLOSED.closed_story(root)
        request = person_rework(controller)
        check_eq("R6: no stamp on a closed story", "rerun_after" in request, False)
        check("R6: the reopen stamp is as it was", bool(request.get("reopened_at")), str(request))
        controller.apply("dispatch", dict(request))
        state = controller.state()
        check_eq("R6: nothing after S5 was lowered, nothing staled, gate B stands",
                 ([state["stages"][s]["status"] for s in ("S6", "S7", "S8")], state["dispatches"]["dS5"]["status"],
                  state["decisions"]["B"]["status"]), (["completed"] * 3, "accepted", "approved"))
        check_eq("R6: and the person's words reopened the story as before",
                 pipeline_of(root).get("reopened_by_words"), WORDS)
    finally:
        cleanup(root)


def a_round_inside_an_open_stage_is_not_stamped():
    """R7: S4 is still open (its designer accepted, its critic not yet): the request is byte-equal to today's."""
    root = temp_project("qa-rerun-r7-")
    try:
        controller = designer_story(root)
        check_eq("R7 fixture: S4 is not completed", controller.state()["stages"]["S4"]["status"], "pending")
        with_words = controller.build_rework_request("S4", "qa-case-designer", ["TC-082"], WORDS, words_given=True)
        without = controller.build_rework_request("S4", "qa-case-designer", ["TC-082"], WORDS)
        check_eq("R7: no stamp, and the request is the one it always was (plus the person_words mark, R14)",
                 (with_words, "rerun_after" in with_words), (dict(without, person_words=True), False))
    finally:
        cleanup(root)


def an_approved_gate_decision_after_the_stage_goes_stale():
    """R8: a story a person reopened keeps its approved gate B; a person's rework of S5 stales it, so S9 cannot start on
    a gate nobody asks again. Gate A is before S5 and stands."""
    root = temp_project("qa-rerun-r8-")
    try:
        controller = CLOSED.closed_story(root)
        CLOSED.stray(controller, CLOSED.GHOST)      # C1-6a: `dispatch` refuses work on a closed story; the tail is written past it
        controller.release_dispatch(CLOSED.GHOST, "nobody is doing this, drop it")
        check_eq("R8 fixture: the story is open by a person's word and gate B is still approved",
                 (bool(CLOSED.story_closed(pipeline_of(root))), controller.state()["decisions"]["B"]["status"]),
                 (False, "approved"))
        request = person_rework(controller)
        check_eq("R8: the stamp names gate B's decision", request.get("rerun_after"),
                 {"stages": ["S6", "S7", "S8"], "reviews": ["dS5"], "decisions": ["B"]})
        controller.apply("dispatch", dict(request))
        state = controller.state()
        check_eq("R8: gate B is stale, gate A is approved",
                 (state["decisions"]["B"]["status"], state["decisions"]["A"]["status"]), ("stale", "approved"))
    finally:
        cleanup(root)


def a_forged_stamp_is_refused_whole():
    """R9: the controller refuses a `rerun_after` it did not build, naming the field; no event is written."""
    root = temp_project("qa-rerun-r9-")
    try:
        controller = story_to_s8(root)
        request = person_rework(controller)
        revision = controller.state()["revision"]
        path = root / "forged.json"
        empty = {"stages": [], "reviews": [], "decisions": []}
        # the last column re-roles the request (the reworked role is `qa-code-critic` there) or drops `rework_of`
        critic = {"role": "qa-code-critic"}
        for label, stamp, needle, change in (
                ("a stage that is not after S5", dict(empty, stages=["S3"]), "rerun_after.stages", {}),
                ("S5 itself", dict(empty, stages=["S5"]), "rerun_after.stages", {}),
                ("S9, past the last stage a rework can lower", dict(empty, stages=["S9"]), "rerun_after.stages", {}),
                ("ids that are not strings", dict(empty, stages=[6]), "rerun_after.stages", {}),
                ("a review no dispatch holds", dict(empty, reviews=["no-such-dispatch"]), "rerun_after.reviews", {}),
                ("a review of another stage", dict(empty, reviews=["dS6"]), "rerun_after.reviews", {}),
                ("a review by a role that does not close S5 (the author)", dict(empty, reviews=["dS5-author"]),
                 "rerun_after.reviews", critic),
                ("a review by the very role being reworked", dict(empty, reviews=["dS5"]), "rerun_after.reviews", critic),
                ("a decision nobody recorded", dict(empty, decisions=["gate-z"]), "rerun_after.decisions", {}),
                ("gate A on a rework of S5 (the builder names gate A only up to S4)", dict(empty, decisions=["gate-a"]),
                 "rerun_after.decisions", {}),
                ("a stamp on a request that reworks nothing", empty, "rework_of", {"rework_of": DROP}),
                ("not an object", ["S6"], "rerun_after must be", {}),
                ("a key the controller does not write", dict(empty, everything=True), "rerun_after must be", {})):
            forged = {k: v for k, v in dict(request, rerun_after=stamp, **change).items() if v is not DROP}
            path.write_text(json.dumps(forged), encoding="utf-8")
            result = run_script("controller.py", "--task-root", root, "--operation", "dispatch", "--input", path)
            check_eq(f"R9: {label}: exit 2", result.returncode, 2)
            check_in(f"R9: {label}: the refusal names the field", needle, result.stderr)
        check_eq("R9: nothing was written by any of them", Controller(root).state()["revision"], revision)
        path.write_text(json.dumps(request), encoding="utf-8")
        result = run_script("controller.py", "--task-root", root, "--operation", "dispatch", "--input", path)
        check("R9 control: the unforged request dispatches through the same door", result.returncode == 0, result.stderr)
    finally:
        cleanup(root)


def the_validator_stops_where_the_builder_stops():
    """R9 (bounds): the validator refuses every decision the builder would not name - unapproved, gate A past S4, gate B past
    S8 - and accepts the same decision AT each edge (the positive control). Pure: the validator reads only the state."""
    root = temp_project("qa-rerun-r9b-")
    try:
        controller = CLOSED.closed_story(root)
        state = controller.state()  # gates "A" and "B" approved
        def bound(stage, ids, state=state):
            body = {"stage": stage, "role": "qa-worker", "rework_of": "d", "rerun_after": {"decisions": ids}}
            return refusal(lambda: Controller._validate_rerun_after(body, state, int(stage[1:])))
        # the builder names exactly these decisions at each edge - the validator takes each of them
        for stage, named in (("S4", ["A", "B"]), ("S5", ["B"]), ("S8", ["B"])):
            built = Controller._rerun_stamp(state, stage, "qa-worker", ["TC-1"])
            check_eq(f"R9 control: the builder names {named} on a rework of {stage}", (built or {}).get("decisions"), named)
            check_eq(f"R9 control: so the validator takes {named} there", bound(stage, named), "")
        # and refuses the first decision past each bound
        for stage, ids in (("S5", ["A"]), ("S9", ["B"])):
            check_in(f"R9: {ids} on a rework of {stage} is beyond the builder's bound", "rerun_after.decisions", bound(stage, ids))
        stale = copy.deepcopy(state)
        stale["decisions"]["A"]["status"] = "stale"
        check_in("R9: an unapproved decision is refused although the builder's bound holds", "rerun_after.decisions",
                 bound("S4", ["A"], stale))
        check_eq("R9 control: the same decision approved is taken", bound("S4", ["A"]), "")
    finally:
        cleanup(root)


def the_projection_forgets_the_run_a_lowered_stage_was():
    """R10 + H14: after S7 completes again its pipeline.json entry carries no `rerun_after`, and a lowered stage drops
    the later-work marks of its previous life; S8, still waiting, keeps the stamp."""
    root = temp_project("qa-rerun-r10-")
    try:
        controller = story_to_s8(root)
        # an unstamped rework of S7 first: the completed S7 keeps its completion and grows later-work marks
        first = controller.build_rework_request("S7", "qa-worker", ["TC-1"], "the triage missed a failure")
        controller.apply("dispatch", dict(first))
        settle(controller, root, first)
        marks = pipeline_of(root)["stages"]["S7"]
        check_eq("H14 control: pipeline.json S7 carries the later-work marks before the stamp",
                 ("later_work_status" in marks, marks.get("later_work_settled")), (True, True))
        request = person_rework(controller, "S6", "qa-worker")
        check_eq("R10: a rework of S6 stamps S7 and S8", (request.get("rerun_after") or {}).get("stages"), ["S7", "S8"])
        controller.apply("dispatch", dict(request))
        pipeline = pipeline_of(root)["stages"]
        check_eq("R10: both lowered stages carry the stamp in pipeline.json",
                 (pipeline["S7"]["status"], pipeline["S7"].get("rerun_after"), pipeline["S8"].get("rerun_after")),
                 ("pending", request["id"], request["id"]))
        check_eq("H14: and S7 lost its later-work marks with its old run",
                 [key for key in ("later_work_status", "later_work_settled", "code_only", "receipt_id")
                  if key in pipeline["S7"]], [])
        settle(controller, root, request)
        redo(controller, root, "S7", "dS7-again")
        pipeline = pipeline_of(root)["stages"]
        check_eq("R10: after S7 completes again its entry carries no rerun_after",
                 (pipeline["S7"]["status"], "rerun_after" in pipeline["S7"]), ("done", False))
        check_eq("R10: S8, still waiting for its run, keeps the stamp", pipeline["S8"].get("rerun_after"), request["id"])
        redo(controller, root, "S8", "dS8-again")
        check_eq("R10: and loses it when it completes",
                 "rerun_after" in pipeline_of(root)["stages"]["S8"], False)
    finally:
        cleanup(root)


def the_stamp_is_applied_once_and_never_travels_in_a_continuation():
    """R11 + H6: the journal replayed twice gives one state; the stamp applied on top of its own replay changes nothing;
    `rerun_after` is no binding key, so a relaunch or a retry packet never carries it."""
    root = temp_project("qa-rerun-r11-")
    try:
        controller = story_to_s8(root)
        request = person_rework(controller)
        controller.apply("dispatch", dict(request))
        events = controller.store.read()
        after = projection(events)
        check_eq("R11: replaying the journal twice gives the same state", projection(events), after)
        again = copy.deepcopy(after)
        apply_rerun_after(again, request["id"], "S5", request.get("rerun_after") or {})
        check_eq("R11: the stamp applied again on the state it already made changes nothing", again, after)
        check_eq("H6: rerun_after is no binding key", "rerun_after" in BINDING_KEYS, False)
        record = after["dispatches"][request["id"]]
        check_eq("H6: the dispatch record's binding carries none", "rerun_after" in record["request_binding"], False)
        paused = dict(record, status="paused", checkpoint={"remaining": ["TC-1"]})
        for name, packet in (("relaunch", Controller._relaunch_packet(after, record)),
                             ("retry", Controller._retry_packet(after, paused))):
            check_eq(f"H6: a {name} packet of the stamped rework carries no rerun_after", "rerun_after" in packet, False)
    finally:
        cleanup(root)


def staling_the_critic_does_not_reset_the_repair_cap():
    """R12: the cap the driver reads is the AUTHOR's window (`budget_or_none("S5", "qa-automator", cases)`). A stamped
    rework counts as the one round it is, exactly as the same rework without the stamp does; the critic's staling adds
    nothing and removes nothing from it."""
    counted = {}
    for label, stamped in (("stamped", True), ("unstamped", False)):
        root = temp_project(f"qa-rerun-r12-{label}-")
        try:
            controller = story_to_s8(root)
            request = controller.build_rework_request("S5", "qa-automator", ["TC-1"], WORDS, words_given=stamped)
            controller.apply("dispatch", dict(request))
            state = Controller(root).state()
            window = {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"]}
            ledger = repair_ledger(state["dispatches"], window)
            budget = Controller(root).prepare({"stage": "S5", "role": "qa-automator", "scope": ["TC-1"]})["repair_budget"]
            counted[label] = (ledger["counted"], ledger["by_cause"], budget["counted"], budget["cap"],
                              state["dispatches"]["dS5"]["status"])
        finally:
            cleanup(root)
    check_eq("R12: the critic IS staled by the stamp and not without it (the comparison means something)",
             (counted["stamped"][4], counted["unstamped"][4]), ("stale", "accepted"))
    check_eq("R12: the author window's counted, by_cause and the budget the driver reads are the same either way",
             counted["stamped"][:4], counted["unstamped"][:4])
    check_eq("R12: that count is the one round of the rework (cap 2 is not reset to 0 by the staling)",
             counted["stamped"][:4], (1, {"test_defect": 1}, 1, 2))


def two_window_story(root):
    """S0-S8 accepted over TWO cases: TC-1 is the window the fixture's critic `dS5` reviewed, TC-2 (a manual-human plan row, so
    no S6 dispatch is owed for it) the window of a second critic `dS5-w2`, accepted before the stage closed."""
    scope = ("TC-1", "TC-2")
    mark_project(root)
    controller = Controller(root)
    controller.apply("initialize", {"scope": list(scope), "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(controller, root, f"S{number}")
    BASE.seed_plan(root, [SCOPED.plan_row(1, "automate"), SCOPED.plan_row(2, "manual-human")])
    pin(root, {"case_id": "TC-1", "version": "cv_1"}, {"case_id": "TC-2", "version": "cv_2"})
    controller.apply("decision", BASE.bind_gate_a(root, {
        "id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
        "source_revision": "src-1", "scope": list(scope), "input_revision": "src-1", "idempotency_key": "gate-a"}))
    s5_apply(controller, {"id": "dS5-w2", "stage": "S5", "role": "qa-code-critic", "scope": ["TC-2"], "input_hash": "w2",
                                  "budget": {}, "known_paths": {}, "idempotency_key": "d-w2"})
    controller.apply("accept", {"id": "dS5-w2", "status": "accepted", "stage_complete": False,
                                "evidence_refs": [BASE.evidence_ref(root, "w2.txt", "w2")], "idempotency_key": "a-w2"})
    for number in range(5, 9):
        BASE.accept_stage(controller, root, f"S{number}")
    return controller


def a_second_person_rework_of_a_pending_stage_stamps_its_own_window():
    """R13 (spec 12, t-679 queue (d)): two person-word reworks of S5, W1 then W2. After the first one's re-run is accepted S5
    is `pending`, no longer `completed`; the second still sets W2's critic aside, so its acceptance cannot approve work that
    was reworked. Controls: no words -> no stamp (H1); a window the first stamp already staled is not named again; an in-stage
    pending S5 no stamped rework reopened stamps nothing."""
    root = temp_project("qa-rerun-r13-")
    try:
        controller = two_window_story(root)
        first = controller.build_rework_request("S5", "qa-automator", ["TC-1"], WORDS, words_given=True)
        check_eq("R13 fixture: the first stamp names W1's critic only - W2's critic is not a review of TC-1",
                 first.get("rerun_after"), {"stages": ["S6", "S7", "S8"], "reviews": ["dS5"], "decisions": []})
        controller.apply("dispatch", dict(first))
        settle(controller, root, first)
        state = controller.state()
        check_eq("R13 fixture: S5 is pending after the first rework, W2's critic still stands",
                 (state["stages"]["S5"]["status"], state["dispatches"]["dS5"]["status"], state["dispatches"]["dS5-w2"]["status"]),
                 ("pending", "stale", "accepted"))
        check_eq("R13 control: the same rework without a person's words stamps nothing (a driver repair, H1)",
                 "rerun_after" in controller.build_rework_request("S5", "qa-automator", ["TC-2"], "the finding", words_given=False),
                 False)
        check_eq("R13 control: a window the first stamp already staled is not named again - nothing left to stamp",
                 "rerun_after" in controller.build_rework_request("S5", "qa-automator", ["TC-1"], WORDS, words_given=True), False)
        second = controller.build_rework_request("S5", "qa-automator", ["TC-2"], WORDS, words_given=True)
        check_eq("R13: the second person's rework of S5 on W2 stamps W2's critic although S5 is pending, and nothing else",
                 second.get("rerun_after"), {"stages": [], "reviews": ["dS5-w2"], "decisions": []})
        controller.apply("dispatch", dict(second))
        state = controller.state()
        check_eq("R13: W2's critic is staled, and says which rework did it",
                 (state["dispatches"]["dS5-w2"]["status"], state["dispatches"]["dS5-w2"].get("stale_by_rework")),
                 ("stale", second["id"]))
        check_eq("R13: S5 is running for the second rework, stamped with it",
                 {k: state["stages"]["S5"].get(k) for k in ("status", "dispatch_id", "rerun_after")},
                 {"status": "running", "dispatch_id": second["id"], "rerun_after": second["id"]})
        settle(controller, root, second)
        action = Controller(root).next_action()
        check_eq("R13: both reviews are owed again: next goes back to S5", (action["action"], action.get("stage")),
                 ("prepare_stage", "S5"))
        ledger = repair_ledger(Controller(root).state()["dispatches"], {"stage": "S5", "role": "qa-automator", "scope": ["TC-2"]})
        check_eq("R13: the cap still counts the second rework as the one round it is (the staling resets nothing)",
                 (ledger["counted"], ledger["by_cause"]), (1, {"test_defect": 1}))
    finally:
        cleanup(root)
    root = temp_project("qa-rerun-r13-s4-")
    try:
        # R7's fixture: S4 is pending mid-round (its designer accepted, its critic not yet) and no stamped rework opened it
        check_eq("R13 control: a pending stage no stamped rework reopened stamps nothing even with a person's words",
                 "rerun_after" in designer_story(root).build_rework_request("S4", "qa-case-designer", ["TC-082"], WORDS,
                                                                            words_given=True), False)
    finally:
        cleanup(root)


def a_rework_without_words_is_todays_flow():
    """H1: `--reason` (the driver's repairs, the conductor's refusal repairs) gets no stamp and stales nothing it did not
    name - an S5 rework leaves S6-S8 and the critic alone; an S7 repair leaves the S5 critic and S6 untouched."""
    for stage, role in (("S5", "qa-automator"), ("S7", "qa-worker")):
        root = temp_project(f"qa-rerun-h1-{stage}-")
        try:
            story_to_s8(root)
            built = rework_cli(root, "--reason", "the refusal, verbatim", "--build-only", stage=stage, role=role)
            check(f"H1: the {stage} rework builds", built.returncode == 0, built.stderr)
            check_eq(f"H1: --reason only: no stamp on {stage}", "rerun_after" in json.loads(built.stdout)["request"], False)
            result = rework_cli(root, "--reason", "the refusal, verbatim", stage=stage, role=role)
            check(f"H1: the {stage} rework dispatches", result.returncode == 0, result.stderr)
            state = Controller(root).state()
            check_eq(f"H1: {stage} --reason: no stage lowered, no dispatch staled, S5 critic and S6 untouched",
                     ([state["stages"][s]["status"] for s in ("S5", "S6", "S7", "S8")],
                      sorted(i for i, d in state["dispatches"].items() if d["status"] == "stale")),
                     (["completed"] * 4, []))
        finally:
            cleanup(root)


def the_person_words_mark_follows_the_words_file():
    """R14 (t-694, F1): the request and the dispatch record carry `person_words: true` exactly when the reason is a person's words
    (`--words-file`, the same `words_given` input as the stamp) - also when the stamp is empty (an S8 rework) - and never with
    `--reason` (a finding typed by code). The gate note quotes `on your words` only for the mark."""
    root = temp_project("qa-rerun-r14-")
    try:
        controller = story_to_s8(root)
        built = rework_cli(root, "--words-file", words_file(root), "--build-only")
        check_eq("R14: --words-file: the built request carries the mark", json.loads(built.stdout)["request"].get("person_words"), True)
        built = rework_cli(root, "--reason", "the refusal, verbatim", "--build-only")
        check_eq("R14: --reason: no mark on the built request", "person_words" in json.loads(built.stdout)["request"], False)
        check_eq("R14: the library call without words_given: no mark", "person_words" in controller.build_rework_request(
            "S5", "qa-automator", ["TC-1"], WORDS), False)
        check_eq("R14: an empty stamp (S8, nothing after it) still carries the mark",
                 person_rework(controller, "S8", "qa-worker").get("person_words"), True)
        result = rework_cli(root, "--words-file", words_file(root))
        check("R14: the rework dispatches", result.returncode == 0, result.stderr)
        record = Controller(root).state()["dispatches"][json.loads(result.stdout)["request"]["id"]]
        check_eq("R14: the dispatch RECORD keeps the mark (the gate note reads the record)", record.get("person_words"), True)
    finally:
        cleanup(root)
    root = temp_project("qa-rerun-r14b-")
    try:
        story_to_s8(root)
        result = rework_cli(root, "--reason", "the refusal, verbatim", stage="S7", role="qa-worker")
        check("R14: a --reason rework dispatches", result.returncode == 0, result.stderr)
        record = Controller(root).state()["dispatches"][json.loads(result.stdout)["request"]["id"]]
        check_eq("R14: and its record has no mark", "person_words" in record, False)
    finally:
        cleanup(root)


def a_stamp_with_nothing_to_set_aside_is_no_stamp():
    """H1 edge: a person-word rework of the last stage has no completed stage above it, no review of its own and no gate B
    decision: an empty stamp set is no stamp, and the request is the one a `--reason` rework builds."""
    root = temp_project("qa-rerun-empty-")
    try:
        controller = story_to_s8(root)
        with_words = person_rework(controller, "S8", "qa-worker")
        check_eq("empty stamp set: the request carries no rerun_after and equals the unstamped one (plus the person_words mark, R14)",
                 (with_words, "rerun_after" in with_words),
                 (dict(controller.build_rework_request("S8", "qa-worker", ["TC-1"], WORDS), person_words=True), False))
        controller.apply("dispatch", dict(with_words))
        state = controller.state()
        check_eq("empty stamp set: applying it lowers and stales nothing else",
                 ([state["stages"][s]["status"] for s in ("S5", "S6", "S7", "S8")],
                  sorted(i for i, d in state["dispatches"].items() if d["status"] == "stale")),
                 (["completed"] * 4, []))
    finally:
        cleanup(root)


def only_one_dispatch_runs_at_a_time_and_a_second_rework_stamps_again():
    """Edge 3: a second rework while the first runs is refused and writes nothing (the controller's own running-dispatch
    rule). Edge 4: after the stages ran again, a new person's rework stamps them again under ITS id."""
    root = temp_project("qa-rerun-e34-")
    try:
        controller = story_to_s8(root)
        first = person_rework(controller, "S6", "qa-worker")
        controller.apply("dispatch", dict(first))
        revision = controller.state()["revision"]
        second = person_rework(controller, "S6", "qa-worker")
        message = refusal(lambda: controller.apply("dispatch", dict(second)))
        check_in("edge 3: a rework while another dispatch runs is refused", "active dispatch", message)
        check_eq("edge 3: and wrote nothing", controller.state()["revision"], revision)
        settle(controller, root, first)
        redo(controller, root, "S7", "dS7-again")
        redo(controller, root, "S8", "dS8-again")
        later = person_rework(controller, "S6", "qa-worker")
        check_eq("edge 4: the stages that ran again are named again", (later.get("rerun_after") or {}).get("stages"), ["S7", "S8"])
        controller.apply("dispatch", dict(later))
        state = controller.state()
        check_eq("edge 4: and carry the NEW rework's id, so each re-show can say what changed",
                 [state["stages"][s].get("rerun_after") for s in ("S7", "S8")], [later["id"]] * 2)
        check("edge 4: the two reworks have different ids", first["id"] != later["id"], first["id"])
    finally:
        cleanup(root)


def a_designer_rework_after_gate_a_stales_the_critic_and_the_gate():
    """Edge 7 + spec 5.6: no case review after gate A (the controller's CASE_REVIEW_AFTER_GATE_A), until a person's rework
    of the designer stales gate A and the critic's acceptance - then the critic may run again."""
    root = temp_project("qa-rerun-s4-")
    try:
        scope = ("TC-082", "TC-099")
        controller = designer_story(root, scope)
        controller.apply("dispatch", {"id": "S4-qa-case-critic-1", "stage": "S4", "role": "qa-case-critic",
                                      "scope": list(scope), "input_hash": "critic-input", "budget": {}, "known_paths": {},
                                      "idempotency_key": "d-critic"})
        BASE.record_stage_acceptance(root, "S4", DESIGNER)  # E-B11: the critic's closing accept reviews the designer's dispatch
        controller.apply("accept", {"id": "S4-qa-case-critic-1", "status": "accepted", "stage_complete": True,
                                    "evidence_refs": [BASE.evidence_ref(root, "critic.txt")], "idempotency_key": "a-critic"})
        controller.apply("decision", BASE.bind_gate_a(root, {
            "id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
            "source_revision": "src-1", "scope": list(scope), "input_revision": "src-1", "idempotency_key": "gate-a"}))
        critic = {"id": "S4-qa-case-critic-2", "stage": "S4", "role": "qa-case-critic", "scope": list(scope),
                  "input_hash": "critic-input-2", "budget": {}, "known_paths": {}, "idempotency_key": "d-critic-2"}
        check_in("edge 7: after gate A the controller refuses a new case review", "CASE_REVIEW_AFTER_GATE_A",
                 refusal(lambda: controller.apply("dispatch", dict(critic))))
        request = controller.build_rework_request("S4", "qa-case-designer", ["TC-082"], WORDS, words_given=True)
        check_eq("spec 5.6: the stamp stales the critic's review and gate A, and lowers no stage (S5 never ran)",
                 request.get("rerun_after"),
                 {"stages": [], "reviews": ["S4-qa-case-critic-1"], "decisions": ["gate-a"]})
        controller.apply("dispatch", dict(request))
        settle(controller, root, request)
        state = controller.state()
        check_eq("spec 5.6: the critic's acceptance and gate A are stale, S4 is open again",
                 (state["dispatches"]["S4-qa-case-critic-1"]["status"], state["decisions"]["gate-a"]["status"],
                  state["stages"]["S4"]["status"]), ("stale", "stale", "pending"))
        check_eq("edge 7: now the case review may run again (gate A is no longer current)",
                 refusal(lambda: controller.apply("dispatch", dict(critic))), "")
    finally:
        cleanup(root)


def a_paid_round_stays_paid_when_its_own_stage_sets_it_aside():
    """R15 (C1-5a, A1; named R15 because R13 and R14 are taken above; the finding 20261010-ledger-kritika-sbrasyvaetsya-pri-stale):
    a `stale` dispatch counts as a paid round ONLY when a rework of the SAME stage set it aside (the `reviews` stamp: an S5 rework
    stales the S5 critic - its round was spent). A rework of an EARLIER stage (S3/S4) that stales S5 through the stamp's `stages`
    step opens a NEW window: counted 0, or the re-run window's first dispatch would count as round 1 or be refused. Both directions
    run through the real replay (`apply_rerun_after`) and the real ledger."""
    def state_of(rework_stage):
        def d(identifier, role, stage="S5", **extra):
            return dict({"id": identifier, "stage": stage, "role": role, "scope": ["TC-1"], "status": "accepted"}, **extra)
        return {"dispatches": {"a1": d("a1", "qa-automator"), "a2": d("a2", "qa-automator"),
                               "c1": d("c1", "qa-code-critic"), "c2": d("c2", "qa-code-critic"),
                               "r": d("r", "qa-automator" if rework_stage == "S5" else "qa-case-designer", stage=rework_stage,
                                      status="running", rework_of="x")},
                "stages": {"S5": {"status": "completed"}}, "decisions": {}}
    critic = {"stage": "S5", "role": "qa-code-critic", "scope": ["TC-1"]}
    author = dict(critic, role="qa-automator")
    unstaled = state_of("S5")
    check_eq("R15 fixture: before any rework the critic has had one round (c2), the author two (a2 and the rework r)",
             (repair_ledger(unstaled["dispatches"], critic)["counted"], repair_ledger(unstaled["dispatches"], author)["counted"]), (1, 2))
    own = state_of("S5")
    apply_rerun_after(own, "r", "S5", {"stages": [], "reviews": ["c1", "c2"], "decisions": []})
    check_eq("R15: the S5 rework stales the critic through the `reviews` stamp, with the mark",
             [(own["dispatches"][i]["status"], own["dispatches"][i].get("stale_by_rework")) for i in ("c1", "c2")],
             [("stale", "r"), ("stale", "r")])
    check_eq("R15: its round stays paid - the critic's counted stays 1 (the cap is not reset by the person's word)",
             repair_ledger(own["dispatches"], critic)["counted"], 1)
    earlier = state_of("S4")
    apply_rerun_after(earlier, "r", "S4", {"stages": ["S5"], "reviews": [], "decisions": []})
    check_eq("R15 fixture: the S4 rework stales every accepted S5 dispatch through the stamp's `stages` step",
             sorted(i for i, d in earlier["dispatches"].items() if d["status"] == "stale"), ["a1", "a2", "c1", "c2"])
    check_eq("R15: ...and that opens a NEW window - the critic's and the author's counted are 0, not 1",
             (repair_ledger(earlier["dispatches"], critic)["counted"], repair_ledger(earlier["dispatches"], author)["counted"]), (0, 0))
    check_eq("R15 control: a stale dispatch whose mark names no dispatch (an old record) is not a paid round",
             repair_ledger({"c1": dict(earlier["dispatches"]["c1"], stale_by_rework="gone"),
                            "c2": dict(earlier["dispatches"]["c2"], stale_by_rework="gone")}, critic)["counted"], 0)


def s6_runner_rework_takes_its_half_from_its_cases():
    """FB-9 (spec t-1361 R12, F-4): a new-mode S6 qa-runner rework says which half it runs and carries the block.
    K-W1 kind + ids + the dispatch is accepted; K-W2 mixed halves, two doors; K-W2b kind unknown; K-W3 over five split;
    K-W4 the parent is the same half's; K-W5 the automation half is unbounded; K-W6 the legacy mode is unchanged.
    KILLS (M17) the parent read from `prior[-1]` (K-W4, K-W4b) or the kind from the records alone (K-W1); (M18) a mixed rework
    allowed (K-W2); (M19) the block rule skipped (K-W3); (M20) one automated case deciding the half for cases of neither (K-W7)."""
    import test_story_step_manual_block as MB
    import test_fixes_13797 as F
    from detector_verdict import split_items
    manual_cases = ["TC-2", "TC-3", "TC-4", "TC-5", "TC-6"]
    root = temp_dir("qa-fb9-rework-")
    try:
        c = MB.real_story(root, MB.MIXED_7)
        F.runner(c, root, "S6-qa-runner-1", "manual", manual_cases, False)
        F.runner(c, root, "S6-qa-runner-2", "manual", ["TC-7"], False)
        F.runner(c, root, "S6-qa-runner-3", "automation", ["TC-1"], False)       # the LAST accepted runner is the other half
        request = c.build_rework_request("S6", "qa-runner", ["TC-2"], "recheck TC-2")
        check_eq("K-W1: a manual rework is a manual block of its cases",
                 (request["execution_kind"], request["manual_case_ids"], request["scope"]), ("manual", ["TC-2"], ["TC-2"]))
        check_eq("K-W4: its parent is the manual block that HOLDS TC-2 (E25), not the later block or the automation packet",
                 request["rework_of"], "S6-qa-runner-1")
        joined = c.build_rework_request("S6", "qa-runner", ["TC-6", "TC-7"], "recheck both")
        check_eq("K-W4b: cases of two manual blocks take the later block that holds one (one block of two cases)",
                 (joined["rework_of"], joined["manual_case_ids"]), ("S6-qa-runner-2", ["TC-6", "TC-7"]))
        c.apply("dispatch", dict(request))
        check_eq("K-W1: and the controller dispatches it", c.state()["dispatches"][request["id"]]["manual_case_ids"], ["TC-2"])
        F.runner(c, root, request["id"], "manual", ["TC-2"], False)
        auto = c.build_rework_request("S6", "qa-runner", ["TC-1"], "recheck TC-1")
        check_eq("K-W4: an automation rework resumes the automation packet", (auto["execution_kind"], auto["rework_of"]), ("automation", "S6-qa-runner-3"))
        check_eq("K-W5: ...and carries no block", "manual_case_ids" in auto, False)
        # K-W2: both halves in one call
        try:
            c.build_rework_request("S6", "qa-runner", ["TC-1", "TC-2"], "both")
            check("K-W2: a rework over both halves is refused", False)
        except ValueError as exc:
            text = str(exc)
            check_in("K-W2: ...with the manual door", "--cases TC-2 ", text)
            check_in("K-W2: ...and the automated door", "--cases TC-1`", text)
            check_in("K-W2: ...and the reason (one packet, one half)", "one packet runs one half", text)
        # K-W3: over five splits, whole, with the first block's door
        try:
            c.build_rework_request("S6", "qa-runner", manual_cases + ["TC-7"], "all six", )
            check("K-W3: a manual rework of six cases is refused", False)
        except ValueError as exc:
            text = str(exc)
            check_in("K-W3: the split is said", "it names 6 cases, at most 5: split the block", text)
            check_in("K-W3: ...with the first block's rework command", "--cases TC-2,TC-3,TC-4,TC-5,TC-6 --reason", text)
            check_in("K-W3: ...and the rest counted", "1 more block(s) of at most 5 for: TC-7", text)
        # the block problems join the call's other problems in ONE refusal (class rule 27.10)
        try:
            c.build_rework_request("S6", "qa-runner", manual_cases + ["TC-7"], "", purpose="nonsense")
            check("K-W3: a bad call plus a long block is refused", False)
        except ValueError as exc:
            check_eq("K-W3: ...whole: purpose, reason and the block in one answer", len(split_items(str(exc)) or []) >= 3, True)
        # K-W2b: the kind cannot be established (the plan derives nothing; the records hold both halves / none)
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
                c, "stage_scope", lambda *a, **k: {"derived": False, "scope": [], "reason": "no dispositions"}):
            try:
                c.build_rework_request("S6", "qa-runner", ["TC-2", "TC-1"], "x")
                check("K-W2b: no disposition and no single half: refused", False)
            except ValueError as exc:
                check_in("K-W2b: no disposition and no single half: refused", "the kind of this S6 qa-runner rework cannot be established", str(exc))
                check_in("K-W2b: ...with the within-one-half door", "--cases <the cases of one half>", str(exc))
            single = c.build_rework_request("S6", "qa-runner", ["TC-1"], "x")
            check_eq("K-W2b control: records that hold the case in ONE half give the kind", single["execution_kind"], "automation")
        # K-W7 (F1): a case of NEITHER half never rides along on the automation half (and not on the manual one)
        root3 = temp_dir("qa-fb9-rework-neither-")
        try:
            c3 = MB.real_story(root3, ["automate", "manual-human", "manual-agent"])
            F.runner(c3, root3, "S6-qa-runner-1", "automation", ["TC-1"], False)
            for label, cases in (("automated + manual-human", ["TC-1", "TC-2"]), ("manual-human alone", ["TC-2"]),
                                 ("manual-agent + manual-human", ["TC-3", "TC-2"])):
                try:
                    c3.build_rework_request("S6", "qa-runner", cases, "probe")
                    check(f"K-W7: {label} is refused", False)
                except ValueError as exc:
                    check_in(f"K-W7: {label} is refused naming TC-2 and the stage-scope door", "TC-2", str(exc))
                    check_in(f"K-W7: ...{label}: the stage-scope door", "--operation stage-scope", str(exc))
            check_eq("K-W7 control: the automated case alone is still reworked",
                     c3.build_rework_request("S6", "qa-runner", ["TC-1"], "probe")["execution_kind"], "automation")
        finally:
            cleanup(root3)
        # K-W5: seven automated cases, no bound
        root2 = temp_dir("qa-fb9-rework-auto-")
        try:
            c2 = MB.real_story(root2, ["automate"] * 7)
            F.runner(c2, root2, "S6-qa-runner-1", "automation", [f"TC-{i}" for i in range(1, 8)], True)
            wide = c2.build_rework_request("S6", "qa-runner", [f"TC-{i}" for i in range(1, 8)], "all")
            check_eq("K-W5: seven automated cases are one packet", (wide["execution_kind"], len(wide["scope"]), "manual_case_ids" in wide), ("automation", 7, False))
        finally:
            cleanup(root2)
        # K-W6: the legacy mode is unchanged (no kind is required there)
        legacy = dict(c.state(), plan_contract_mode="legacy")
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(c, "state", lambda: legacy):
            old = c.build_rework_request("S6", "qa-runner", ["TC-2"], "x")
            check_eq("K-W6: a legacy-mode rework carries neither field", ("execution_kind" in old, "manual_case_ids" in old), (False, False))
    finally:
        cleanup(root)


def rh110_s6_half_membership():
    """RH1-10 (spec t-1421 part B, DC1-13 / DC1-15): ONE membership function, `Controller._half_membership_problems`, for both S6
    halves on every road. Keys B-K1..B-K11 and B-K16, edges B-E1..B-E13.
    KILLS (one test file, this one): the automation call dropped from `validate` (B-K2), from `prepare` (B-K1) or from
    `build_rework_request` (B-K7); `_case_rows` errors read as `[]` (B-K6, B-K6b); `execution_kind:` put back into the empty-cases door
    (B-K8); the `named` cut moved to 19 or 21 (B-K10); an id stripped before it is judged (B-K11); the manual sentences reworded (B-K4)."""
    import unittest.mock as mock
    import waiver
    import test_story_step_manual_block as MB
    import test_fixes_13797 as F
    from no_move import check_args
    from controller import MANUAL_BLOCK_CASES, SCOPE_SHOWN

    def refused_with(call):
        try:
            call()
        except (StateConflict, ValueError) as exc:
            return str(exc)
        return None

    root = temp_dir("qa-rh110-")
    try:
        c = MB.real_story(root, MB.MIXED_7)          # TC-1 automate; TC-2..TC-7 manual-agent
        # B-K1: prepare, automation, over a manual-agent case -> cause 1, with the real manual command as its door
        text = refused_with(lambda: c.prepare({"stage": "S6", "role": "qa-runner", "id": "a1", "scope": ["TC-2"], "execution_kind": "automation"}))
        check_in("B-K1: prepare refuses an automation packet over a manual-agent case (cause 1)", "disposed manual-agent in the plan: TC-2", text or "")
        check_in("B-K1: ...with the real manual command as its door",
                 f"story_step.py start --stage S6 --role qa-runner --execution-kind manual --scope <1..{MANUAL_BLOCK_CASES} ids>", text or "")
        check_in("B-K1: ...and the disposition road", "S3 rework, then gate A", text or "")
        ok = c.prepare({"stage": "S6", "role": "qa-runner", "id": "a1", "scope": ["TC-1"], "execution_kind": "automation"})
        check_eq("B-K1 control: the automated case is prepared", ok["dispatch_request"]["scope"], ["TC-1"])
        default = c.prepare({"stage": "S6", "role": "qa-runner", "id": "a1", "execution_kind": "automation"})
        check_eq("B-K1 control: no scope given: the derived automated scope", default["dispatch_request"]["scope"], ["TC-1"])
        # B-K2: validate (apply "dispatch") over a handed automate case -> cause 2; built BEFORE the hand-over, so only `validate` can stop it
        request = dict(ok["dispatch_request"])
        c._handed_cases = lambda: {"TC-1": "profile-x"}
        text = refused_with(lambda: c.apply("dispatch", dict(request)))
        check_in("B-K2: apply('dispatch') refuses a handed automate case (cause 2)", "handed to the person by their recorded word: TC-1", text or "")
        check_in("B-K2: ...leave it out of the automated run", "leave them out of the automated run", text or "")
        check_eq("B-K2: ...and nothing was registered", "a1" in c.state()["dispatches"], False)
        c._handed_cases = lambda: {}
        # B-K3: a case in neither half (manual-human) -> cause 3 with the stage-scope door and the kind
        root3 = temp_dir("qa-rh110-neither-")
        try:
            c3 = MB.real_story(root3, ["automate", "manual-human", "manual-agent"])
            got = c3._half_membership_problems("S6", c3.state(), ["TC-1", "TC-2"], "automation")
            check_eq("B-K3: a manual-human case on the automation half: ONE sentence", len(got), 1)
            check_in("B-K3: ...cause 3 names the case", "not an automated case of the approved plan: TC-2", got[0])
            check_in("B-K3: ...with the stage-scope door and the kind",
                     "`controller.py --operation stage-scope` with `execution_kind: automation` lists the cases the automated half may name", got[0])
            check_eq("B-E3 / B-K3 (manual twin): the same case on the manual half is cause 3 too",
                     [t.split(":")[0] for t in c3._half_membership_problems("S6", c3.state(), ["TC-2"], "manual")], ["not a manual-agent case of the approved plan"])
        finally:
            cleanup(root3)
        # B-K4: the manual half's sentences are byte for byte today's
        c._handed_cases = lambda: {"TC-3": "profile-x"}
        check_eq("B-K4: the manual half's three sentences, byte for byte",
                 c._half_membership_problems("S6", c.state(), ["TC-1", "TC-3", "TC-99", "TC-2"], "manual"),
                 ["disposed automate in the plan: TC-1 - the automated half runs them (`story_step.py start --stage S6 --role qa-runner "
                  "--execution-kind automation`); to check them by hand, the plan row's disposition changes (S3 rework, then gate A)",
                  "handed to the person by their recorded word: TC-3 - nobody dispatches them; leave them out of the block",
                  "not a manual-agent case of the approved plan: TC-99 - `controller.py --operation stage-scope` with `execution_kind: manual` "
                  "lists the cases a block may name"])
        # B-E4 / m1 (t-1452, FR-2): a HANDED case is judged handed FIRST in both halves, so its door is the handed door and never
        # leads to the other half's refusal of the same case. KILLS: the handed test moved back behind the other half's.
        got = c._half_membership_problems("S6", c.state(), ["TC-3"], "automation")
        check_eq("B-E4/m1: a handed manual-agent case on the automation half is cause 2 (handed), not 'a manual block runs them'",
                 [t.split(":")[0] for t in got], ["handed to the person by their recorded word"])
        check_in("B-E4/m1: ...it names the case", "TC-3", got[0])
        c._handed_cases = lambda: {"TC-1": "profile-x"}
        got = c._half_membership_problems("S6", c.state(), ["TC-1"], "manual")
        check_eq("m1 manual twin: a handed automate case on the manual half is cause 2 (handed), not 'the automated half runs them'",
                 [t.split(":")[0] for t in got], ["handed to the person by their recorded word"])
        c._handed_cases = lambda: {"TC-3": "profile-x"}
        check_eq("m1 control: an unhanded manual-agent case on the automation half still gets the manual-block door",
                 [t.split(":")[0] for t in c._half_membership_problems("S6", c.state(), ["TC-2"], "automation")], ["disposed manual-agent in the plan"])
        c._handed_cases = lambda: {}
        # q1: prepare with a derived EMPTY automated half never falls back to the whole approved scope - it refuses, naming the half
        root1 = temp_dir("qa-rh110-q1-")
        try:
            c1 = MB.real_story(root1, ["manual-agent", "manual-agent"])
            text = refused_with(lambda: c1.prepare({"stage": "S6", "role": "qa-runner", "id": "q1", "execution_kind": "automation"})) or ""
            check_in("q1: an empty derived automated half is named", "the automated half of the approved plan is empty", text)
            check_in("q1: ...with the manual door", "--execution-kind manual --scope", text)
            check_not_in("q1: ...and never the membership prefix over cases nobody named", "must name only cases", text)
            check_eq("q1 control: a given scope is still judged by the membership check",
                     "disposed manual-agent in the plan: TC-1" in (refused_with(lambda: c1.prepare(
                         {"stage": "S6", "role": "qa-runner", "id": "q1", "scope": ["TC-1"], "execution_kind": "automation"})) or ""), True)
        finally:
            cleanup(root1)
        c._handed_cases = lambda: {}
        # B-K5: a readable plan with no dispositions -> the declared skip, both halves
        with mock.patch.object(c, "stage_scope", lambda *a, **k: {"derived": False, "scope": [], "reason": "no dispositions"}):
            check_eq("B-K5: no dispositions -> [] for both halves",
                     (c._half_membership_problems("S6", c.state(), ["TC-1", "TC-99"], "manual"),
                      c._half_membership_problems("S6", c.state(), ["TC-1", "TC-99"], "automation")), ([], []))
        # only S6 has two halves; an unknown kind reads nothing
        check_eq("B-E5: an S5 packet and an unknown kind meet no half check",
                 (c._half_membership_problems("S5", c.state(), ["TC-2"], "automation"), c._half_membership_problems("S6", c.state(), ["TC-2"], "")), ([], []))
        # B-K6: `_case_rows` raises -> the unknown is ONE sentence with the person's-word door, for BOTH halves; the S6 waiver passes it
        real_rows = c._case_rows
        for error in (StateConflict("plan is broken"), ValueError("plan rows are not a list")):
            c._case_rows = lambda s, e=error: (_ for _ in ()).throw(e)
            for kind, ids in (("manual", ["TC-2"]), ("automation", ["TC-1"])):
                got = c._half_membership_problems("S6", c.state(), ids, kind)
                check_eq(f"B-K6: {type(error).__name__} on the {kind} half: ONE sentence (the unknown never reads as a pass)", len(got), 1)
                check_in(f"B-K6: ...{kind}: it names the case, the reason and the S6 block",
                         f"the plan could not be read to judge which half {ids[0]} belong to ({error}) - repair the plan (S3 rework) or record "
                         "the person's word (`waiver.py --stage S6 --block \"S6 half membership: unreadable\"`)", got[0])
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8-sig"))
        waiver.apply_stage_override(pipeline, "S6", "S6 half membership: unreadable", "accept - the person wrote: go on", "2026-10-28T00:00:00")
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("B-K6: with the person's word recorded at S6 the same unknown passes, both halves",
                 (c._half_membership_problems("S6", c.state(), ["TC-2"], "manual"), c._half_membership_problems("S6", c.state(), ["TC-1"], "automation")), ([], []))
        pipeline["stage_overrides"][0]["stage"] = "S5"
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("B-K6 negative control: a word recorded at another stage passes nothing",
                 len(c._half_membership_problems("S6", c.state(), ["TC-1"], "automation")), 1)
        pipeline["stage_overrides"] = []
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        c._case_rows = real_rows
        # q3 (AR-28, F-8 sibling): `validate`'s empty-scope check does not pass when the plan cannot be read; same road and block as B-K6
        okq = c.prepare({"stage": "S6", "role": "qa-runner", "id": "q3", "scope": ["TC-1"], "execution_kind": "automation"})
        empty = dict(okq["dispatch_request"], scope=[])
        text = refused_with(lambda: c.apply("dispatch", dict(empty))) or ""
        check_in("q3 control: a READABLE plan refuses the empty scope as before", "has an empty scope while the approved plan expects 1", text)
        c._case_rows = lambda s: (_ for _ in ()).throw(StateConflict("plan is broken"))
        text = refused_with(lambda: c.apply("dispatch", dict(empty))) or ""
        check_in("q3: an UNREADABLE plan does not pass an empty scope (the unknown is not a pass)", "the plan could not be read to judge", text)
        check_in("q3: ...with the S6 person's-word block", "S6 half membership: unreadable", text)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8-sig"))
        waiver.apply_stage_override(pipeline, "S6", "S6 half membership: unreadable", "accept - the person wrote: go on", "2026-10-28T00:00:00")
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("q3: with the person's word recorded the unreadable-plan sentence is gone (read, not dispatched: a pass would register)",
                 c._unreadable_plan_problems(c.state(), "x"), [])
        pipeline["stage_overrides"] = []
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        c._case_rows = real_rows
        # t-1459 (the S5 twin of q3): `validate`'s empty-scope check at S5 over an unreadable plan refuses with its own block,
        # and only a word recorded AT S5 under THAT block passes it (the S6 block and a word at S6 pass nothing).
        ok5 = c.prepare({"stage": "S5", "role": "qa-automator", "id": "q3-s5", "scope": ["TC-1"]})
        empty5 = dict(ok5["dispatch_request"], scope=[])
        text = refused_with(lambda: c.apply("dispatch", dict(empty5))) or ""
        check_in("q3 S5 control: a READABLE plan refuses the empty S5 scope as before", "has an empty scope while the approved plan expects", text)
        c._case_rows = lambda s: (_ for _ in ()).throw(StateConflict("plan is broken"))
        text = refused_with(lambda: c.apply("dispatch", dict(empty5))) or ""
        check_in("q3 S5: an UNREADABLE plan does not pass an empty scope", "the plan could not be read to judge", text)
        check_in("q3 S5: ...with the S5 person's-word block", "--stage S5 --block \"S5 scope: unreadable\"", text)
        check_not_in("q3 S5: ...and not the S6 block", "S6 half membership", text)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8-sig"))
        waiver.apply_stage_override(pipeline, "S6", "S5 scope: unreadable", "accept - the person wrote: go on", "2026-10-28T00:00:00")
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("q3 S5 negative control: the S5 block recorded at S6 passes nothing at S5",
                 len(c._unreadable_plan_problems(c.state(), "x", "S5")), 1)
        pipeline["stage_overrides"] = []
        waiver.apply_stage_override(pipeline, "S5", "S5 scope: unreadable", "accept - the person wrote: go on", "2026-10-28T00:00:00")
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("q3 S5: with the person's word recorded at S5 the unreadable-plan sentence is gone",
                 c._unreadable_plan_problems(c.state(), "x", "S5"), [])
        pipeline["stage_overrides"] = []
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        c._case_rows = real_rows
        # B-K7: a rework of the automation half over a handed case -> cause 2 joins the call's problems
        F.runner(c, root, "S6-qa-runner-3", "automation", ["TC-1"], False)
        c._handed_cases = lambda: {"TC-1": "profile-x"}
        text = refused_with(lambda: c.build_rework_request("S6", "qa-runner", ["TC-1"], "recheck TC-1"))
        check_in("B-K7: an automation rework over a handed case is refused (cause 2)", "handed to the person by their recorded word: TC-1", text or "")
        c._handed_cases = lambda: {}
        check_eq("B-K7 control: with nothing handed the same rework is built",
                 c.build_rework_request("S6", "qa-runner", ["TC-1"], "recheck TC-1")["execution_kind"], "automation")
        # B-K8 (DC1-13, B-AC4): the S6 empty-cases door names stage-scope and one half per call, and no `rework` parameter it lacks
        text = refused_with(lambda: c.build_rework_request("S6", "qa-runner", [], "x")) or ""
        check_in("B-K8: S6 empty --cases: the refusal", "--cases must name at least one case of the approved scope", text)
        check_in("B-K8: ...the door names stage-scope", "`controller.py --operation stage-scope` lists them", text)
        check_in("B-K8: ...and one half per call", "S6 is reworked one half per call", text)
        check_in("B-K8: ...with the manual bound", f"(at most {MANUAL_BLOCK_CASES})", text)
        check_not_in("B-K8: ...and never `execution_kind:` as a rework parameter", "execution_kind:", text)
        # B-K9: S5 empty --cases: the same door, no S6 tail
        text = refused_with(lambda: c.build_rework_request("S5", "qa-automator", [], "x")) or ""
        check_in("B-K9: S5 empty --cases: the door names stage-scope", "`controller.py --operation stage-scope` lists them", text)
        check_not_in("B-K9: ...with no S6 tail", "one half per call", text)
        legacy = dict(c.state(), plan_contract_mode="legacy")
        with mock.patch.object(c, "state", lambda: legacy):
            text = refused_with(lambda: c.build_rework_request("S6", "qa-runner", [], "x")) or ""
        check_not_in("B-K9: a legacy-mode S6 empty --cases has no half tail either", "one half per call", text)
        # B-K10: the named list AT and BEYOND SCOPE_SHOWN (B-E9)
        rootn = temp_dir("qa-rh110-many-")
        try:
            cn = MB.real_story(rootn, ["manual-agent"] * (SCOPE_SHOWN + 1))
            every = [f"TC-{i}" for i in range(1, SCOPE_SHOWN + 2)]
            at = cn._half_membership_problems("S6", cn.state(), every[:SCOPE_SHOWN], "automation")
            beyond = cn._half_membership_problems("S6", cn.state(), every, "automation")
            check_eq("B-K10: AT the limit the whole list is named, no tail", ("and 1 more" in at[0], every[SCOPE_SHOWN - 1] in at[0]), (False, True))
            check_eq("B-K10: BEYOND it the tail says how many are left out", ("and 1 more" in beyond[0], every[SCOPE_SHOWN] in beyond[0]), (True, False))
        finally:
            cleanup(rootn)
        # B-K11 / B-E13: an unstripped id is judged as given, on the safe side (a refusal with a door), both halves
        text = refused_with(lambda: c.prepare({"stage": "S6", "role": "qa-runner", "id": "u1", "scope": [" TC-2 "], "execution_kind": "manual",
                                               "manual_case_ids": [" TC-2 "]})) or ""
        check_in("B-K11: ` TC-2 ` to prepare (manual) is cause 3", "not a manual-agent case of the approved plan:  TC-2 ", text)
        text = refused_with(lambda: c.prepare({"stage": "S6", "role": "qa-runner", "id": "u1", "scope": [" TC-1 "], "execution_kind": "automation"})) or ""
        check_in("B-K11: ` TC-1 ` to prepare (automation) is cause 3", "not an automated case of the approved plan:  TC-1 ", text)
        # B-E7: malformed members never raise; a duplicate is judged once
        got = c._half_membership_problems("S6", c.state(), ["TC-2", "TC-2", 5, "", None, ["TC-3"], "TC-1"], "automation")
        check_eq("B-E7: non-str / empty members skipped, a duplicate judged once: ONE sentence naming TC-2 once", (len(got), got[0].count("TC-2")), (1, 1))
        check_eq("B-E7: a non-list is the caller's to judge", [c._half_membership_problems("S6", c.state(), bad, "automation") for bad in ("TC-2", None, 7, {"TC-2"})], [[]] * 4)
        # B-E8: a bare id two areas hold, or an area-qualified spelling the plan does not key, is compared as written -> cause 3
        check_in("B-E8: an area-qualified spelling of an automated case is refused with the stage-scope door", "not an automated case of the approved plan: area/TC-1",
                 c._half_membership_problems("S6", c.state(), ["area/TC-1"], "automation")[0])
        # B-E10: a record already running or accepted is not re-judged (the check is on new packets only)
        check_eq("B-E10: the accepted automation record is untouched by a later re-disposition", c.state()["dispatches"]["S6-qa-runner-3"]["status"], "accepted")
        # B-K16 (B-AC5): the S4+ rule of `no_move.check_args` refuses an S6 rework with no cases
        facts = {"rework_roles": {"S6": ["qa-runner"]}, "scope": ["TC-1", "TC-2"], "causes": ["ticket_changed", "test_defect"], "rework_stages": ["S6"]}
        good = {"stage": "S6", "role": "qa-runner", "cases": ["TC-1"], "cause": "test_defect"}
        check_eq("B-K16 control: the same args with a case are accepted", check_args(good, facts)[1], "")
        none, why = check_args(dict(good, cases=[]), facts)
        check_eq("B-K16: an S6 rework with `cases: []` is refused, nothing is read as 'all'", (none, "needs at least one of the approved scope" in why), (None, True))
        none, why = check_args({k: v for k, v in good.items() if k != "cases"}, facts)
        check_eq("B-K16: ...and so is one with no `cases` key", (none, "needs at least one of the approved scope" in why), (None, True))
        # B-K6b: a MISSING plan file is an unknown for both halves, on the real reader
        (root / "work" / "test-plan.json").unlink()
        for kind, ids in (("manual", ["TC-2"]), ("automation", ["TC-1"])):
            got = c._half_membership_problems("S6", c.state(), ids, kind)
            check_eq(f"B-K6b: no work/test-plan.json: the {kind} half has ONE unknown sentence", len(got), 1)
            check_in(f"B-K6b: ...{kind}: the S6 block is the door", "S6 half membership: unreadable", got[0])
    finally:
        cleanup(root)


def main():
    rh110_s6_half_membership()
    s6_runner_rework_takes_its_half_from_its_cases()
    a_paid_round_stays_paid_when_its_own_stage_sets_it_aside()
    a_rework_is_never_the_opener_of_a_window()
    s4_rounds_survive_a_changed_case_list()
    a_person_rework_carries_the_stamp()
    the_replay_sets_aside_what_runs_after_the_rework()
    a_stage_closed_by_a_code_only_receipt_is_lowered()
    a_skipped_stage_is_never_touched()
    a_ticket_changed_rework_is_not_stamped()
    a_closed_story_is_not_stamped()
    a_round_inside_an_open_stage_is_not_stamped()
    an_approved_gate_decision_after_the_stage_goes_stale()
    a_forged_stamp_is_refused_whole()
    the_validator_stops_where_the_builder_stops()
    the_projection_forgets_the_run_a_lowered_stage_was()
    the_stamp_is_applied_once_and_never_travels_in_a_continuation()
    staling_the_critic_does_not_reset_the_repair_cap()
    a_second_person_rework_of_a_pending_stage_stamps_its_own_window()
    a_rework_without_words_is_todays_flow()
    the_person_words_mark_follows_the_words_file()
    a_stamp_with_nothing_to_set_aside_is_no_stamp()
    only_one_dispatch_runs_at_a_time_and_a_second_rework_stamps_again()
    a_designer_rework_after_gate_a_stales_the_critic_and_the_gate()
    finish("test_controller_rework_window_words")


# split: runner piece 1
if __name__ == "__main__":
    main()
