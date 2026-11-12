#!/usr/bin/env python3
"""The gate decision is built and checked by code, never typed from a reading of the source.

TP1-15045, 00:36 UTC. The person said "approve, keep all automate, accept gaps". The
orchestrator then spent three minutes reading `controller.py` to learn the shape of a
decision, got it wrong twice, and was finally refused with one sentence: "critical plan row
needs independent accepted design review". The refusal was the factory's own defect — the
gate check read the row's `required_scenarios`, which in that plan were sentences of prose,
while the same program's `_case_rows` read the case front matter. Three role dispatches
(1.4M tokens) were spent repairing a plan that was never broken.

So: `build_gate_decision` derives the whole request, `check_decision` says what would be
refused without writing anything, and `decision` runs the very same rule body.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, finish, mark_project,  # noqa: E402
                     run_script, s5_apply, temp_project, cleanup)

sys.path.insert(0, str(SCRIPTS))
import controller as CTL  # noqa: E402
import hooklib  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import StateConflict  # noqa: E402
# The REAL reader of the combined refusal (C2-1): the head and the `N) ` lines the controller writes are
# checked against it, never against a copy of its grammar.
from detector_verdict import refusal_text, split_items  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402  (accept_stage/seed_plan/bind_gate_a fixtures)

WORDS = "approve, keep all automate, accept gaps"
# The real plan's row: what a scenario column looks like when a strategist writes prose.
PROSE = ["button opens visual popup", "YAML diff opens separately from YAML panel"]


def critical_row():
    return {"id": "TS-1", "impact": "severe", "likelihood": "high", "confidence": "low",
            "risk_rationale": "bounded", "risk_source_refs": ["R-1"],
            "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1"],
            "unknowns": [], "verification_depth": "critical", "required_scenarios": PROSE,
            "test_level_rationale": "e2e", "design_review_required": True,
            "bounded_reversible": True, "disposition": "automate"}


def pin_case(root, case="TC-1", row="TS-1", version="cv_1"):
    """A pinned case version that names its plan row where the factory really reads it."""
    path = root / "state" / "case-versions" / case / f"{version}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {case}\ntask: {root.name}\nstatus: Draft\n---\n\n"
                    f"Plan row: {row}\nRequirements: R-1\n\nGiven a workflow\nWhen opened\n"
                    "Then the diff shows\n", encoding="utf-8")
    (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": case, "version": version,
         "path": f"state/case-versions/{case}/{version}.md"}]}), encoding="utf-8")


def rollcall(root, body):
    path = root / "work" / "test-cases" / "critic-findings.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def story(root, scope_of_s4=("TC-1",), designer=None, designer_files=None, rows=None,
          prepared=False, critic_extra=None, critic_scope=None, leave_item_open=False):
    """S0..S4 accepted, a critical plan row, one pinned case, an independent S4 review.

    `designer` adds keys to the designer's dispatch (`plan_rows`, `rework_of`, ...) and
    `designer_files` names the files its accepted receipt lists as evidence. `prepared` builds
    the designer's request with the controller's own `prepare`, so `plan_rows` is what the
    controller records and not what a test typed; `rows` is the plan at that moment.
    """
    mark_project(root)
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    BASE.seed_plan(root, rows or [critical_row()])
    for number in range(4):
        BASE.accept_stage(controller, root, f"S{number}")
    input_hash = "review-input"
    for role, did, complete in (("qa-case-designer", "S4-designer", False),
                                ("qa-case-critic", "S4-critic", True)):
        request = {"id": did, "stage": "S4", "role": role,
                   "scope": list(scope_of_s4), "input_hash": input_hash,
                   "budget": {}, "known_paths": {},
                   "idempotency_key": "dispatch-" + did}
        files = [did + ".txt"]
        if role == "qa-case-designer":
            if prepared:
                request = controller.prepare({"stage": "S4", "role": role, "id": did,
                                              "scope": list(scope_of_s4)})["dispatch_request"]
                input_hash = request["input_hash"]
            request.update(designer or {})
            files = designer_files or files
        else:
            if critic_scope is not None:
                request["scope"] = list(critic_scope)
            request.update(critic_extra or {})
        s5_apply(controller, request)
        refs = []
        for name in files:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            refs.append(BASE.evidence_ref(root, name))
        if complete:  # E-B11: the closing accept of S4 needs the acceptor's record over the designer's dispatch
            BASE.record_stage_acceptance(root, "S4", "S4-designer")
        controller.apply("accept", {"id": did, "status": "accepted", "stage_complete": complete,
                                    "evidence_refs": refs, "idempotency_key": "accept-" + did})
    pin_case(root)
    if not leave_item_open:
        word_for_open_items(root)
    return controller


FIXTURE_ITEM_BLOCK = "no execution profile in"     # the one `person_decides` item this fixture's rehearsal holds (s5_executor-1)


def stage_overrides_of(root):
    data = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
    return (data.get("stage_overrides") if isinstance(data, dict) else None) or []


add_override, word_for_open_items = BASE.add_override, BASE.word_for_open_items      # the fixtures' one writer lives with the shared fixtures


# --- the request is derived, and the prose is never read as a case id ---------------------

def the_decision_is_built_by_code():
    root = temp_project("qa-gate-decision-")
    try:
        controller = story(root)
        request = controller.build_gate_decision("A", WORDS)
        check_eq("the person's words are the authorization, verbatim",
                 request["authorization_source"], WORDS)
        check_eq("the scope is the approved scope, not a typed one", request["scope"], ["TC-1"])
        check_eq("the input revision is the reviewed one",
                 request["input_revision"], controller.state().get("plan_revision") or "src-1")
        review = request["design_reviews"][0]
        check_eq("the critical row gets a design review", review["plan_row"], "TS-1")
        check_eq("bound to the pinned case version", review["case_versions"], ["cv_1"])
        check_eq("naming the designer that wrote it", review["author_dispatch_id"], "S4-designer")
        check_eq("and the independent critic that read it", review["reviewer_dispatch_id"], "S4-critic")
        check_eq("the review says the designer was credited by its case scope",
                 review["author_basis"], "scope")
        check_not_in("no sentence from required_scenarios reaches the request",
                     PROSE[0], json.dumps(request))
        check_eq("nothing the controller builds is refused by the controller",
                 controller.check_decision(request), [])
        before = controller.state()["revision"]
        check_eq("checking a decision writes nothing", Controller(root).state()["revision"], before)
        controller.apply("decision", dict(request))
        check_eq("and recording it opens S5", controller.next_action()["stage"], "S5")
    finally:
        cleanup(root)


def an_empty_historical_scope_is_not_a_refusal():
    """Every S4 dispatch before 0.7.5 recorded an empty scope. The reviewer's own roll-call
    is what says which cases it read, and on the real run it said all six."""
    root = temp_project("qa-gate-rollcall-")
    try:
        controller = story(root, scope_of_s4=())
        rollcall(root, "## Roll-call\n\n| Plan row | Case | Reviewed |\n|---|---|---|\n"
                       "| TS-1 | TC-1 | yes |\n")
        request = controller.build_gate_decision("A", WORDS)
        check_eq("a review is still bound to the two S4 dispatches",
                 (request["design_reviews"][0]["author_dispatch_id"],
                  request["design_reviews"][0]["reviewer_dispatch_id"]),
                 ("S4-designer", "S4-critic"))
        check_eq("the designer is credited by the roll-call, and the review says so",
                 request["design_reviews"][0]["author_basis"], "rollcall")
        check_eq("and the decision records", controller.check_decision(request), [])
    finally:
        cleanup(root)


def an_unreviewed_case_is_still_a_refusal():
    root = temp_project("qa-gate-unreviewed-")
    try:
        controller = story(root, scope_of_s4=())
        rollcall(root, "## Roll-call\n\n| Plan row | Case | Status |\n|---|---|---|\n"
                       "| TS-1 | TC-1 | found (not semantically reviewed) |\n")
        request = controller.build_gate_decision("A", WORDS)
        problems = controller.check_decision(request)
        check("an empty scope with nothing reviewed is refused", bool(problems))
        check_in("and the refusal names the row and what is missing", "plan row TS-1", problems)
        check_in("not one sentence for the whole plan", "does not cover TC-1", problems)
    finally:
        cleanup(root)


# --- B-224: the S4 designer's receipt says what it was sent to design ----------------------
# cmp1, TP1-13797: the designer opened S4 before any case id existed, its receipt carried
# `scope: []`, and gate A recorded TS-6/7/9/11 with author "" (recorded only because those rows
# were `manual-human`; a B-216 switch to `automate` would have refused the decision).

COVERS = Controller._cover_basis
CASE = "TP1-13797_TC_011"


def dispatch(role="qa-case-designer", **extra):
    return {"id": "D", "stage": "S4", "role": role, "status": "accepted", "scope": [], **extra}


def evidence_of(*paths):
    return [{"path": path, "sha256": "0" * 64} for path in paths]


def basis(dispatch_, cases, row=None, reviewed=()):
    return COVERS(dispatch_, set(cases), set(reviewed), row)


def a_designer_is_credited_by_the_plan_rows_it_was_sent():
    root = temp_project("qa-gate-plan-rows-")
    try:
        # At dispatch time TS-1 is a manual-human row; a B-216 switch makes it `automate` later.
        controller = story(root, scope_of_s4=(), critic_scope=("TC-1",), prepared=True,
                           rows=[dict(critical_row(), disposition="manual-human")])
        opener = controller.state()["dispatches"]["S4-designer"]
        check_eq("prepare recorded every plan row beside an empty scope",
                 (opener["scope"], opener.get("plan_rows")), ([], ["TS-1"]))
        BASE.seed_plan(root, [critical_row(),
                              dict(critical_row(), id="TS-2", required_scenarios=["TC-2"])])
        pin_case(root)
        request = controller.build_gate_decision("A", WORDS)
        reviews = {item["plan_row"]: item for item in request["design_reviews"]}
        check_eq("the designer is the author although no roll-call is on disk",
                 reviews["TS-1"]["author_dispatch_id"], "S4-designer")
        check_eq("credited by the rows it was sent", reviews["TS-1"]["author_basis"], "plan_rows")
        check_eq("a row that entered the plan after the dispatch is not credited to it",
                 (reviews["TS-2"]["author_dispatch_id"], reviews["TS-2"]["author_basis"]), ("", "none"))
        problems = controller.check_decision(request)
        check_in("so that row is refused, naming its cases", "plan row TS-2", problems)
        check_not_in("and the credited row is not", "plan row TS-1", problems)

        # The same story with the new row out of the plan records, and keeps the basis.
        BASE.seed_plan(root, [critical_row()])
        pin_case(root)
        request = controller.build_gate_decision("A", WORDS)
        check_eq("the rehearsal passes the switched row", controller.check_decision(request), [])
        controller.apply("decision", dict(request))
        recorded = json.dumps(json.loads((root / "pipeline.json").read_text(encoding="utf-8")))
        check_in("the recorded review keeps how its author was credited",
                 '"author_basis": "plan_rows"', recorded)
    finally:
        cleanup(root)


def a_legacy_opener_is_credited_only_by_its_own_evidence():
    """Every receipt made before B-224 has no `plan_rows` key (E-1)."""
    root = temp_project("qa-gate-legacy-")
    try:
        controller = story(root, scope_of_s4=(), critic_scope=("TC-1",),
                           designer_files=["work/test-cases/cases/TC-1/cv_1.md"])
        request = controller.build_gate_decision("A", WORDS)
        review = request["design_reviews"][0]
        check_eq("the opener that listed the case's file is the author",
                 (review["author_dispatch_id"], review["author_basis"]),
                 ("S4-designer", "legacy_evidence"))
        check_eq("and the decision records", controller.check_decision(request), [])
    finally:
        cleanup(root)

    root = temp_project("qa-gate-legacy-none-")
    try:
        controller = story(root, scope_of_s4=(), critic_scope=("TC-1",))
        review = controller.build_gate_decision("A", WORDS)["design_reviews"][0]
        check_eq("an opener with no evidence of the case is not credited",
                 (review["author_dispatch_id"], review["author_basis"]), ("", "none"))
        problems = controller.check_decision(controller.build_gate_decision("A", WORDS))
        check_in("the refusal says no designer is recorded as having designed the case",
                 "no accepted S4 qa-case-designer dispatch is recorded as having designed TC-1",
                 problems)
        check_in("names the rework door", "--operation rework --stage S4 --role qa-case-designer "
                 "--cases TC-1 --reason", problems)
        check_in("and the person's word", 'waiver.py --task ' + root.name + ' --stage S4 --block '
                 '"design review"', problems)
        check_not_in("instead of the two sentences it replaces", "is not an S4 qa-case-designer",
                     problems)
        check_not_in("for that case only", "the designer dispatch does not cover", problems)
        check_not_in("and nothing beside it contradicts the one sentence (FR-10)", "must be accepted",
                     problems)
        check_not_in("neither about the input hash", "input_hash", problems)
        # Positive control: a non-empty wrong author keeps today's text, noise included.
        request = controller.build_gate_decision("A", WORDS)
        request["design_reviews"][0]["author_dispatch_id"] = "ghost"
        wrong = controller.check_decision(request)
        check_in("a named author that is not a designer still gets today's sentence",
                 "author 'ghost' is not an S4 qa-case-designer", wrong)
        check_in("and the acceptance sentence", "must be accepted", wrong)
        check_in("and the input hash sentence", "input_hash", wrong)
    finally:
        cleanup(root)


def a_designer_with_a_present_but_empty_plan_rows_credits_nothing():
    root = temp_project("qa-gate-empty-rows-")
    try:
        controller = story(root, scope_of_s4=(), critic_scope=("TC-1",), designer={"plan_rows": []},
                           designer_files=["work/test-cases/cases/TC-1/cv_1.md"])
        review = controller.build_gate_decision("A", WORDS)["design_reviews"][0]
        check_eq("a present `[]` is zero rows: the evidence is not consulted",
                 (review["author_dispatch_id"], review["author_basis"]), ("", "none"))
    finally:
        cleanup(root)


def a_critics_roll_call_never_credits_a_designer_that_spoke_in_rows():
    """The critic's roll-call is the fallback for receipts made before `plan_rows`; a receipt that
    carries the key has said what it was sent to design, and `[]` or another row credits nothing."""
    for rows in ([], ["TS-9"]):
        root = temp_project("qa-gate-rows-rollcall-")
        try:
            controller = story(root, scope_of_s4=(), critic_scope=("TC-1",), designer={"plan_rows": rows})
            rollcall(root, "## Roll-call\n\n| Plan row | Case | Reviewed |\n|---|---|---|\n"
                           "| TS-1 | TC-1 | yes |\n")
            request = controller.build_gate_decision("A", WORDS)
            review = request["design_reviews"][0]
            check_eq(f"plan_rows={rows}: no author although the roll-call names the case",
                     (review["author_dispatch_id"], review["author_basis"]), ("", "none"))
            problems = controller.check_decision(request)
            check_in(f"plan_rows={rows}: the gate refuses with the one sentence",
                     "no accepted S4 qa-case-designer dispatch is recorded as having designed TC-1",
                     problems)
        finally:
            cleanup(root)
    for key_less in ({}, {"role": "qa-case-critic"}):
        d = dispatch(**key_less)
        check_eq(f"{key_less or 'a designer without the key'}: the roll-call credits it as before",
                 basis(d, {CASE}, "TS-11", reviewed={CASE}), "rollcall")
    check_eq("plan_rows=[] with the case in the roll-call is not covered",
             basis(dispatch(plan_rows=[]), {CASE}, "TS-11", reviewed={CASE}), "")
    check_eq("nor plan_rows=['TS-9'] for row TS-11",
             basis(dispatch(plan_rows=["TS-9"]), {CASE}, "TS-11", reviewed={CASE}), "")
    check_eq("a critic holding the key is still credited by the roll-call",
             basis(dispatch("qa-case-critic", plan_rows=[]), {CASE}, "TS-11", reviewed={CASE}), "rollcall")


def a_designer_with_another_input_hash_is_still_refused():
    """Clause 2 decides who covers; `:1157` still decides whether they worked on this input."""
    root = temp_project("qa-gate-rows-hash-")
    try:
        controller = story(root, scope_of_s4=(), critic_scope=("TC-1",),
                           designer={"plan_rows": ["TS-1"], "input_hash": "another-input"})
        request = controller.build_gate_decision("A", WORDS)
        check_eq("the designer is credited by its row",
                 request["design_reviews"][0]["author_basis"], "plan_rows")
        check_in("and refused for its input hash", "did not work from the review's input_hash",
                 controller.check_decision(request))
    finally:
        cleanup(root)


def a_critic_is_never_credited_by_rows_or_evidence():
    root = temp_project("qa-gate-critic-rows-")
    try:
        controller = story(root, scope_of_s4=(), critic_scope=(), critic_extra={
            "plan_rows": ["TS-1"]}, designer={"plan_rows": ["TS-1"]})
        review = controller.build_gate_decision("A", WORDS)["design_reviews"][0]
        check_eq("a critic holding the row with an empty scope is not a reviewer",
                 review["reviewer_dispatch_id"], "")
        check_eq("while the designer holding it is the author",
                 review["author_dispatch_id"], "S4-designer")
    finally:
        cleanup(root)
    critic = dispatch("qa-case-critic", plan_rows=["TS-6"])
    check_eq("(input 1) a critic with plan_rows and no scope or roll-call", basis(critic, {"C-1"}, "TS-6"), "")
    check_eq("nor by the evidence it lists", basis(
        dispatch("qa-case-critic", evidence_refs=evidence_of("work/cases/C-1/cv.md")), {"C-1"}, "TS-6"), "")
    check_eq("a critic is still credited by its scope",
             basis(dispatch("qa-case-critic", scope=["C-1"]), {"C-1"}, "TS-6"), "scope")
    check_eq("and by the roll-call", basis(critic, {"C-1"}, "TS-6", reviewed={"C-1"}), "rollcall")
    dispatches = [dispatch("qa-case-critic", id="K", plan_rows=["TS-6"]),
                  dispatch("qa-case-designer", id="A", plan_rows=["TS-6"])]
    check_eq("the pick never returns a dispatch of another role",
             Controller._last_covering(dispatches, "qa-case-designer", {"C-1"}, set(), "TS-6")["id"], "A")
    check_eq("and the critic pick finds none", Controller._last_covering(
        dispatches, "qa-case-critic", {"C-1"}, set(), "TS-6"), None)


def plan_rows_membership_is_exact():
    opener = dispatch(plan_rows=["TS-6"])
    check_eq("an exact element covers the row", basis(opener, {"C-1"}, "TS-6"), "plan_rows")
    check_eq("(input 2) TS-60 does not cover TS-6", basis(dispatch(plan_rows=["TS-60"]), {"C-1"}, "TS-6"), "")
    check_eq("(input 3) a string is never iterated: TS-10 does not hold TS-1",
             basis(dispatch(plan_rows="TS-10"), {"C-1"}, "TS-1"), "")
    check_eq("not even when the string IS the row", basis(dispatch(plan_rows="TS-1"), {"C-1"}, "TS-1"), "")
    check_eq("a dict is not a list", basis(dispatch(plan_rows={"TS-1": 1}), {"C-1"}, "TS-1"), "")
    check_eq("(input 4) `*` means nothing", basis(dispatch(plan_rows=["*"]), {"C-1"}, "TS-6"), "")
    check_eq("an empty row is not everything", basis(dispatch(plan_rows=[""]), {"C-1"}, ""), "")
    check_eq("no row given: the clause is off", basis(opener, {"C-1"}, None), "")
    check_eq("a row absent from the list is not credited", basis(opener, {"C-1"}, "TS-7"), "")
    check_eq("the scope clause still goes first", basis(dispatch(scope=["C-1"], plan_rows=[]), {"C-1"}, "TS-6"), "scope")
    check_eq("no cases, no question: unchanged", basis(dispatch(), set(), None), "scope")


def legacy_evidence_is_matched_whole_and_only_for_an_accepted_opener():
    path = f"work/test-cases/cases/{CASE}/cv_5b365b319626a97856bb.md"
    legacy = dispatch(evidence_refs=evidence_of(path))
    check_eq("cmp1: the case id is a whole path part", basis(legacy, {CASE}), "legacy_evidence")
    check_eq("or a file stem", basis(dispatch(evidence_refs=evidence_of(f"work/{CASE}.md")), {CASE}),
             "legacy_evidence")
    check_eq("(input 5) a longer id is not a substring match", basis(legacy, {CASE[:-1]}), "")
    check_eq("a case the evidence does not list makes the whole set uncovered",
             basis(legacy, {CASE, "TP1-13797_TC_012"}), "")
    check_eq("(input 6) a superseded opener is not an author",
             basis(dispatch(status="superseded", evidence_refs=evidence_of(path)), {CASE}), "")
    check_eq("nor a running one", basis(dispatch(status="running", evidence_refs=evidence_of(path)), {CASE}), "")
    check_eq("(input 7) nor a rework round",
             basis(dispatch(rework_of="S4-qa-case-designer-1", evidence_refs=evidence_of(path)), {CASE}), "")
    check_eq("(input 8) a present `plan_rows: []` never reads the evidence",
             basis(dispatch(plan_rows=[], evidence_refs=evidence_of(path)), {CASE}), "")
    check_eq("nor a present `plan_rows: None`",
             basis(dispatch(plan_rows=None, evidence_refs=evidence_of(path)), {CASE}), "")
    check_eq("an opener with a scope of other cases is not credited by evidence",
             basis(dispatch(scope=["OTHER"], evidence_refs=evidence_of(path)), {CASE}), "")
    for junk in (None, "work/x", {"path": path}, 7, [None, 5, "x", {"path": None}, {"path": 5}, {}]):
        try:
            got = basis(dispatch(evidence_refs=junk), {CASE})
        except Exception as exc:  # the point of the check is that nothing is raised
            got = f"raised {type(exc).__name__}"
        check_eq(f"(input 9) malformed evidence_refs {str(junk)[:30]!r} is skipped, not raised", got, "")
    check_eq("a malformed entry beside a good one does not hide the good one",
             basis(dispatch(evidence_refs=[None, {"path": None}] + evidence_of(path)), {CASE}),
             "legacy_evidence")
    check_eq("the roll-call fallback stays last", basis(dispatch(), {CASE}, reviewed={CASE}), "rollcall")


def the_second_designer_round_keeps_the_openers_rows():
    """E-7: the rework is credited by its named cases, the opener by rows for the rest."""
    opener = dispatch(id="S4-qa-case-designer-1", plan_rows=["TS-1", "TS-2"])
    rework = dispatch(id="S4-qa-case-designer-2", scope=["TC-2"], rework_of="S4-qa-case-designer-1")
    pick = Controller._last_covering
    check_eq("a row whose cases are all in the rework's scope is credited to the rework",
             pick([opener, rework], "qa-case-designer", {"TC-2"}, set(), "TS-2")["id"],
             "S4-qa-case-designer-2")
    check_eq("a row the rework did not name stays with the opener",
             pick([opener, rework], "qa-case-designer", {"TC-1"}, set(), "TS-1")["id"],
             "S4-qa-case-designer-1")
    check_eq("a row split across rounds is credited to the opener",
             pick([opener, rework], "qa-case-designer", {"TC-1", "TC-2"}, set(), "TS-2")["id"],
             "S4-qa-case-designer-1")


def prepare_records_the_plan_rows_for_the_designer_only():
    root = temp_project("qa-gate-prepare-rows-")
    try:
        controller = story(root)
        plan = root / "work" / "test-plan.json"

        def ask(stage="S4", role="qa-case-designer", **extra):
            return Controller(root).prepare(dict({"stage": stage, "role": role}, **extra))["dispatch_request"]

        plan.write_text(json.dumps({"rows": [
            {"id": "TS-2", "disposition": "automate"}, {"id": "TS-1", "disposition": "skip"},
            {"disposition": "automate"}, {"id": ""}, "not a row", {"id": "TS-1"},
            {"id": "TS-3", "disposition": "manual-human", "design_review_required": False}]}),
            encoding="utf-8")
        request = ask()
        check_eq("every row id, sorted and unique, whatever its disposition or flag",
                 request.get("plan_rows"), ["TS-1", "TS-2", "TS-3"])
        check_eq("the scope is the one it always was", request["scope"], controller.state()["scope"])
        check_eq("a caller's own plan_rows is never read",
                 ask(plan_rows=["TS-99"]).get("plan_rows"), ["TS-1", "TS-2", "TS-3"])
        check_eq("an explicit empty scope stays empty beside the rows",
                 (ask(scope=[])["scope"], ask(scope=[])["plan_rows"]), ([], ["TS-1", "TS-2", "TS-3"]))
        for stage, role in (("S3", "qa-strategist"), ("S4", "qa-case-critic"), ("S3", "qa-case-designer"),
                            ("S1", "qa-scout")):
            check_not_in(f"{stage} {role} gets no plan_rows key", "plan_rows", json.dumps(ask(stage, role)))

        plan.write_text(json.dumps({"rows": []}), encoding="utf-8")
        check_eq("a plan with no rows records `[]`, not an absent key", ask().get("plan_rows"), [])
        plan.write_text(json.dumps([{"id": "TS-7"}]), encoding="utf-8")
        check_eq("a plan that is a bare list of rows is read too", ask().get("plan_rows"), ["TS-7"])
        for label, text in (("a corrupt plan", "{not json"), ("rows that are not a list", '{"rows": "TS-1"}')):
            plan.write_text(text, encoding="utf-8")
            check_not_in(f"{label}: the key is omitted, never `[]`", "plan_rows", json.dumps(ask()))
        plan.unlink()
        check_not_in("no plan file: the key is omitted, never `[]`", "plan_rows", json.dumps(ask()))
    finally:
        cleanup(root)


# --- one rule body: the rehearsal cannot disagree with the recording ----------------------

def recorded_refusal(controller, request):
    """(exception class, text) of recording `request`, or (None, "") when it was recorded."""
    try:
        controller.apply("decision", dict(request))
    except (StateConflict, ValueError) as exc:
        return type(exc), str(exc)
    return None, ""


def check_and_record_are_the_same_rules():
    root = temp_project("qa-gate-same-rules-")
    try:
        controller = story(root)
        # ONE defect: the sentence is the rehearsal's, word for word, with no head and no number.
        broken = dict(controller.build_gate_decision("A", WORDS), plan_semantic_hash="not-the-plan")
        problems = controller.check_decision(broken)
        check_eq("the rehearsal sees one stale semantic hash", len(problems), 1)
        cls, raised = recorded_refusal(controller, broken)
        check_eq("and recording it raises the very same sentence", raised, problems[0])
        check_eq("in the story's class, not the caller's", cls, StateConflict)
        check_in("which names what was expected", "must bind server-derived semantic plan hash", raised)
        check_eq("the refused decision left no receipt", controller.state()["decisions"], {})
        # A defect and the design review that reads it are two problems of one request.
        stale = dict(controller.build_gate_decision("A", WORDS), input_revision="plan-elsewhere")
        problems = controller.check_decision(stale)
        check_in("the rehearsal sees the stale input revision", "must bind the current reviewed", "\n".join(problems))
        _, raised = recorded_refusal(controller, stale)
        check_eq("and recording it names each of them", split_items(raised), problems)
    finally:
        cleanup(root)


def several_problems_are_reported_at_once():
    root = temp_project("qa-gate-many-")
    try:
        controller = story(root)
        broken = dict(controller.build_gate_decision("A", WORDS),
                      input_revision="plan-elsewhere", plan_content_hash="not-the-plan",
                      design_reviews=[])
        problems = controller.check_decision(broken)
        check("a rehearsal reports every problem, not the first one", len(problems) >= 3,
              str(problems))
        check_in("including the missing design review", "requires an independent design review",
                 problems)
        check_in("and it names the operation that builds one", "--operation gate-decision", problems)
        # K1: the recording refuses with the same list in ONE text, not the first problem of it.
        cls, raised = recorded_refusal(controller, broken)
        check_eq("recording it raises one refusal whose head counts them",
                 raised.splitlines()[0], f"{len(problems)} problems - the request is refused whole, every one is listed:")
        check_eq("and lists exactly the rehearsal's problems, in order", split_items(raised), problems)
        check_eq("in the class of the first problem", cls, StateConflict)
        # The CLI prints the same text as `{"error": ...}` on stderr, newlines escaped: the reader
        # takes the transport off first, and still finds every problem.
        request_file = root / "broken-decision.json"
        request_file.write_text(json.dumps(dict(broken, idempotency_key="cli-broken")), encoding="utf-8")
        run = subprocess.run([sys.executable, "-B", str(SCRIPTS / "controller.py"), "--task-root", str(root),
                              "--operation", "decision", "--input", str(request_file)],
                             capture_output=True, text=True, timeout=120)
        check_eq("the CLI refuses with exit 2", run.returncode, 2)
        check_eq("and its stderr line, unwrapped, lists the same problems",
                 split_items(refusal_text(run.stderr.strip())), problems)
        check_eq("while the controller's bare text is its own transport-free form (identity)",
                 refusal_text(raised), raised)
    finally:
        cleanup(root)


def a_collected_refusal_has_the_class_of_its_first_problem():
    """F-4: no caller branches on the class, so a mixed list is raised as the FIRST problem's."""
    root = temp_project("qa-gate-mixed-")
    try:
        controller = story(root)
        # Gate B at gate A's moment: the story is not ready (state), and the receipt is malformed
        # (request) - one of each, the state problem first.
        base = controller.build_gate_decision("B", WORDS)
        request = dict(base, selected_drafts=None)
        problems = controller.check_decision(request)
        cls, raised = recorded_refusal(controller, request)
        check_in("the state problem comes first", "gate before prerequisite completion", problems[0])
        check_in("and the malformed receipt after it", "selected_drafts", problems[-1])
        check_eq("the refusal is the first problem's class (the story's)", cls, StateConflict)
        check_eq("with every problem listed", split_items(raised), problems)
    finally:
        cleanup(root)


def identical_problems_are_merged_into_one_line():
    """`_raise_all` folds equal messages as `(×K)`; the head counts lines, not raw problems."""
    from controller import Controller as C
    for label, problems, expected in (
            ("none: nothing is raised", [], None),
            ("one: the sentence, unchanged", [(StateConflict, "alpha")], (StateConflict, "alpha")),
            ("two equal ones: one line with the count, no head",
             [(ValueError, "alpha"), (ValueError, "alpha")], (ValueError, "alpha (×2)")),
            ("a multi-line message keeps one item",
             [(StateConflict, "a\n2) looks like an item"), (ValueError, "b")], None)):
        try:
            C._raise_all(problems)
            got = None
        except (StateConflict, ValueError) as exc:
            got = (type(exc), str(exc))
        if expected is not None or not problems:
            check_eq(label, got, expected)
        else:
            check_eq(label + ": the reader counts two items", len(split_items(got[1])), 2)
    try:
        C._raise_all([(ValueError, "x"), (StateConflict, "y"), (ValueError, "x")])
    except (StateConflict, ValueError) as exc:
        check_eq("equal messages merge wherever they stand; the head counts the lines",
                 split_items(str(exc)), ["x (×2)", "y"])


def an_unverifiable_row_owes_no_design_review():
    """A row the owner declared has no observable cannot own a case, so it cannot owe a review.

    TP1-13797, 26.09: TS-19 carried the register's own contradiction (AC7's UI half is not in
    this story's code), the strategist wrote `required_scenarios: ["pending Gate-A scope decision"]`
    and `design_review_required: true`, and this check went looking for a pinned case version of
    that sentence. The gate the person had just approved would not record, and the driver asked
    gate A again in a loop. `skip` and `manual-human` were already exempt; `unverifiable` was not.
    """
    root = temp_project("qa-gate-unverifiable-")
    try:
        controller = story(root)
        row = dict(critical_row(), id="TS-19", disposition="unverifiable",
                   required_scenarios=["pending Gate-A scope decision"])
        BASE.seed_plan(root, [critical_row(), row])
        decision = controller.build_gate_decision("A", WORDS)
        problems = controller.check_decision(decision)
        check_not_in("an unverifiable row is not asked for a design review", "TS-19", str(problems))
    finally:
        cleanup(root)


def the_builder_names_its_allowed_values():
    root = temp_project("qa-gate-args-")
    try:
        controller = story(root)
        for bad, needle in (("C", "gate must be one of: A, B"), ("", "gate must be one of: A, B")):
            message = ""
            try:
                controller.build_gate_decision(bad, WORDS)
            except ValueError as exc:
                message = str(exc)
            check_in(f"gate {bad!r} is refused by naming the allowed values", needle, message)
        message = ""
        try:
            controller.build_gate_decision("A", "   ")
        except ValueError as exc:
            message = str(exc)
        check_in("a decision cannot be recorded without the person's words",
                 "authorization_source", message)
        gate_b = controller.build_gate_decision("B", "deliver with the two bugs")
        check_eq("gate B carries the drafts field the check requires",
                 gate_b.get("selected_drafts"), [])
    finally:
        cleanup(root)


# --- 0.7.7 review, D-F3: gate B's chosen drafts come in by flag ---------------------------

def gate_b_takes_the_chosen_drafts_by_flag():
    """s8.md names `--drafts`; adding the refs to a printed request afterwards was
    hand-building the JSON s0.md forbids."""
    root = temp_project("qa-gate-b-drafts-")
    try:
        controller = story(root)
        request = controller.build_gate_decision(
            "B", "file the two", ["work/bug-drafts/BD-1.md", " work/bug-drafts/BD-2.md ", ""])
        check_eq("the person's chosen drafts are recorded, trimmed, without the blanks",
                 request["selected_drafts"],
                 ["work/bug-drafts/BD-1.md", "work/bug-drafts/BD-2.md"])
        check_eq("and no drafts is still a valid gate B",
                 controller.build_gate_decision("B", "nothing to file", [])["selected_drafts"], [])
    finally:
        cleanup(root)


# --- 0.7.7 review, B-F6: the design review's verdict is the critic's, not a constant -------

def the_design_review_verdict_is_the_critics_own():
    """`_build_design_reviews` wrote `verdict: "accepted"` whatever the roll-call said, so a
    `reject` reached the person as an accepted independent review."""
    root = temp_project("qa-gate-verdict-")
    try:
        controller = story(root)
        check_eq("with no findings file at all the review stays accepted (0.7.4 stories)",
                 controller.build_gate_decision("A", WORDS)["design_reviews"][0]["verdict"],
                 "accepted")
        rollcall(root, "Verdict: `approve_with_concerns`\n\n## Roll-call\n\n"
                       "| Plan row | Case | Reviewed |\n|---|---|---|\n| TS-1 | TC-1 | yes |\n")
        check_eq("an approving verdict is an accepted review",
                 controller.build_gate_decision("A", WORDS)["design_reviews"][0]["verdict"],
                 "accepted")
        rollcall(root, "Verdict: `reject`\n\n## Roll-call\n\n"
                       "| Plan row | Case | Reviewed |\n|---|---|---|\n| TS-1 | TC-1 | yes |\n")
        request = controller.build_gate_decision("A", WORDS)
        check_eq("a reject is carried, not overwritten",
                 request["design_reviews"][0]["verdict"], "reject")
        problems = controller.check_decision(request)
        check("and the gate refuses the decision built on it", bool(problems))
        check_in("naming the critic's own word", "'reject'", problems)
        check_in("with the round that repairs it", "--operation rework", problems)
        check_in("and the person's word that passes it", "waiver.py", problems)
    finally:
        cleanup(root)


# --- RN1-20 (t-1697 D1-D): the review is void when the critic did not see the designer's last version -----

def second_designer_after_critic(controller, root):
    """A second S4 designer dispatch over the same case, accepted AFTER the critic: the rework the critic never saw."""
    request = {"id": "S4-designer-2", "stage": "S4", "role": "qa-case-designer", "scope": ["TC-1"],
               "input_hash": "review-input", "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-S4-designer-2"}
    s5_apply(controller, request)
    controller.apply("accept", {"id": "S4-designer-2", "status": "accepted", "stage_complete": False,
                                "evidence_refs": [BASE.evidence_ref(root, "S4-designer-2.txt")],
                                "idempotency_key": "accept-S4-designer-2"})


def rn1_20_k_d1_designer_after_critic_voids_the_review():
    root = temp_project("qa-gate-order-")
    try:
        controller = story(root)
        order = controller.accept_order()
        check("K-D1: the accept order puts the designer before the critic in the ordinary story",
              order["S4-designer"] < order["S4-critic"])
        check_eq("K-D1 reverse order: no order refusal", [p for p in controller.check_decision(
            controller.build_gate_decision("A", WORDS)) if "accepted after" in p], [])
        second_designer_after_critic(controller, root)
        order = controller.accept_order()
        check("K-D1: the second designer is accepted after the critic", order["S4-designer-2"] > order["S4-critic"])
        request = controller.build_gate_decision("A", WORDS)
        check_eq("K-D1: the review names the later designer", request["design_reviews"][0]["author_dispatch_id"],
                 "S4-designer-2")
        problems = [p for p in controller.check_decision(request) if "accepted after" in p]
        check_eq("K-D1: one refusal for the row", len(problems), 1)
        check_in("K-D1: it names both dispatches", "S4-designer-2 was accepted after the case critic's S4-critic",
                 problems[0])
        check_in("K-D1: and what is wrong", "the critic has not reviewed the cases as they stand", problems[0])
        check("K-D1: the pins alone cannot see it (the old comparison holds)", not [
            p for p in controller.check_decision(request) if "case_versions" in p])
        check("K-D1 pure helper: no author is no staleness (E-D2)", not Controller.review_is_stale(
            {"author_dispatch_id": "", "reviewer_dispatch_id": "S4-critic"}, order))
        check("K-D1 pure helper: an unknown position is no staleness (E-D1/E-D3)", not Controller.review_is_stale(
            request["design_reviews"][0], {}))
        # (re-pinned, Q1 t-1752: the order is read through `store.read()`, so the stand-in store has a `read`, not a `log` path)
        def _raises(exc):
            def read():
                raise exc
            return read
        check_eq("K-D1: an unreadable events log gives {} (E-D3)", Controller.accept_order(
            type("C", (), {"store": type("S", (), {"read": staticmethod(_raises(OSError("gone")))})})()), {})
        check_eq("K-D1: a store with no log at all gives {} (E-D3)", Controller.accept_order(
            type("C", (), {"store": type("S", (), {"read": staticmethod(lambda: [])})})()), {})
        # Q1 (t-1752) E-D3: a CORRUPT tail of the real log -> {} (an unknown order never refuses and never passes), never a partial order
        log = controller.store.log
        before = log.read_bytes()
        try:
            log.write_bytes(before + b"{not json\n")
            check_eq("K-D1 E-D3: a corrupt line at the tail of the real events log gives {}", controller.accept_order(), {})
            log.write_bytes(before + b'{"type": "accept"')
            check_eq("K-D1 E-D3: an incomplete final event gives {}", controller.accept_order(), {})
        finally:
            log.write_bytes(before)
        check("K-D1 E-D3: ... and the restored log reads again", "S4-critic" in controller.accept_order())
    finally:
        cleanup(root)


def rn1_20_k_d3_the_packet_line_for_a_stale_review():
    import gate_brief
    root = temp_project("qa-gate-stale-")
    try:
        controller = story(root)
        rows = gate_brief.accepted_review_summary(root)
        check_eq("K-D3: an ordinary story has no stale mark", [r for r in rows if r.get("stale")], [])
        second_designer_after_critic(controller, root)
        rows = gate_brief.accepted_review_summary(root)
        check_eq("K-D3: the stale row is marked", [(r["plan_row"], r.get("stale")) for r in rows], [("TS-1", True)])
        line = "- after the last edit of its cases the case critic has not reviewed them"
        check_in("K-D3: the packet says the critic has not reviewed the edited cases", line,
                 "\n".join(gate_brief._head_lines({"task": "T", "gate_reviews": rows})))
        check_not_in("K-D3 control: a fresh review prints no such line", line, "\n".join(
            gate_brief._head_lines({"task": "T", "gate_reviews": [{"plan_row": "TS-1", "verdict": "accepted"}]})))
    finally:
        cleanup(root)


def rn1_20_k_d4_q2_a_row_patched_by_an_answer_after_the_critic_is_no_refusal():
    """R6 carry, recon q1 (t-1697 D4): `apply_recorded_answers` patches a row AFTER the critic's accept; the gate
    decision built and checked next has no `why` for it, so the answer's own code path (A2/A6) closes R6 and no
    `_late_record` change is needed (q2). The pin keeps it so; a future `why` here is the q3 finding."""
    import planning_contract as PC
    import question_register as QR
    root = temp_project("qa-gate-late-answer-")
    try:
        row = critical_row()
        row["question_refs"] = ["Q1"]
        row["if_answered"] = {"Q1": {"a": {"level": "api", "test_level_rationale": "api now"}, "*": {}, "not_needed": {}}}
        controller = story(root, rows=[row])
        (root / "work" / "requirements-readiness.json").write_text(json.dumps({"verdict": "blocked", "open_questions": [
            {"id": "Q1", "question": "Which behaviour?", "severity": "major",
             "readings": [{"reading": "r0", "from": "description", "if_chosen": "x"},
                          {"reading": "r1", "from": "description", "if_chosen": "y"}]}]}), encoding="utf-8")
        shown = {q["id"]: q for q in QR.load(root)["questions"]}["Q1"]["row_hash"]
        QR.record(root, "Q1", "answered", "Q1: a", "S3 stop", "person", shown, reading="a")
        order = controller.accept_order()
        check("K-D4: the critic's accept is already in the log", "S4-critic" in order)
        applied = PC.apply_recorded_answers(root, "gate A", "driver")
        check_eq("K-D4: the answer patched the row after the critic's accept", applied["applied"][0]["rows"], ["TS-1"])
        plan = json.loads((root / "work" / "test-plan.json").read_text(encoding="utf-8"))
        check_eq("K-D4: the plan row changed", [r.get("level") for r in plan["rows"]], ["api"])
        check_eq("K-D4 q2: and the gate decision built from it has no refusal",
                 controller.check_decision(controller.build_gate_decision("A", WORDS)), [])
    finally:
        cleanup(root)


# --- 0.7.7 review, B-F15: what the PERSON changed at gate A is marked by code --------------

def gate_a_overrides_are_marked_by_code():
    """The retro counts human overrides. Nothing a role writes is evidence of what the
    person changed, so the controller derives it from the plan the role left behind."""
    root = temp_project("qa-gate-overrides-")
    try:
        controller = story(root)
        rows = [dict(critical_row()), dict(critical_row(), id="TS-2", required_scenarios=["TC-2"])]
        BASE.seed_plan(root, rows)
        pin_case(root)  # seed_plan rewrites the links; TC-1 still names TS-1
        # The baseline: the plan exactly as S4 left it.
        controller._capture_plan_baseline(controller.state())

        document = json.loads((root / "work/test-plan.json").read_text(encoding="utf-8"))
        document["rows"][1]["disposition"] = "manual-agent"
        (root / "work/test-plan.json").write_text(json.dumps(document), encoding="utf-8")
        controller.apply("revise_plan", {
            "scope": ["TC-1"], "plan_revision": "plan-2",
            "reason": "TS-2 by hand this time, and drop nothing else",
            "idempotency_key": "revise-1"})

        after = json.loads((root / "work/test-plan.json").read_text(encoding="utf-8"))["rows"]
        moved = next(row for row in after if row["id"] == "TS-2")
        untouched = next(row for row in after if row["id"] == "TS-1")
        check("the row whose disposition the person moved is marked",
              moved.get("overridden") is True)
        check_eq("by the only place a person edits a plan", moved.get("overridden_by"), "gate A")
        check_in("carrying their own words", "TS-2 by hand this time",
                 moved.get("overridden_words", ""))
        check_in("and what actually changed", "automate -> manual-agent",
                 moved.get("overridden_change", ""))
        check("a row nobody touched carries no mark", "overridden" not in untouched)

        # The other half: a case the person struck out of the approved scope.
        controller._capture_plan_baseline(controller.state())
        controller.apply("revise_plan", {
            "scope": [], "plan_revision": "plan-3",
            "reason": "drop TC-1, we test that one by hand",
            "idempotency_key": "revise-2"})
        dropped = next(row for row in json.loads(
            (root / "work/test-plan.json").read_text(encoding="utf-8"))["rows"]
            if row["id"] == "TS-1")
        check("the row that owned the dropped case is marked",
              dropped.get("overridden") is True)
        check_in("naming the case the person struck out", "cases dropped: TC-1",
                 dropped.get("overridden_change", ""))
    finally:
        cleanup(root)


# --- HF1-8 (GW1-12): the answer of a RECORDED decision says what runs next and whether the window changes ---------
# After a gate the factory used to stop unconditionally and ask the person to restart it. The answer now carries
# the next move (`next_action`, with the project's `stop_after` applied) and the window verdict (`window`), and the
# only stop left is the project's own word. The expectations are the spec's (t-050 G1..G9), not the code's.

ABSENT = object()
ANSWER_KEYS = ["recorded", "next_action", "window", "questions", "decision"]     # DC1-19: `questions` before the receipt, which stays last


def story_at_gate_b(root):
    """Gate A recorded, S5..S8 accepted: the state in which gate B is the next move."""
    controller = story(root)
    controller.apply("decision", dict(controller.build_gate_decision("A", WORDS)))
    for number in range(5, 9):
        BASE.accept_stage(controller, root, f"S{number}")
    return controller


def set_pipeline(root, value=ABSENT):
    """The project's `pipeline` block: absent, or exactly `value` (any JSON, a broken shape included)."""
    path = root / "qa-factory" / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.pop("pipeline", None)
    if value is not ABSENT:
        config["pipeline"] = value
    path.write_text(json.dumps(config), encoding="utf-8")


def set_turns(root, count, session="s-1"):
    path = root / "qa-factory" / "state" / "turns" / f"{session}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"count": count}), encoding="utf-8")


def record_by_cli(root, gate="A", *extra, words=WORDS):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return run_script("controller.py", "--task-root", root, "--operation", "gate-decision", "--gate", gate,
                      "--words", words, *extra, env=env)


def answered(root, gate="A", pipeline=ABSENT, turns=None, story_fn=None):
    """Run the CLI over a fresh story at the gate; (the CompletedProcess, the parsed answer or None)."""
    (story_fn or story)(root)
    set_pipeline(root, pipeline)
    if turns is not None:
        set_turns(root, turns)
    # GB-1a: a gate B without `--mr` orders the MR (the delivery step), so the story is `executing`, not closed; these keys are about
    # the stop and the window, and the person here said no MR: `--mr not_offered` orders nothing, the story closes into S9
    done = record_by_cli(root, gate, *(("--mr", "not_offered") if gate == "B" else ()))
    return done, (json.loads(done.stdout) if done.returncode == 0 else None)


def gate_b_flags_order_the_executors():
    """GB-1a (t-1509 §5.1a p.2): `--bugs` and `--mr` write the orders of the decision from a closed lexicon; no flag orders the MR,
    chosen drafts order the bugs, a value outside the lexicon is one refusal naming the lexicon, both flags are gate B only."""
    root = temp_project("qa-gate-orders-")
    try:
        story_at_gate_b(root)
        c = Controller(root)
        for label, flags, drafts, want in (
                ("no flags, no drafts: the MR is ordered, bugs are not", {}, [], {"bugs": "not_ordered", "mr": "due"}),
                ("drafts chosen order the bugs", {}, ["d1"], {"bugs": "due", "mr": "due"}),
                ("--bugs ordered with no drafts", {"bugs": "ordered"}, [], {"bugs": "due", "mr": "due"}),
                ("--mr open", {"mr": "open"}, [], {"bugs": "not_ordered", "mr": "due"}),
                ("--mr do_not_open", {"mr": "do_not_open"}, [], {"bugs": "not_ordered", "mr": "not_ordered"}),
                ("--mr not_offered with --bugs ordered (K13)", {"bugs": "ordered", "mr": "not_offered"}, [], {"bugs": "due", "mr": "not_ordered"})):
            request = c.build_gate_decision("B", WORDS, drafts, **flags)
            check_eq("GB-1a " + label, request["orders"], want)
            check_eq("GB-1a " + label + ": the request passes the decision check", c.check_decision(request), [])
        for flag, value in (("bugs", "yes"), ("mr", "maybe"), ("bugs", ""), ("mr", " open")):
            try:
                c.build_gate_decision("B", WORDS, [], **{flag: value})
                raised = ""
            except ValueError as exc:
                raised = str(exc)
            check_in(f"GB-1a --{flag} {value!r} is refused naming the lexicon", "must be one of:", raised)
        try:
            c.build_gate_decision("B", WORDS, [], bugs="nope", mr="nope")
        except ValueError as exc:
            check_in("GB-1a both bad flags are ONE refusal listing both", "2 problems", str(exc))
        try:
            c.build_gate_decision("A", WORDS, [], mr="open")
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in("GB-1a --mr on gate A is refused: gate B only", "gate B only", raised)
        bad = dict(c.build_gate_decision("B", WORDS, []), orders={"bugs": "done"})
        check("GB-1a a request that carries a status the decision cannot hold is refused", bool(c.check_decision(bad)))
        # L2 (GB-1a Q2, FR-10): `--bugs not_ordered` WITH chosen drafts contradicts itself: refused, both doors named; each half alone passes
        try:
            c.build_gate_decision("B", WORDS, ["d1"], bugs="not_ordered")
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in("L2 the pair is refused, naming the door that drops the drafts", "Drop --drafts", raised)
        check_in("L2 and the door that orders the bugs", "record --bugs ordered", raised)
        for label, drafts, flags, want in (("--bugs not_ordered alone", [], {"bugs": "not_ordered"}, "not_ordered"),
                                           ("--drafts alone", ["d1"], {}, "due"),
                                           ("--drafts with --bugs ordered", ["d1"], {"bugs": "ordered"}, "due"),
                                           ("blank refs are no drafts", [" ", ""], {"bugs": "not_ordered"}, "not_ordered")):
            check_eq("L2 " + label + " is accepted", c.build_gate_decision("B", WORDS, drafts, **flags)["orders"]["bugs"], want)
        run = record_by_cli(root, "B", "--drafts", "d1", "--bugs", "not_ordered")
        check_eq("L2 through the CLI the pair is exit 2", run.returncode, 2)
        check_in("L2 and the refusal reaches the caller with both doors", "record --bugs ordered", run.stderr + run.stdout)
    finally:
        cleanup(root)


def the_answer_of_a_recorded_decision_leads_with_the_next_move():
    root = temp_project("qa-gate-answer-")
    try:
        done, answer = answered(root)
        check("G1 the CLI records the decision", done.returncode == 0, done.stderr)
        check("G1 and the answer starts with the next move: a reader that cuts it still sees `next_action`",
              done.stdout.startswith('{"recorded": true, "next_action": '), done.stdout[:80])
        check_eq("G1 the keys, in order: the receipt stays whole and LAST", list(answer), ANSWER_KEYS)
        check_eq("G1 the receipt is the controller's whole record, not a reference",
                 answer["decision"]["payload"]["id"], "gateA-" + root.name)
        check_eq("G2 gate A approved, no stop_after: S5 is prepared",
                 (answer["next_action"]["action"], answer["next_action"]["stage"]), ("prepare_stage", "S5"))
        check_eq("G2 with no counter at all the window is `unknown` (AR-28): no line, nothing said about it",
                 answer["window"], {"verdict": "unknown", "line": ""})
        check_eq("G2 the decision is on disk: the words are the person's own",
                 Controller(root).state()["decisions"]["gateA-" + root.name]["authorization_source"], WORDS)
    finally:
        cleanup(root)


def the_planned_stop_is_the_projects_word_and_only_that():
    for label, pipeline, gate, story_fn, want in (
            ("G3 stop_after gate_A at gate A", {"stop_after": "gate_A"}, "A", None, "stop"),
            ("G4 stop_after gate_B at gate A: S5 goes on", {"stop_after": "gate_B"}, "A", None, "prepare_stage"),
            ("G5 gate B, no stop_after: the story closes into S9", {"stop_after": None}, "B", story_at_gate_b, "closed"),
            ("G5 gate B, stop_after gate_B: stop", {"stop_after": "gate_B"}, "B", story_at_gate_b, "stop"),
            ("G5 gate B, stop_after gate_A (a stop past gate A only): stop too", {"stop_after": "gate_A"}, "B",
             story_at_gate_b, "stop")):
        root = temp_project("qa-gate-stop-")
        try:
            done, answer = answered(root, gate, pipeline, story_fn=story_fn)
            check(f"{label}: recorded", done.returncode == 0, done.stderr)
            action = answer["next_action"]
            check_eq(f"{label}: the next action", action["action"], want)
            check_eq(f"{label}: the receipt is there, whole, whatever the next move", list(answer), ANSWER_KEYS)
            if want == "stop":
                check_eq(f"{label}: a stop prints no window line (FR-10: never together)", answer["window"], None)
                check_in(f"{label}: and says whose word it is", "pipeline.stop_after is", action["reason"])
            else:
                check_eq(f"{label}: a continue carries a window verdict", sorted(answer["window"]), ["line", "verdict"])
            if want == "closed":
                check_eq(f"{label}: S9 is what follows, and the retro is owed", (action["stage"], action.get("retro_pending")),
                         ("S9", True))
        finally:
            cleanup(root)


def an_unknown_stop_after_is_no_stop_and_no_traceback():
    """G9 / E4: the key is matched whole; whatever else it holds - another spelling, another type, a broken
    block around it - the story goes on, and the decision is still recorded (exit 0, no traceback)."""
    values = ("gate_a", "GATE_A", " gate_A", "gate_A ", "", True, 5, ["gate_A"], {"gate_A": 1}, None,
              "gate_" + chr(0x410))   # the last one: a Cyrillic A built from its code point (FR-30)
    root = temp_project("qa-gate-stop-values-")
    saved_env = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        story(root)
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        for value in values:
            set_pipeline(root, {"stop_after": value})
            hooklib._PROJECT_ROOT_CACHE = None
            check_eq(f"G9 stop_after {value!r} is no stop", CTL.stop_after(), None)
        for label, shape in (("an absent pipeline block", ABSENT), ("pipeline: null", None), ("pipeline: a list", ["x"]),
                             ("pipeline: a string", "gate_A"), ("pipeline: a number", 7)):
            set_pipeline(root, shape)
            hooklib._PROJECT_ROOT_CACHE = None
            check_eq(f"G9 {label} is no stop", CTL.stop_after(), None)
        (root / "qa-factory" / "config.json").write_text("[1]", encoding="utf-8")
        hooklib._PROJECT_ROOT_CACHE = None
        check_eq("G9 a config that is not an object is no stop", CTL.stop_after(), None)
        (root / "qa-factory" / "config.json").write_text("", encoding="utf-8")
        hooklib._PROJECT_ROOT_CACHE = None
        check_eq("G9 an empty config is no stop", CTL.stop_after(), None)
        set_pipeline_ok = json.dumps({"pipeline": {"stop_after": "gate_A"}})
        (root / "qa-factory" / "config.json").write_text(set_pipeline_ok, encoding="utf-8")
        hooklib._PROJECT_ROOT_CACHE = None
        check_eq("G9 positive control: the exact value IS read", CTL.stop_after(), "gate_A")
        (root / "qa-factory" / "config.json").write_bytes(b"\xef\xbb\xbf" + set_pipeline_ok.encode("utf-8"))
        hooklib._PROJECT_ROOT_CACHE = None
        check("G9 a BOM-prefixed config is read like every other config of the package: no traceback",
              CTL.stop_after() in (None, "gate_A"))
    finally:
        hooklib._PROJECT_ROOT_CACHE = None
        if saved_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved_env
        cleanup(root)
    for label, shape in (("pipeline: a list", ["x"]), ("stop_after: a list", {"stop_after": ["gate_A"]})):
        root = temp_project("qa-gate-stop-shape-")
        try:
            done, answer = answered(root, pipeline=shape)
            check(f"G9 through the CLI, {label}: recorded, exit 0, no traceback", done.returncode == 0 and
                  "Traceback" not in done.stderr, done.stderr)
            check_eq(f"G9 through the CLI, {label}: S5 goes on", answer["next_action"]["stage"], "S5")
        finally:
            cleanup(root)


def a_short_window_changes_where_the_story_continues_not_what_runs():
    root = temp_project("qa-gate-window-")
    try:
        window = 120
        done, answer = answered(root, turns=window - 1)         # remaining 1 < the default estimate for S5
        check("G8 recorded", done.returncode == 0, done.stderr)
        check_eq("G8 the verdict is `change`", answer["window"]["verdict"], "change")
        for needle in ("gate A is recorded", "S5 next", "/qa-factory:qa-story " + root.name,
                       "first, in this window"):
            check_in(f"G8 the line carries {needle!r}", needle, answer["window"]["line"])
        check_eq("G8 and the next action is still S5: a window change never changes what runs next",
                 (answer["next_action"]["action"], answer["next_action"]["stage"]), ("prepare_stage", "S5"))
        check_eq("G8 the answer is whole", list(answer), ANSWER_KEYS)
    finally:
        cleanup(root)
    root = temp_project("qa-gate-window-room-")
    try:
        done, answer = answered(root, turns=10)
        check_eq("G8 control: with room the verdict is `fits` and there is no line",
                 answer["window"], {"verdict": "fits", "line": ""})
    finally:
        cleanup(root)
    root = temp_project("qa-gate-window-b-")
    try:
        done, answer = answered(root, "B", turns=119, story_fn=story_at_gate_b)
        check_eq("G8 gate B: the change line names S9 and the delivery that comes first",
                 (answer["window"]["verdict"], "S9 next" in answer["window"]["line"],
                  "Deliver what the decision authorized first" in answer["window"]["line"]), ("change", True, True))
        check_eq("G8 gate B: the retro still follows in next_action", answer["next_action"]["stage"], "S9")
    finally:
        cleanup(root)


def a_refused_or_inspected_decision_carries_no_next_move_and_no_window():
    root = temp_project("qa-gate-refused-")
    try:
        story(root)
        set_turns(root, 119)
        done = record_by_cli(root, "B")        # gate B at gate A's moment: the story is not ready
        check_eq("G6 a refused decision exits 2", done.returncode, 2)
        refusal = json.loads(done.stderr)
        check_eq("G6 and its stderr keys are the old ones, the mark of where the items' sentences start, and what the words did (DC1-19)",
                 sorted(refusal), ["item_problems_from", "problems", "questions", "recorded", "request"])
        check_eq("G6 it says nothing was recorded", refusal["recorded"], False)
        check_eq("G6 and printed nothing on stdout (no composed next, no window)", done.stdout, "")
        built = record_by_cli(root, "A", "--build-only")
        check_eq("G7 --build-only exits 0", built.returncode, 0)
        check_eq("G7 and its keys are the old ones and the mark of where the items' sentences start", sorted(json.loads(built.stdout)),
                 ["item_problems_from", "problems", "recorded", "request"])
        check_eq("G7 nothing was recorded by the inspection", Controller(root).state()["decisions"], {})
    finally:
        cleanup(root)


# --- RH1-6: a gate A approval records only over items the person has worded --------------------------

def item_of(number, kind, block):
    return {"id": f"fx-{number}", "check": "fx", "message": f"open item {number}",
            "door": {"kind": kind, "says": "your word", "block": block, "stage": "S5" if block else "", "waives": []}}


class FakeItems:
    """`gate_brief.open_rehearsal_items` standing in for the rehearsal: an item is open until a live override carries its block."""

    def __init__(self, items, status="read"):
        import gate_brief
        self.gate_brief, self.items, self.status, self.real = gate_brief, items, status, gate_brief.open_rehearsal_items

    def __enter__(self):
        def fake(task_root, gate="A", rehearsed=None):
            if self.status != "read":
                return {"status": "unknown", "items": [], "why": "OSError: down"}
            matches = {o.get("match") for o in stage_overrides_of(Path(task_root)) if not o.get("revoked_at")}
            still = [i for i in self.items if i["door"]["kind"] == "none" or i["door"]["block"] not in matches]
            # a `none` item is dropped by the REAL filter (B1): the fake never re-implements what the reader decides
            return {"status": "read", "why": "", "items": self.gate_brief._drop_as_is_items(Path(task_root), gate, still)}
        self.gate_brief.open_rehearsal_items = fake
        return self

    def __exit__(self, *exc):
        self.gate_brief.open_rehearsal_items = self.real


def rh16_refusal_and_its_doors():
    root = temp_project("qa-rh16-refuse-")
    try:
        controller = story(root, leave_item_open=True)
        before = controller.state()
        done = record_by_cli(root, "A")
        refusal = json.loads(done.stderr)
        check_eq("A-K6 an unanswered item with no door refuses: exit 2", done.returncode, 2)
        check_eq("A-K6 the refusal keeps the transport and adds `open_items` and the items' start in `problems`, in order", list(refusal),
                 ["recorded", "problems", "item_problems_from", "open_items", "request", "questions"])
        check_eq("A-K6 no factory sentence stands before the items", refusal["item_problems_from"], 0)
        check_eq("A-K6 the item is named, with its `words` door", (refusal["open_items"][0]["id"], refusal["open_items"][0]["door"]["kind"]),
                 ("s5_executor-1", "words"))
        check_in("A-K6 the closing sentence keeps the approval and names the closed word", "Your approval is kept", refusal["problems"][-1])
        check_in("A-K6 and `approve as is`", "`approve as is`", refusal["problems"][-1])
        check_eq("A-K6 nothing was recorded: decisions and revision unchanged",
                 (Controller(root).state()["decisions"], Controller(root).state()["revision"]), (before["decisions"], before["revision"]))
        built = record_by_cli(root, "A", "--build-only")
        check_eq("A-K8 --build-only lists open_items and exits 0", (built.returncode, "open_items" in json.loads(built.stdout)), (0, True))
        check_eq("A-K8 and records nothing", Controller(root).state()["decisions"], {})
        request = controller.build_gate_decision("A", WORDS)
        cls, raised = recorded_refusal(controller, request)
        check_in("A-K13 the raw `decision` road refuses the same story", "[s5_executor-1]", raised)
        check_eq("A-K13 in the story's class", cls, StateConflict)
        import gate_brief
        import gate_preflight
        calls = []
        real = gate_brief.open_rehearsal_items
        gate_brief.open_rehearsal_items = lambda *a, **k: calls.append(a) or real(*a, **k)
        try:
            gate_preflight.run(root, "A")
        finally:
            gate_brief.open_rehearsal_items = real
        check_eq("A-K10 the rehearsal never reads open items", calls, [])
        check_not_in("A-K10 and `check_decision` holds no open-item sentence", "needs your word", "\n".join(controller.check_decision(request)))
        add_override(root, "S5", FIXTURE_ITEM_BLOCK)
        check_eq("A-K7 the waiver at the item's block lets it record", record_by_cli(root, "A").returncode, 0)
    finally:
        cleanup(root)
    root = temp_project("qa-rh16-gate-b-")
    try:
        story(root)
        done = record_by_cli(root, "B", "--as-is")
        check_eq("A-K26 --as-is at gate B is refused", done.returncode, 2)
        check_in("A-K26 and says gate A only", "gate A only", done.stderr)
    finally:
        cleanup(root)


def rh16_listing_and_unknown():
    root = temp_project("qa-rh16-list-")
    try:
        controller = story(root)
        for count in (20, 21):
            with FakeItems([item_of(n, "words", f"block number {n}") for n in range(count)]):
                problems, items = controller.open_gate_items("A")
            more = [p for p in problems if p.startswith("and ")]
            check_eq(f"A-K12 {count} items: the machine list is whole", len(items), count)
            check_eq(f"A-K12 {count} items: the sentences are cut at 20, the rest counted", (len(problems) - 1 - len(more), more[0][:10] if more else None),
                     (20, "and 1 more" if count == 21 else None))
        long = item_of(1, "words", "block")
        long["message"] = "m" * 400
        with FakeItems([long]):
            problems, _ = controller.open_gate_items("A")
        check_eq("A-E13 one sentence is cut at 300 characters with an ellipsis", (len(problems[0]), problems[0][-1]), (301, "…"))
        with FakeItems([], status="unknown"):
            problems, items = controller.open_gate_items("A")
            check_in("A-K5c an unreadable list refuses, and names why", "could not be listed (OSError: down)", problems[0])
            check_in("A-K5c with the S4 block the person's word records", "gate A open items: unreadable", problems[0])
            add_override(root, "S4", "gate A open items: unreadable")
            check_eq("A-K5c the person's word at S4 lets it record", controller.open_gate_items("A"), ([], []))
        check_eq("gate B has no items", controller.open_gate_items("B"), ([], []))
    finally:
        cleanup(root)


def rh16_as_is():
    root = temp_project("qa-rh16-asis-")
    try:
        controller = story(root)
        two = [item_of(1, "line", "stand gap: TC-1"), item_of(2, "words", "words block two")]
        with FakeItems(two):
            ids = controller.record_as_is("A", WORDS)
        matches = [(o["stage"], o["match"]) for o in stage_overrides_of(root) if o["match"] != FIXTURE_ITEM_BLOCK]
        check_eq("A-K20 two waivers, each at its own block", (ids, matches), (["fx-1", "fx-2"], [("S5", "stand gap: TC-1"), ("S5", "words block two")]))
        check_not_in("A-K20 and NO `*` in the overrides", "*", [o["match"] for o in stage_overrides_of(root)])
        check("A-K20 the decision carries the person's words after the option word",
              all(o["decision"] == "accept - the person wrote: " + WORDS for o in stage_overrides_of(root) if o["match"] != FIXTURE_ITEM_BLOCK))
        from waiver import split_overridden
        check_eq("A-K21 an unrelated S5 error is NOT passed (no `*` breadth)",
                 split_overridden(["some unrelated S5 error"], {"stage_overrides": stage_overrides_of(root)}, "S5")[0], ["some unrelated S5 error"])
        (root / "pipeline.json").write_text("[1]", encoding="utf-8")
        try:
            with FakeItems([item_of(3, "words", "never recorded")]):
                controller.record_as_is("A", WORDS)
            raised = ""
        except StateConflict as exc:
            raised = str(exc)
        check_in("A-K25 a waiver that cannot be recorded names its item and records no decision", "fx-3", raised)
    finally:
        cleanup(root)
    root = temp_project("qa-rh16-asis-cli-")
    try:
        story(root, leave_item_open=True)
        done = record_by_cli(root, "A", "--as-is", words="approve as is")
        answer = json.loads(done.stdout) if done.returncode == 0 else {}
        check("A-AC3b the CLI records over the open item", done.returncode == 0, done.stderr[:400])
        check_eq("A-AC3b the answer row names the item, and the receipt stays last", (answer.get("as_is"), list(answer)[-1]),
                 ("approved as is over: s5_executor-1", "decision"))
        check_eq("A-AC3b one waiver at the item's own block, never `*`", [o["match"] for o in stage_overrides_of(root)][0].startswith("no execution profile"), True)
    finally:
        cleanup(root)
    root = temp_project("qa-rh16-asis-none-")
    try:
        story(root)
        before = len(stage_overrides_of(root))
        done = record_by_cli(root, "A", "--as-is", words="approve as is")
        check_eq("A-E1 as-is over zero items records as `approve` does: no waiver, no `as_is` row",
                 (done.returncode, len(stage_overrides_of(root)) == before, "as_is" in done.stdout), (0, True, False))
    finally:
        cleanup(root)


def main_inprocess(root, *args, gate="A", words=WORDS):
    """`controller.py --operation gate-decision` run IN this process (its `main`): (exit code, stdout, stderr). Lets a test count what the
    rehearsal does and stub `check_decision`, which a subprocess cannot."""
    import contextlib
    import io
    old_argv, old_env = sys.argv, os.environ.get("CLAUDE_PROJECT_DIR")
    sys.argv = ["controller.py", "--task-root", str(root), "--operation", "gate-decision", "--gate", gate, "--words", words, *args]
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CTL.main()
            except SystemExit as exc:
                code = exc.code or 0
    finally:
        sys.argv = old_argv
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
    return code, out.getvalue(), err.getvalue()


def rh16_b1_a_doorless_item_is_passed_by_as_is():
    """B1 (critic t-1447): `approve as is` over a `none` item records a block the ONE reader reads back as answered; the fake in
    `FakeItems` calls the real filter, so these fail on the old code (the S4 block `gate A open items: unreadable`, which nothing read)."""
    import gate_brief
    root = temp_project("qa-rh16-b1-")
    try:
        controller = story(root)
        doorless = item_of(1, "none", "")
        with FakeItems([doorless]):
            ids = controller.record_as_is("A", WORDS)
            left = controller.open_gate_items("A")
        waivers = [o for o in stage_overrides_of(root) if o["match"].startswith("gate A item without a door:")]
        check_eq("B1 record `approve as is` over a `none` item: the item is recorded", ids, ["fx-1"])
        check_eq("B1 the re-check lists nothing", left, ([], []))
        check_eq("B1 one waiver for the item, at S4, with its id and its message in the block",
                 [(o["stage"], o["match"]) for o in waivers], [("S4", "gate A item without a door: [fx-1] open item 1")])
        check_eq("B1 the decision carries the person's words", waivers[0]["decision"], "accept - the person wrote: " + WORDS)
        # one waiver PER item: two doorless items are two entries, never one block for both and never `*`
        two = [item_of(1, "none", ""), item_of(2, "none", "")]
        with FakeItems(two):
            controller.record_as_is("A", WORDS)
            check_eq("B1 two doorless items: both closed", controller.open_gate_items("A"), ([], []))
        check_eq("B1 and two own blocks", sorted(o["match"] for o in stage_overrides_of(root) if o["match"].startswith("gate A item without")),
                 ["gate A item without a door: [fx-1] open item 1", "gate A item without a door: [fx-2] open item 2"])
        check_not_in("B1 never `*`", "*", [o["match"] for o in stage_overrides_of(root)])
        # the allowed error is asking again: a waiver for [fx-1] passes neither another text under that id nor that text under another id
        other_text = dict(doorless, message="a different finding now numbered fx-1")
        renumbered = dict(doorless, id="fx-9")
        with FakeItems([other_text, renumbered]):
            check_eq("B1 control: another text under the id, and the text under another id, stay open",
                     [i["id"] for i in controller.open_gate_items("A")[1]], ["fx-1", "fx-9"])
        # the generic block of an UNREADABLE list is not a substring of an item's block: it passes no item
        root2 = temp_project("qa-rh16-b1-generic-")
        try:
            controller2 = story(root2)
            add_override(root2, "S4", "gate A open items: unreadable")
            with FakeItems([doorless]):
                check_eq("B1 control: the unreadable-list word does not pass a doorless item",
                         [i["id"] for i in controller2.open_gate_items("A")[1]], ["fx-1"])
        finally:
            cleanup(root2)
        check_eq("B1 the block builder is the reader's", gate_brief.none_item_block("A", doorless), "gate A item without a door: [fx-1] open item 1")
    finally:
        cleanup(root)


def rh16_m1_the_as_is_word_is_journalled_like_any_person_answer():
    """M1: `record_as_is` stores through `waiver.record_stage_overrides`, which journals one `human_answer` line per item (brief_pack reads them)."""
    import log_append
    root = temp_project("qa-rh16-m1-")
    seen = []
    real = log_append.write
    log_append.write = lambda records: seen.extend(records)
    try:
        controller = story(root)
        with FakeItems([item_of(1, "line", "stand gap: TC-1"), item_of(2, "none", "")]):
            controller.record_as_is("A", WORDS)
        notes = sorted(r["notes"] for r in seen if r.get("event") == "human_answer")
        check_eq("M1 one `human_answer` line per item", len(notes), 2)
        check_eq("M1 the line names the stage, the block and the person's words",
                 notes[0], "S4 block passed by the person's word [gate A item without a door: [fx-2] open item 2]: accept - the person wrote: " + WORDS)
        check_in("M1 and the line item's", "S5 block passed by the person's word [stand gap: TC-1]", notes[1])
    finally:
        log_append.write = real
        cleanup(root)


def rh16_m2_factory_problems_and_items_together_a_k9():
    """A-K9 / M2: the factory's own sentence comes first, the closing sentence does not offer `approve as is` (the flag is skipped while a
    factory problem stands), and no waiver is written."""
    root = temp_project("qa-rh16-k9-")
    real = Controller.check_decision
    Controller.check_decision = lambda self, payload: ["the factory's own sentence"]
    try:
        story(root)
        before = len(stage_overrides_of(root))
        with FakeItems([item_of(1, "words", "words block one")]):
            code, out, err = main_inprocess(root, "--as-is", words="approve as is")
        record = json.loads(err)
        check_eq("A-K9 the refusal exits 2", code, 2)
        check_eq("A-K9 the factory sentence comes first, and the mark says where the items start",
                 (record["problems"][0], record["item_problems_from"]), ("the factory's own sentence", 1))
        check_in("A-K9 the item follows", "[fx-1]", record["problems"][1])
        check_not_in("A-K9 the closing sentence does not offer `approve as is`", "approve as is", record["problems"][-1])
        check_in("A-K9 but still keeps the approval", "Your approval is kept", record["problems"][-1])
        check_eq("A-K9 `--as-is` wrote no waiver", len(stage_overrides_of(root)), before)
    finally:
        Controller.check_decision = real
        cleanup(root)


def rh16_m5_one_rehearsal_per_decision_none_under_the_store_lock():
    """M5 (AR-12): a plain gate-decision runs the gate rehearsal ONCE, `--as-is` twice (the read, and the fresh re-check after recording),
    and never inside the event store's lock (it starts subprocesses). Counted at the rehearsal itself."""
    import gate_preflight
    import event_store
    real_run, real_commit = gate_preflight.run, event_store.EventStore.commit
    for label, leave_open, extra, expected in (("plain approve", False, (), 1), ("--as-is", True, ("--as-is",), 2)):
        root = temp_project("qa-rh16-m5-")
        runs, locked = [], [False]

        def counting(task_root, gate="A", _runs=runs, _locked=locked):
            _runs.append(bool(_locked[0]))
            return real_run(task_root, gate)

        def commit(self, *a, _locked=locked, **k):
            _locked[0] = True
            try:
                return real_commit(self, *a, **k)
            finally:
                _locked[0] = False
        gate_preflight.run, event_store.EventStore.commit = counting, commit
        try:
            story(root, leave_item_open=leave_open)
            code, out, err = main_inprocess(root, *extra, words="approve as is" if extra else WORDS)
            check_eq(f"M5 {label} records", code, 0)
            check_eq(f"M5 {label}: rehearsals run", len(runs), expected)
            check_eq(f"M5 {label}: none of them inside the store lock", any(runs), False)
        finally:
            gate_preflight.run, event_store.EventStore.commit = real_run, real_commit
            cleanup(root)


def main():
    rh16_refusal_and_its_doors()
    rh16_listing_and_unknown()
    rh16_as_is()
    rh16_b1_a_doorless_item_is_passed_by_as_is()
    rh16_m1_the_as_is_word_is_journalled_like_any_person_answer()
    rh16_m2_factory_problems_and_items_together_a_k9()
    rh16_m5_one_rehearsal_per_decision_none_under_the_store_lock()
    the_answer_of_a_recorded_decision_leads_with_the_next_move()
    gate_b_flags_order_the_executors()
    the_planned_stop_is_the_projects_word_and_only_that()
    an_unknown_stop_after_is_no_stop_and_no_traceback()
    a_short_window_changes_where_the_story_continues_not_what_runs()
    a_refused_or_inspected_decision_carries_no_next_move_and_no_window()
    the_decision_is_built_by_code()
    an_empty_historical_scope_is_not_a_refusal()
    an_unreviewed_case_is_still_a_refusal()
    a_designer_is_credited_by_the_plan_rows_it_was_sent()
    a_legacy_opener_is_credited_only_by_its_own_evidence()
    a_designer_with_a_present_but_empty_plan_rows_credits_nothing()
    a_critics_roll_call_never_credits_a_designer_that_spoke_in_rows()
    a_designer_with_another_input_hash_is_still_refused()
    a_critic_is_never_credited_by_rows_or_evidence()
    plan_rows_membership_is_exact()
    legacy_evidence_is_matched_whole_and_only_for_an_accepted_opener()
    the_second_designer_round_keeps_the_openers_rows()
    prepare_records_the_plan_rows_for_the_designer_only()
    check_and_record_are_the_same_rules()
    several_problems_are_reported_at_once()
    a_collected_refusal_has_the_class_of_its_first_problem()
    identical_problems_are_merged_into_one_line()
    an_unverifiable_row_owes_no_design_review()
    the_builder_names_its_allowed_values()
    gate_b_takes_the_chosen_drafts_by_flag()
    the_design_review_verdict_is_the_critics_own()
    gate_a_overrides_are_marked_by_code()
    rn1_20_k_d1_designer_after_critic_voids_the_review()
    rn1_20_k_d3_the_packet_line_for_a_stale_review()
    rn1_20_k_d4_q2_a_row_patched_by_an_answer_after_the_critic_is_no_refusal()
    finish("test_controller_gate_decision")


if __name__ == "__main__":
    main()
