#!/usr/bin/env python3
"""The defects TP1-13797 exhibited on 2026-09-23/24, one section each.

F1 (FB-10)  an S5 window may list no instance for a case the manifest calls `impossible` or
            `handed_to_person`, when the completion says so too — every other case keeps the rule.
F2 (FB-10)  ledger, delivery and traceability read `test-plan.md` from `work/` when the story
            root has none, like every other reader.
F3          a consolidated test proves the cases in `covers[]`, not only its singular `case`.
F5          S6 completes only when its derived scope — the manual-agent half included — is
            covered by accepted dispatches; a person's word passes it.
F6          a fresh story initializes `new` / coverage v2 with no phantom `legacy:S1`: the S0
            template's pending placeholder is not an inherited running role.
F7 (FB-12)  rows that join no manifest instance do not vote on `execution_status`.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (GOOD, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, mark_project, s5_window_form, temp_project)

sys.path.insert(0, str(SCRIPTS))
import check_delivery as D  # noqa: E402
import check_traceability as T  # noqa: E402
import contract as C  # noqa: E402
import finalize_task as F  # noqa: E402
import ledger as L  # noqa: E402
import waiver  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import StateConflict, content_hash  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework_scope as SCOPED  # noqa: E402
import test_coverage_controller_integration as COV  # noqa: E402


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def refused(fn, *args):
    """The message of the refusal, or '' when the call went through."""
    try:
        fn(*args)
    except (ValueError, StateConflict) as exc:
        return str(exc)
    return ""


# --- F1: a case with no instance -------------------------------------------------------------

def v2_story_at_s5(root: Path):
    """A coverage-v2 story through gate A with two cases: TC-1 has a test, TC-2 will have none.
    Returns (controller, window, obligations) with the author accepted and the critic running."""
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1", "TC-2"], "source_revision": "src",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(3):
        COV.accept_stage(controller, root, number)
    one, two = COV.obligation("O-1", "R-1"), COV.obligation("O-2", "R-2")
    row = {"id": "TS-1", "schema_version": 2, "impact": "moderate", "likelihood": "medium",
           "confidence": "high", "risk_rationale": "two effects", "risk_source_refs": ["R-1", "R-2"],
           "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1", "R-2"],
           "unknowns": [], "verification_depth": "normal", "required_scenarios": ["TC-1", "TC-2"],
           "test_level_rationale": "unit", "design_review_required": False,
           "coverage_contract_revision": "coverage-observation-v1",
           "coverage_delta": {"baseline_kind": "initial", "initial_scope_rationale": "fixture",
                              "planned_instance_ids": ["i-1"],
                              "counts": {"logical_cases_before": 2, "logical_cases_after": 2,
                                         "executable_instances_before": 1, "executable_instances_after": 1},
                              "entries": [{"obligation_id": "O-1", "disposition": "reuse", "rationale": "a", "existing_case_refs": ["TC-1"]},
                                          {"obligation_id": "O-2", "disposition": "reuse", "rationale": "b", "existing_case_refs": ["TC-2"]}]},
           "coverage_obligations": [one, two]}
    document = {"schema_version": 2, "rows": [row], "lifecycle_actions": []}
    (root / "work").mkdir(exist_ok=True)
    (root / "work/test-plan.json").write_text(json.dumps(document), encoding="utf-8")
    COV.accept_stage(controller, root, 3)
    (root / "state").mkdir(exist_ok=True)
    (root / "state/story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": "TC-1", "version": "cv1"}, {"case_id": "TC-2", "version": "cv2"}]}), encoding="utf-8")
    COV.accept_stage(controller, root, 4)
    controller.apply("decision", {
        "id": "A", "gate": "A", "action": "approve", "status": "approved",
        "authorization_source": "human", "source_revision": "src", "scope": ["TC-1", "TC-2"],
        "input_revision": "src", "plan_content_hash": content_hash(document),
        "plan_semantic_hash": Controller._plan_semantic_hash(document),
        "oracle_content_hashes": Controller._oracle_hashes([row]),
        "coverage_contract_revisions": ["coverage-observation-v1"], "idempotency_key": "A"})
    with s5_window_form(controller, root):      # SC1-14 B1b: the rows carry no disposition, so this story begins on the earlier form
        controller.apply("dispatch", {"id": "s5-author", "stage": "S5", "role": "qa-automator",
                                      "scope": ["TC-1", "TC-2"], "input_hash": "s5-h", "budget": {},
                                      "known_paths": {}, "idempotency_key": "s5-author"})
    controller.apply("accept", {"id": "s5-author", "status": "accepted", "stage_complete": False,
                                "evidence_refs": [COV.evidence(root, "author.txt", "author green")],
                                "idempotency_key": "s5-author-accept"})
    controller.apply("dispatch", {"id": "s5-critic", "stage": "S5", "role": "qa-code-critic",
                                  "scope": ["TC-1", "TC-2"], "input_hash": "s5-h", "budget": {},
                                  "known_paths": {}, "idempotency_key": "s5-critic"})
    (root / "critic-findings.md").write_bytes(b"findings")
    refs = [{"obligation_id": "O-1", "obligation_hash": content_hash(one)},
            {"obligation_id": "O-2", "obligation_hash": content_hash(two)}]
    instance = {"schema_version": 2, "instance_id": "i-1", "outcome": "passed", "input_hash": "s5-h",
                "review": {"verdict": "approved", "input_hash": "s5-h"},
                "change_disposition": "unchanged", "change_basis_ref": "repo:test-sha",
                "obligation_ids": ["O-1", "O-2"], "obligation_refs": refs,
                "obligation_hash": content_hash(refs), "assertion_id": "tests/test_one.py:9",
                "defect_location": "src/one.py:4", "execution_fingerprint": "run-fingerprint",
                "evidence_refs": [COV.evidence(root, "run.txt", "one selected execution")]}
    window = {"schema_version": 2, "input_hash": "s5-h", "required_quality_checks": [],
              "author_dispatch_id": "s5-author", "reviewer_dispatch_id": "s5-critic",
              "quality_receipts": [], "scope_instances": {"TC-1": ["i-1"], "TC-2": []},
              "instances": [instance]}
    return controller, window


def manifest_with(root: Path, reason: str) -> None:
    write_json(root / "work/automation-manifest.json", {
        "tests": [{"instance_id": "i-1", "case": "TC-1", "covers": ["TC-1"], "status": "green",
                   "test": "tests/test_one.py::test_one"}],
        "unresolved": [{"case": "TC-2", "reason": reason, "detail": "every Then of TC-2 reads the "
                        "caller's own memory; nothing observable outside it"}]})


def completion(window, key, **extra):
    # The critic's own receipts (a findings file) travel with every completion: once a
    # manifest exists, the controller asks for them before anything about the window.
    return dict({"id": "s5-critic", "status": "accepted", "stage_complete": True, "window": window,
                 "evidence_refs": [{"path": "run.txt", "sha256": hashlib.sha256(b"one selected execution").hexdigest()},
                                   {"path": "critic-findings.md", "sha256": hashlib.sha256(b"findings").hexdigest()}],
                 "idempotency_key": key}, **extra)


def f1_an_impossible_case_may_list_no_instance():
    root = temp_project("qa-13797-f1-")
    try:
        controller, window = v2_story_at_s5(root)
        message = refused(controller.apply, "accept", completion(window, "no-manifest"))
        check_in("F1: with no manifest an empty list is still refused", "TC-2 lists no instance", message)
        check_in("F1: and the refusal names the two conditions", "`impossible` or `handed_to_person`", message)
        manifest_with(root, "blocked_by_env")
        message = refused(controller.apply, "accept",
                          completion(window, "env", unresolved=["TC-2"], reason="stand down"))
        check_in("F1: a stand problem is not a case with no instance", "it does not carry TC-2", message)
        manifest_with(root, "impossible")
        message = refused(controller.apply, "accept", completion(window, "silent"))
        check_in("F1: the manifest alone is not enough — the completion must say it",
                 "names it in `unresolved` with a `reason`", message)
        message = refused(controller.apply, "accept",
                          completion(window, "spoken", unresolved=["TC-2"],
                                     reason="TC-2 impossible: no observable outside the caller"))
        check_eq("F1: manifest `impossible` + completion `unresolved`/`reason` completes the window", message, "")
        state = controller.state()
        check_eq("F1: S5 is completed", state["stages"]["S5"]["status"], "completed")
        check_eq("F1: on the critic's acceptance", state["dispatches"]["s5-critic"]["status"], "accepted")
    finally:
        cleanup(root)


def f1_a_handed_case_may_list_no_instance_and_others_keep_the_rule():
    root = temp_project("qa-13797-f1b-")
    try:
        controller, window = v2_story_at_s5(root)
        manifest_with(root, "handed_to_person")
        wrong = dict(window, scope_instances={"TC-1": [], "TC-2": []}, instances=[])
        message = refused(controller.apply, "accept",
                          completion(wrong, "tc1-empty", unresolved=["TC-2"], reason="handed_to_person: the person runs TC-2"))
        check_in("F1: a case the manifest has a test for keeps the nonempty rule", "it does not carry TC-1", message)
        message = refused(controller.apply, "accept",
                          completion(window, "handed", unresolved=["TC-2"],
                                     reason="handed_to_person: the person runs TC-2 under the ios profile"))
        check_eq("F1: `handed_to_person` closes the same way", message, "")
        check_eq("F1: S5 completed", controller.state()["stages"]["S5"]["status"], "completed")
    finally:
        cleanup(root)


# --- F2 / F3: the plan under work/, the cases in covers[] ------------------------------------

def f2_the_plan_is_read_from_work():
    root = temp_project("qa-13797-f2-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        before = (len(L.build(art)["rows"]), T.walk(art)["ok"], D.completeness_reasons(art))
        shutil.move(str(art / "test-plan.md"), str(art / "work" / "test-plan.md"))
        check_eq("F2: contract.artifact finds test-plan.md under work/ when the root has none",
                 C.artifact(art, "test-plan.md"), art / "work" / "test-plan.md")
        check_eq("F2: the ledger reads the same rows", len(L.build(art)["rows"]), before[0])
        check_eq("F2: traceability still reaches every requirement", T.walk(art)["ok"], before[1])
        check_eq("F2: delivery completeness sees the plan", D.completeness_reasons(art), before[2])
        check_not_in("F2: no requirement is called unreachable",
                     "no row of test-plan.md names", json.dumps(T.walk(art)["rows"]))
        shutil.copy(str(art / "work" / "test-plan.md"), str(art / "test-plan.md"))
        check_eq("F2: a plan at the story root still wins over the copy under work/",
                 C.artifact(art, "test-plan.md"), art / "test-plan.md")
    finally:
        cleanup(root)


def f3_a_consolidated_test_covers_its_cases():
    root = temp_project("qa-13797-f3-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        case = art / "work" / "test-cases" / "checkout" / "TC-003.md"
        case.write_text((art / "work" / "test-cases" / "checkout" / "TC-001.md").read_text(encoding="utf-8")
                        .replace("id: TC-001", "id: TC-003")
                        .replace("title: A coupon above the cap", "title: A coupon at the cap"), encoding="utf-8")
        manifest_path = art / "work" / "automation-manifest.json"
        manifest = C.load_json(manifest_path)
        reasons = D.completeness_reasons(art)
        check_in("F3: a second automate case on the row with no test is named", "TC-003", "\n".join(reasons))
        manifest["tests"][0]["covers"] = ["TC-001", "TC-003"]
        write_json(manifest_path, manifest)
        check_eq("F3: the same case named in the test's covers[] is tested", D.completeness_reasons(art), [])
    finally:
        cleanup(root)


# --- F5: S6 completes over its whole derived scope -------------------------------------------

def s6_story(root: Path):
    mark_project(root)
    c = Controller(root)
    c.apply("initialize", {"scope": ["TC-1", "TC-2"], "source_revision": "src-1",
                           "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    BASE.seed_plan(root, [SCOPED.plan_row(1, "automate"), SCOPED.plan_row(2, "manual-agent")])
    (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": "TC-1", "version": "cv_1"}, {"case_id": "TC-2", "version": "cv_2"}]}), encoding="utf-8")
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                "authorization_source": "human", "source_revision": "src-1", "scope": ["TC-1", "TC-2"],
                "input_revision": "src-1", "idempotency_key": "gate-a"}
    c.apply("decision", BASE.bind_gate_a(root, decision))
    BASE.accept_stage(c, root, "S5")
    return c


def runner(c, root, dispatch_id, kind, scope, complete, **extra):
    request = {"id": dispatch_id, "stage": "S6", "role": "qa-runner", "execution_kind": kind,
               "scope": scope, "input_hash": "s6", "budget": {}, "known_paths": {},
               "idempotency_key": "dispatch-" + dispatch_id}
    if kind == "manual":
        request["manual_case_ids"] = list(scope)
    if dispatch_id not in c.state()["dispatches"]:
        c.apply("dispatch", request)
    if complete:
        # X7-6c: S6 closes only over the consumer's (failure analyst's) acceptance record, never on the runner's own word
        BASE.record_stage_acceptance(root, "S6", dispatch_id)
    return refused(c.apply, "accept", dict({
        "id": dispatch_id, "status": "accepted", "stage_complete": complete,
        "evidence_refs": [BASE.evidence_ref(root, dispatch_id + ".txt", dispatch_id)],
        "idempotency_key": "accept-" + dispatch_id + ("-complete" if complete else "")}, **extra))


def f5_s6_does_not_close_over_an_undispatched_manual_half():
    root = temp_project("qa-13797-f5-")
    try:
        c = s6_story(root)
        check_eq("F5: the derived S6 scope carries both halves",
                 c.stage_scope("S6", c.state())["scope"], ["TC-1", "TC-2"])
        message = runner(c, root, "S6-auto", "automation", ["TC-1"], True)
        check_in("F5: the automation half cannot complete S6 alone", "manual-agent case TC-2", message)
        check_in("F5: the refusal says how to go on", "stage_complete: false", message)
        check_in("F5: and how a person passes it", "--block \"derived scope\"", message)
        check_eq("F5: S6 stays open", c.state()["stages"]["S6"]["status"], "running")
        check_eq("F5: the same acceptance without stage_complete goes through",
                 runner(c, root, "S6-auto", "automation", ["TC-1"], False), "")
        check_eq("F5: the manual half completes the stage",
                 runner(c, root, "S6-manual", "manual", ["TC-2"], True), "")
        check_eq("F5: S6 completed", c.state()["stages"]["S6"]["status"], "completed")
    finally:
        cleanup(root)


def f5_a_person_may_close_s6_without_the_manual_half():
    root = temp_project("qa-13797-f5b-")
    try:
        c = s6_story(root)
        pipeline_path = root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8")) if pipeline_path.is_file() else {}
        pipeline = waiver.apply_stage_override(pipeline, "S6", "derived scope",
                                               "I ran TC-2 myself on the stand", waiver.now_iso())
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("F5: the recorded word passes the block",
                 runner(c, root, "S6-auto", "automation", ["TC-1"], True), "")
        check_eq("F5: S6 completed on it", c.state()["stages"]["S6"]["status"], "completed")
    finally:
        cleanup(root)


# --- F6: a fresh story is not a legacy one -------------------------------------------------

def s0_pipeline(root: Path, s1: dict) -> None:
    write_json(root / "pipeline.json", {
        "ticket": root.name, "environment": "localhost", "environment_pending": False, "warnings": [],
        "stages": {"S0": {"status": "done", "started": "2026-09-24T02:01:28Z",
                          "finished": "2026-09-24T02:24:44+00:00", "role": None,
                          "digest": "preflight green, env=localhost"},
                   "S1": s1},
        "gates": {}, "halts": []})


def initialize(root: Path) -> dict:
    Controller(root).apply("initialize", {"scope": [], "source_revision": "src",
                                          "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    return Controller(root).state()


def f6_a_fresh_story_initializes_new_without_a_phantom():
    root = temp_project("qa-13797-f6-")
    try:
        s0_pipeline(root, {"status": "pending", "role": "qa-scout", "digest": ""})
        state = initialize(root)
        check_eq("F6: the S0 template gives a `new` story", state.get("plan_contract_mode"), "new")
        check_eq("F6: on coverage v2", state.get("coverage_contract_version"), 2)
        check_eq("F6: no `legacy:S1` phantom", [d for d in state["dispatches"] if d.startswith("legacy:")], [])
        check_eq("F6: S1 is not imported at all", state["stages"].get("S1"), None)
        check_eq("F6: the closed S0 is still imported as completed",
                 (state["stages"]["S0"]["status"], state["stages"]["S0"].get("imported")), (True and "completed", True))
        action = Controller(root).next_action()
        check_not_in("F6: the next action asks nobody to reconcile a phantom", "legacy", json.dumps(action))
    finally:
        cleanup(root)


def f6_a_real_legacy_pipeline_still_imports():
    root = temp_project("qa-13797-f6b-")
    try:
        s0_pipeline(root, {"status": "running", "role": "qa-scout", "digest": "", "dispatch_id": "S1-qa-scout-1"})
        state = initialize(root)
        check_eq("F6: a running S1 is inherited", state["dispatches"].get("legacy:S1", {}).get("status"), "incomplete")
        check_eq("F6: and the story is a legacy one", state.get("plan_contract_mode"), "legacy")
        check_eq("F6: on coverage v1", state.get("coverage_contract_version"), 1)
    finally:
        cleanup(root)
    root = temp_project("qa-13797-f6c-")
    try:
        s0_pipeline(root, {"status": "pending", "role": "qa-scout", "digest": "", "dispatch_id": "S1-qa-scout-1"})
        state = initialize(root)
        check_eq("F6: a `pending` receipt that names its dispatch is inherited too",
                 state["dispatches"].get("legacy:S1", {}).get("status"), "incomplete")
    finally:
        cleanup(root)


# --- F7: debris rows do not decide execution_status ---------------------------------------

def f7_unjoined_rows_do_not_vote():
    root = temp_project("qa-13797-f7-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-7"
        write_json(task / "work" / "automation-manifest.json", {"tests": [
            {"instance_id": "test_filter[a]", "case": "TC-1", "covers": ["TC-1"], "test": "test_filter",
             "file": "tests/test_filter.py", "status": "green"}], "unresolved": []})
        write_json(task / "work" / "run-blocks" / "one.json", {
            "block_id": "b1", "attempt_id": "a1", "attempt_started_at": "2026-09-24T00:01:00+00:00",
            "execution_status": "passed",
            "results": [{"instance_id": "test_filter[a]", "case": "TC-1", "status": "passed"}]})
        write_json(task / "work" / "run-blocks" / "two.json", {
            "block_id": "b2", "attempt_id": "a2", "attempt_started_at": "2026-09-24T00:02:00+00:00",
            "execution_status": "not_executed",
            "results": [{"instance_id": "test_filter", "status": "partial", "reason": "report row missing"}]})
        F.refresh(task)
        report = C.load_json(task / "work" / "run-report.json")
        check_eq("F7: a green story is `passed` beside a bare-name debris row",
                 report["execution_status"], "passed")
        findings = [f for f in report.get("factory_findings") or [] if f.get("code") == "INSTANCE_MANIFEST_JOIN_FAILED"]
        check_eq("F7: the debris row is still the factory's finding", [f["entity"] for f in findings], ["test_filter"])
        check_eq("F7: and still a current row, counted as partial",
                 report.get("current_totals"), {"partial": 1, "passed": 1})
        write_json(task / "work" / "run-blocks" / "three.json", {
            "block_id": "b3", "attempt_id": "a3", "attempt_started_at": "2026-09-24T00:03:00+00:00",
            "execution_status": "failed",
            "results": [{"instance_id": "test_filter[a]", "case": "TC-1", "status": "failed"}]})
        check_eq("F7: a real failure of a joined instance still fails the story",
                 F.refresh(task)["execution_status"], "failed")
        for name in ("one.json", "three.json"):
            (task / "work" / "run-blocks" / name).unlink()
        check_eq("F7: debris alone proves nothing — not_executed",
                 F.refresh(task)["execution_status"], "not_executed")
    finally:
        cleanup(root)


# --- F8: an artifact that exists is changed where it changed ---------------------------------


def blocked_in_session(check_fn, path: Path, session: str) -> str:
    """What a guard check says about a Write over `path` from a named session."""
    import io
    import contextlib
    event = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    if session:
        event["session_id"] = session
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            check_fn(event, {})
    except SystemExit:
        pass
    return captured.getvalue()


def blocked(check_fn, path: Path) -> str:
    """The refusal a guard check prints for a Write over `path`, or '' when it lets it through.

    No session id: the guard cannot count attempts, so its rule stands on every call — which is
    what the rest of this section is about."""
    return blocked_in_session(check_fn, path, "")


def f8_an_existing_artifact_is_not_written_whole():
    """Measured on this story: 59 whole rewrites of test-plan.json, 525,812 tokens of arguments.

    The first write of each file is how it comes into being and is never refused; after that the
    refusal names the point edit. The registry drives which artifacts these are, so a new artifact
    needs no change here — only its own `rewrite` field."""
    import guard_pre_tool as G  # noqa: PLC0415 - the guard is the subject of this section
    root = temp_project()
    try:
        work = root / "qa-factory" / "artifacts" / "QA-1" / "work"
        work.mkdir(parents=True)
        plan_json, plan_md = work / "test-plan.json", work / "test-plan.md"
        register = work / "requirements-register.md"

        check_eq("F8: the first write of the plan is not refused",
                 blocked(G.plan_write_check, plan_json), "")
        write_json(plan_json, {"rows": [{"id": "TS-1", "disposition": "automate"}]})
        check_in("F8: a plan that holds rows refuses a whole rewrite", "plan_row.py",
                 blocked(G.plan_write_check, plan_json))
        check_in("F8: and the refusal names appending a row", "--add-row",
                 blocked(G.plan_write_check, plan_json))
        check_eq("F8: a plan with no rows yet is still the role's to write",
                 blocked(G.plan_write_check, work / "other-plan.json"), "")

        check_eq("F8: test-plan.md is not refused before it exists",
                 blocked(G.plan_write_check, plan_md), "")
        plan_md.write_text("| TS-1 | smoke |\n", encoding="utf-8")
        check_in("F8: once it exists, its lines are edited", "Edit",
                 blocked(G.plan_write_check, plan_md))

        # The refusal never yields to repetition: a role that cannot satisfy it writes that in its
        # findings and halts, and every role carries Edit so the case of "nothing to change it
        # with" is closed by the role files, not by a hole in the guard.
        session = "held-" + hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
        for attempt in range(1, 5):
            said = blocked_in_session(G.plan_write_check, plan_json, session)
            check_in(f"F8: attempt {attempt} over a plan with rows is still refused",
                     "PRE-TOOL GUARD", said)
        check_in("F8: and every refusal says where an impossible one goes", "in your findings",
                 blocked_in_session(G.plan_write_check, plan_json, session))
        check_eq("F8: no allowance is recorded, because none is given",
                 (work.parent / "state" / "guard-allowances.jsonl").is_file(), False)
        for role in sorted(p.stem for p in (SCRIPTS.parent / "agents").glob("qa-*.md")):
            tools = (SCRIPTS.parent / "agents" / f"{role}.md").read_text(encoding="utf-8")
            line = [row for row in tools.splitlines() if row.startswith("tools:")]
            check("F8: %s carries a point editor" % role, bool(line) and "Edit" in line[0],
                  line[0] if line else "no tools: line")

        check_eq("F8: an artifact with no rewrite rule is left alone",
                 blocked(G.artifact_rewrite_check, work / "scratch.md"), "")
        register.write_text("| R-1 | configurable |\n", encoding="utf-8")
        said = blocked(G.artifact_rewrite_check, register)
        check_in("F8: a registered artifact that exists refuses a whole rewrite", "Edit", said)
        check_in("F8: and the refusal carries what the rewrites cost", "22,684", said)
    finally:
        cleanup(root)


if __name__ == "__main__":
    f1_an_impossible_case_may_list_no_instance()
    f1_a_handed_case_may_list_no_instance_and_others_keep_the_rule()
    f2_the_plan_is_read_from_work()
    f3_a_consolidated_test_covers_its_cases()
    f5_s6_does_not_close_over_an_undispatched_manual_half()
    f5_a_person_may_close_s6_without_the_manual_half()
    f6_a_fresh_story_initializes_new_without_a_phantom()
    f6_a_real_legacy_pipeline_still_imports()
    f7_unjoined_rows_do_not_vote()
    f8_an_existing_artifact_is_not_written_whole()
    finish("TP1-13797 fixes (F1 FB-10, F2, F3, F5, F6, F7 FB-12, F8)")
