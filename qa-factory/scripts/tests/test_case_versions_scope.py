#!/usr/bin/env python3
"""HF8-6 (S3.05): the pin step records the approved scope, and the refusal before it says so.

Run 12586 (29.10.2026): S4 on the skill path had no driver, the controller refused the case critic because the approved
scope was empty, and the conductor spent six calls and two refusals rebuilding the driver's `revise_plan` by hand.
`case_versions.py --all` now records the scope itself through `case_versions.scope_request` (the one builder the driver
calls too). Real controller, real store, real CLI subprocess where the CLI is the thing under test.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_mode,  # noqa: E402
                     run_script, temp_project)

sys.path.insert(0, str(SCRIPTS))
import case_versions as V  # noqa: E402
import test_controller_rework_scope as RS  # noqa: E402
import test_controller_state as BASE  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import StateConflict  # noqa: E402

TICKET = "QA-15"
SINGLE = {1: ["s"], 2: ["s"], 3: ["s"], 4: ["s"]}       # four cases, one area each: the index keys them bare


def cli_story(init=True, prefix="qa-scope-pin-"):
    """A project with an (optionally initialized) controller story under it: `(project, task, controller)`."""
    root = temp_project(prefix)
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": TICKET, "stages": {}, "gates": {}}), encoding="utf-8")
    c = Controller(task)
    if init:
        c.apply("initialize", {"scope": [], "source_revision": "src-1", "known_paths": {"root": str(task)},
                               "idempotency_key": "init"})
    return root, task, c


def write_case(task, number, area="", body=None, ident=None):
    # the bytes differ by area: two areas with identical bytes share one content-addressed version (not what is tested here)
    body = body if body is not None else f"body of {area or 'the root'}"
    folder = task / "work" / "test-cases" / area if area else task / "work" / "test-cases"
    folder.mkdir(parents=True, exist_ok=True)
    cid = ident or f"TC-{number:03d}"
    path = folder / f"TC-{number:03d}.md"
    path.write_text(f"---\nid: {cid}\ntitle: case {number}\nstatus: Draft\nplan_row: TS-{number}\ntask: {TICKET}\n---\n"
                    f"Plan row: TS-{number}\n{body}\n", encoding="utf-8")
    return path


def cli(root, task, *flags):
    """`(exit code, the answer's JSON, the process)` of `case_versions.py --task-root <task> <flags>`."""
    done = run_script("case_versions.py", "--task-root", task, *flags, cwd=root)
    lines = [line for line in done.stdout.strip().splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else {}
    except ValueError:
        data = {}
    return done.returncode, data, done


def revise_events(c):
    return [e for e in c.store.read() if e["type"] == "revise_plan"]


def designed_story(count=2, designer_done=True):
    """S0..S3 accepted, the S4 designer dispatched (accepted unless `designer_done` is False), `count` case files on disk, the
    scope empty: the state the skill path is in when the designer returns."""
    root, task, c = cli_story()
    BASE.seed_plan(task, [RS.plan_row(n, "automate") for n in range(1, count + 1)])
    (task / "state" / "story-case-links.json").unlink()       # seed_plan stubs a pin of `TC-1`; the designer's files are the pins
    for stage in ("S0", "S1", "S2", "S3", "S4"):
        role = "qa-case-designer" if stage == "S4" else "qa-worker"
        c.apply("dispatch", {"id": f"d{stage}", "stage": stage, "role": role, "scope": [], "input_hash": stage,
                             "budget": {}, "known_paths": {}, "idempotency_key": f"dispatch-{stage}"})
        if stage == "S4" and not designer_done:
            break
        BASE.record_stage_acceptance(task, stage, f"d{stage}" if stage == "S4" else "")     # E-B11: S2/S3 close over a worker stub, S4 reviews the designer
        c.apply("accept", {"id": f"d{stage}", "status": "accepted", "stage_complete": role != "qa-case-designer",
                           "evidence_refs": [BASE.evidence_ref(task, f"{stage}.txt", stage)], "idempotency_key": f"accept-{stage}"})
    for n in range(1, count + 1):
        write_case(task, n)
    return root, task, c


def approve(root, c):
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
                "source_revision": "src-1", "scope": list(c.state()["scope"]),
                "input_revision": c.state().get("plan_revision") or "sha256:plan-1",
                "idempotency_key": "gate-a"}
    c.apply("decision", BASE.bind_gate_a(root, decision))


def written_by_us(c, scope, tag="0123456789ab"):
    """A `revise_plan` carrying the whole key shape `scope_request` writes (`revise_plan:<ticket>:<revision>:<12 hex>`)."""
    c.apply("revise_plan", {"scope": scope, "plan_revision": "sha256:plan-1", "reason": "S4: pinned cases",
                            "idempotency_key": f"revise_plan:{c._ticket()}:{c.state()['revision']}:{tag}"})


def by_hand(c, scope, tag="by-hand"):
    c.apply("revise_plan", {"scope": scope, "plan_revision": "sha256:plan-1", "reason": "the person dropped a case",
                            "idempotency_key": tag})


def scope_story(areas=SINGLE, gate=False, scope=None):
    """The keyed story of the scope tests with the last `revise_plan` written the way this code writes it, and gate A
    approved on request."""
    root, parent, c = RS.keyed_story(areas, gate=False)
    written_by_us(c, scope or list(c.state()["scope"]))
    if gate:
        approve(root, c)
    return root, parent, c


def statuses(c):
    return [d["status"] for d in c.state()["decisions"].values()]


def refusal_text(c, stage, scope, state=None, role="qa-case-critic"):
    """'' when the dispatch passes the controller's checks, the refusal text otherwise."""
    request = {"id": "w", "stage": stage, "role": role, "scope": scope, "input_hash": "h", "budget": {}, "known_paths": {}}
    try:
        with run_mode("driver"):
            c.validate("dispatch", request, state or c.state())
    except (ValueError, StateConflict) as exc:
        return str(exc)
    return ""


# --- the skill path: pin, then the critic starts (T1, T2, T3, T4, T5) -----------------------------------------------

def t1_skill_path_critic_starts_without_a_hand_made_revise_plan():
    root, task, c = designed_story(2)
    try:
        before = refusal_text(c, "S4", ["TC-001"])
        check_in("T1: before the pin the critic is refused in the new words (no gate A decision was ever asked)",
                 "the review scope does not hold yet", before)
        check_in("T1: ... and the refusal names the door that pins and records", "case_versions.py --task-root", before)
        code, answer, _ = cli(root, task, "--all")
        check_eq("T1: `--all` exits 0", code, 0)
        check_eq("T1: the answer says the scope was recorded", answer.get("scope"), "recorded")
        check_eq("T1: pinned comes first in the answer (test_case_gates reads it)", list(answer)[:2], ["pinned", "links"])
        check_eq("T1: the scope IS the pinned cases", c.state()["scope"], ["TC-001", "TC-002"])
        check_eq("T1: one revise_plan event, written by the pin step", len(revise_events(c)), 1)
        packet = c.prepare({"stage": "S4", "role": "qa-case-critic", "id": "S4-qa-case-critic-1", "scope": ["TC-001"]})
        c.apply("dispatch", packet["dispatch_request"])
        check_eq("T1: the same prepare + apply story_step.start makes starts the critic with no hand-made revise_plan",
                 c.state()["dispatches"]["S4-qa-case-critic-1"]["status"], "running")
    finally:
        cleanup(root)


def t2_t3_repeat_and_growth():
    root, task, c = designed_story(2)
    try:
        cli(root, task, "--all")
        events = len(c.store.read())
        _, again, _ = cli(root, task, "--all")
        check_eq("T2 (K4): the same set again is `unchanged`", again.get("scope"), "unchanged")
        check_eq("T2: ... and writes no event, so the revision does not grow", len(c.store.read()), events)
        write_case(task, 3)
        _, grown, _ = cli(root, task, "--all")
        check_eq("T3: a case the designer added before gate A is recorded", grown.get("scope"), "recorded")
        check_eq("T3: the scope follows the pins", c.state()["scope"], ["TC-001", "TC-002", "TC-003"])
        check("T3: no gate A existed, so nothing is called stale", "gate_a_stale" not in grown, str(grown))
    finally:
        cleanup(root)


def t4_no_controller_journal():
    root, task, _c = cli_story(init=False)
    try:
        write_case(task, 1)
        code, answer, done = cli(root, task, "--all")
        check_eq("T4 (K1): a story with no journal pins and exits 0", (code, answer.get("pinned")), (0, 1))
        check_eq("T4: and says the scope was not recorded", answer.get("scope"), "not_recorded")
        check_in("T4: ... because there is no controller journal", "no controller journal", answer.get("scope_note", ""))
        check("T4: no event file was created by the attempt", not any((task / "state").glob("events*")),
              str(list((task / "state").iterdir())))
        check("T4: the pin itself stands", (task / "state" / "story-case-links.json").is_file())
    finally:
        cleanup(root)


def t5_a_running_dispatch_and_a_lease_leave_the_pin_and_say_so():
    root, task, c = designed_story(2, designer_done=False)
    try:
        code, answer, _ = cli(root, task, "--all")
        check_eq("T5 (K8): a running dispatch: exit 0, the pin stands", (code, answer.get("pinned")), (0, 2))
        check_eq("T5: the scope is not recorded", answer.get("scope"), "not_recorded")
        check_in("T5: the note carries the controller's own words", "checkpoint active work", answer.get("scope_note", ""))
        check_eq("T5: the answer names the pins the scope is behind by", answer.get("scope_behind"), ["TC-001", "TC-002"])
        check_eq("T5: the controller's scope was not touched", c.state()["scope"], [])
    finally:
        cleanup(root)
    root, parent, c = scope_story()
    original = Controller.state
    try:
        RS.pin_case_files(root, {**SINGLE, 5: ["s"]})

        def with_lease(self):
            state = original(self)
            state["leases"] = {"orchestrator": {"owner_session_id": "another-session"}}
            return state
        Controller.state = with_lease
        answer = V.record_scope(root)
    finally:
        Controller.state = original
        cleanup(parent)
    check_eq("T5 (K20): under an orchestrator lease the scope is not recorded", answer.get("scope"), "not_recorded")
    check_in("T5: the note has the controller's words", "stale or missing orchestrator lease", answer.get("scope_note", ""))
    check_in("T5: ... and says the lease is the reason", "cannot be recorded under a lease", answer.get("scope_note", ""))
    check_in("T5 (C-2): ... and the door of the hand-written request, at the END of the note",
             "cannot be recorded under a lease; a hand-written revise_plan carries the owner_session_id of leases.orchestrator "
             "in state/controller.json", answer.get("scope_note", ""))
    check("T5 (C-2): the door is the last words", answer.get("scope_note", "").endswith("in state/controller.json"),
          answer.get("scope_note", "")[-120:])
    # F1: the event is in the journal when `apply` raises a committed-event error: recorded, the stale gate named, no `scope_behind`
    from event_store import DerivedViewStale
    root, parent, c = scope_story(gate=True)
    original_apply = Controller.apply
    try:
        RS.pin_case_files(root, {**SINGLE, 5: ["s"]})

        def apply_then_stale(self, operation, request, *args, **kwargs):
            original_apply(self, operation, request, *args, **kwargs)
            raise DerivedViewStale("event committed; dashboard not refreshed; do not repeat")
        Controller.apply = apply_then_stale
        answer = V.record_scope(root)
    finally:
        Controller.apply = original_apply
    try:
        check_eq("T5 (F1): a committed event is `recorded`, never `not_recorded`", answer.get("scope"), "recorded")
        check_eq("T5 (F1): the scope holds the new case and gate A is stale",
                 ("TC-005" in c.state()["scope"], statuses(c), answer.get("gate_a_stale")), (True, ["stale"], True))
        check_in("T5 (F1): the note carries the controller's `do not repeat`", "do not repeat", answer.get("scope_note", ""))
        check_in("T5 (F1): ... and the stale gate", "ask gate A again", answer.get("scope_note", ""))
        check("T5 (F1): no `scope_behind` for a scope that is written", "scope_behind" not in answer, str(answer))
    finally:
        cleanup(parent)


# --- one case respelled, a number that grew an area, a new case at a current gate (T6, T7) --------------------------------

def t6_respelling_never_stales_but_a_grown_number_does():
    # K6: the stored scope names `s/TC-003`, the index keys it bare now: one key per member, the same set
    root, parent, c = scope_story({**SINGLE, 3: ["s", "a"]}, gate=True, scope=["TC-001", "TC-002", "s/TC-003", "TC-004"])
    try:
        check_eq("T6 setup: the stored scope is the respelled one", c.state()["scope"], ["TC-001", "TC-002", "TC-004", "s/TC-003"])
        RS.pin_case_files(root, SINGLE)
        events = len(revise_events(c))
        answer = V.record_scope(root)
        check_eq("T6 (K6): one case respelled at a current gate is `unchanged`", answer.get("scope"), "unchanged")
        check_eq("T6: gate A stays approved and no event is written", (statuses(c), len(revise_events(c))), (["approved"], events))
    finally:
        cleanup(parent)
    # K6a: the same without gate A: the spelling is brought to the index's keys
    root, parent, c = scope_story({**SINGLE, 3: ["s", "a"]}, gate=False, scope=["TC-001", "TC-002", "s/TC-003", "TC-004"])
    try:
        RS.pin_case_files(root, SINGLE)
        answer = V.record_scope(root)
        check_eq("T6 (K6a): with no gate A the spelling is recorded", answer.get("scope"), "recorded")
        check_eq("T6: in the index's keys", c.state()["scope"], ["TC-001", "TC-002", "TC-003", "TC-004"])
        check("T6: and nothing is stale", "gate_a_stale" not in answer, str(answer))
    finally:
        cleanup(parent)
    # K6b: the stored bare `TC-003` was approved with ONE area; a second area appears: a new case, not a respelling
    root, parent, c = scope_story({**SINGLE, 3: ["a"]}, gate=True)
    try:
        check_eq("T6 setup: approved once, the number held by one area", (statuses(c), "TC-003" in c.state()["scope"]), (["approved"], True))
        RS.pin_case_files(root, {**SINGLE, 3: ["a", "b"]})
        answer = V.record_scope(root)
        check_eq("T6 (K6b): the bare member that became two keys is recorded", answer.get("scope"), "recorded")
        check_eq("T6: gate A is stale, and the answer says so", (statuses(c), answer.get("gate_a_stale")), (["stale"], True))
        note = answer.get("scope_note", "")
        check("T6: the note names the member and both keys",
              "TC-003 now names a/TC-003, b/TC-003" in note and "ask gate A again" in note, note)
        check_eq("T6: the scope holds both keys", [k for k in c.state()["scope"] if "TC-003" in k], ["a/TC-003", "b/TC-003"])
        check_in("T6 (t-436): BOTH keys of the grown number are named new (a bare member that became two keys is wholly new)",
                 "these new cases: a/TC-003, b/TC-003;", note)
    finally:
        cleanup(parent)
    # the same stored scope read before it is written: the plan names both keys as new and the member as multi
    root, parent, c = scope_story({**SINGLE, 3: ["a"]}, gate=True)
    try:
        RS.pin_case_files(root, {**SINGLE, 3: ["a", "b"]})
        plan = V._scope_plan(root, c)
        check_eq("T6 (t-436): the plan names both keys of the grown number as new, none as behind",
                 (plan["new"], plan["behind"], plan["multi"]),
                 (["a/TC-003", "b/TC-003"], [], [("TC-003", ["a/TC-003", "b/TC-003"])]))
        check_eq("T6 (t-436): and writes a request, never `unchanged`", plan["request"] is not None, True)
    finally:
        cleanup(parent)


def t6b_a_bare_member_beside_its_own_keys_is_not_a_respelling():
    """t-442 (canon part D). K6 returns `unchanged` only when EVERY stored member names exactly one key and those keys are the
    pinned set. Here the keys happen to be the same set (`a/TC-003`, `b/TC-003` are both stored by their keys) but one member, the
    bare `TC-003`, names TWO: the stored scope is not one case respelled, so the request is written and the plan says `multi`.
    KILLS: the K6 clause without "one key per member" (`len(found) == 1`)."""
    stored = ["TC-001", "TC-002", "TC-004", "a/TC-003", "b/TC-003", "TC-003"]
    root, parent, c = scope_story({**SINGLE, 3: ["a", "b"]}, gate=True, scope=["TC-001", "TC-002", "TC-004", "a/TC-003", "b/TC-003"])
    try:
        # `revise_plan` normalises what it writes, so a scope with the bare member beside its keys (a hand-written or an older
        # journal) is put in front of the plan as the STATE reads it: the same state, its `scope` replaced
        real_state = c.state
        c.state = lambda *args, **kwargs: dict(real_state(*args, **kwargs), scope=list(stored))
        check_eq("T6b setup: the stored scope holds the bare member beside both keys of its number",
                 [m for m in c.state()["scope"] if "TC-003" in m], ["a/TC-003", "b/TC-003", "TC-003"])
        check_eq("T6b setup: gate A is approved", statuses(c), ["approved"])
        plan = V._scope_plan(root, c)
        check_eq("T6b the plan: nothing behind, nothing new (the keys are all there), the bare member is named multi",
                 (plan["behind"], plan["new"], plan["multi"]), ([], [], [("TC-003", ["a/TC-003", "b/TC-003"])]))
        check_eq("T6b ... and it is NOT `unchanged`: a request is written for the scope", plan["request"] is not None, True)
        check_eq("T6b ... the request carries the pinned cases, each once (the bare member is not repeated beside its keys)",
                 sorted(plan["request"]["scope"]) if plan["request"] else None, ["TC-001", "TC-002", "TC-003", "TC-004"])
    finally:
        cleanup(parent)
    # control (K6): the same stored scope WITHOUT the bare member is the set respelled by its keys only: nothing to write
    root, parent, c = scope_story({**SINGLE, 3: ["a", "b"]}, gate=True, scope=["TC-001", "TC-002", "TC-004", "a/TC-003", "b/TC-003"])
    try:
        check_eq("T6b control: the same scope without the bare member writes nothing", V._scope_plan(root, c)["request"], None)
    finally:
        cleanup(parent)


def t7_new_case_at_a_current_gate_is_named_and_changed_bytes_are_not_silent():
    root, parent, c = scope_story(gate=True)
    try:
        RS.pin_case_files(root, {**SINGLE, 5: ["s"]})
        answer = V.record_scope(root)
        check_eq("T7 (K7): a new case at a current gate is recorded", answer.get("scope"), "recorded")
        check_eq("T7: the approval is stale and the answer flags it", (statuses(c), answer.get("gate_a_stale")), (["stale"], True))
        check_in("T7: the note names the new case and what to do", "these new cases: TC-005; ask gate A again", answer.get("scope_note", ""))
    finally:
        cleanup(parent)
    root, parent, c = scope_story(gate=True)
    try:
        answer = V.record_scope(root, changed=["TC-001"])
        check_eq("T7 (K5, negative control): changed bytes of an approved case leave the scope `unchanged`",
                 (answer.get("scope"), statuses(c)), ("unchanged", ["approved"]))
        check_eq("T7: ... but the answer names the case", answer.get("cases_changed"), ["TC-001"])
        check_in("T7: ... in words", "the bytes of these approved cases changed", answer.get("scope_note", ""))
        check_eq("T7: with no change named there is no such field", "cases_changed" in V.record_scope(root), False)
    finally:
        cleanup(parent)
    # K5, the other side of the condition: the bytes moved but gate A is NOT current (never approved): there is no approval
    # to be silent over, so the answer carries no `cases_changed` and no note
    root, parent, c = scope_story(gate=False)
    try:
        answer = V.record_scope(root, changed=["TC-001"])
        check_eq("T7 (K5, t-436): changed bytes with no current gate A: `unchanged`, no field, no note",
                 (answer.get("scope"), "cases_changed" in answer, "scope_note" in answer), ("unchanged", False, False))
    finally:
        cleanup(parent)


def t7b_cli_compares_the_versions_around_the_pin():
    """`main` in process with gate A reported current (a real approval needs the whole rehearsal): the subprocess cannot be
    patched, and the comparison of the versions before and after `pin_batch` is `main`'s own."""
    import contextlib
    import io
    import os
    root, task, c = designed_story(2)
    original, cwd, project = Controller._current_gate_a, os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR")

    def run_main():
        out, argv = io.StringIO(), sys.argv
        sys.argv = ["case_versions.py", "--task-root", str(task), "--all"]
        try:
            with contextlib.redirect_stdout(out):
                V.main()
        finally:
            sys.argv = argv
        return json.loads(out.getvalue().strip().splitlines()[-1])
    try:
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        os.chdir(root)
        run_main()
        Controller._current_gate_a = lambda self, state: {"id": "gate-a"}
        write_case(task, 1, body="the designer rewrote the steps")
        answer = run_main()
        check_eq("T7b (K5): main sees the bytes move: `unchanged` and the case named",
                 (answer.get("scope"), answer.get("cases_changed")), ("unchanged", ["TC-001"]))
        write_case(task, 3)
        answer = run_main()
        check_eq("T7b: a third case at a current gate: recorded and flagged stale",
                 (answer.get("scope"), answer.get("gate_a_stale"), "cases_changed" in answer), ("recorded", True, False))
    finally:
        Controller._current_gate_a = original
        os.chdir(cwd)
        if project is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = project
        cleanup(root)


def t8_an_index_that_cannot_be_built_is_the_controllers_refusal_in_the_note():
    root, parent, c = scope_story()
    original = Controller._scope_membership
    try:
        RS.pin_case_files(root, {**SINGLE, 5: ["s"]})

        def broken(self, members, strict=False):
            raise ValueError("index boom")
        Controller._scope_membership = broken
        answer = V.record_scope(root)         # in process: a patch is invisible to a subprocess
    finally:
        Controller._scope_membership = original
    try:
        check_eq("T8 (K9): an unbuildable index is not equality: not recorded", answer.get("scope"), "not_recorded")
        check_in("T8: the note is the controller's refusal with its door", "the case index cannot be built", answer.get("scope_note", ""))
        check_eq("T8: the scope was not touched", len(c.state()["scope"]), 4)
    finally:
        cleanup(parent)


def t9_one_number_in_two_areas_records_both_keys():
    root, parent, c = RS.keyed_story(SINGLE, gate=False)
    try:
        RS.pin_case_files(root, RS.AREAS)
        answer = V.record_scope(root)
        check_eq("T9: a number two areas hold: recorded", answer.get("scope"), "recorded")
        check_eq("T9: both of its keys are in the scope", c.state()["scope"], RS.APPROVED_KEYS)
    finally:
        cleanup(parent)


# --- the CLI's own edges (T10, T14) ----------------------------------------------------------------------------------

def t10_scope_is_written_over_a_whole_pin_only_and_only_by_all():
    root, task, c = cli_story()
    try:
        write_case(task, 1, "x")
        write_case(task, 2, "y")
        only_x = task / "work" / "test-cases" / "x"
        code, answer, _ = cli(root, task, "--all", "--cases-dir", only_x)
        check_eq("T10 (K10): `--all` over a narrowed walk pins and exits 0", (code, answer.get("pinned")), (0, 1))
        check_eq("T10: but a story with an unpinned case has no scope written", (answer.get("scope"), c.state()["scope"]), ("not_recorded", []))
        check_in("T10: the note names the case left out", "y/TC-002", answer.get("scope_note", ""))
        for name, flags in (("--cases-dir", ["--cases-dir", only_x]), ("--case-file", ["--case-file", only_x / "TC-001.md"]),
                            ("--verify", ["--verify"])):
            _, answer, _ = cli(root, task, *flags)
            check(f"T10 (K11): {name} alone carries no scope field", "scope" not in answer, str(answer))
        check_eq("T10: and none of them wrote an event", len(revise_events(c)), 0)
    finally:
        cleanup(root)


def t14_battery():
    root, task, c = cli_story(prefix="qa scope battery ")        # magnitude, nesting, encoding, empty and broken
    try:
        check("T14: the story path holds a space", " " in str(task))
        for n in range(1, 102):
            write_case(task, n, body="step: " + "".join(chr(code) for code in (0x43d, 0x430, 0x436, 0x430, 0x442, 0x44c)) + " " + chr(0x1F600))
        code, answer, _ = cli(root, task, "--all")
        check_eq("T14: 101 cases (magnitude, Cyrillic and an emoji in the bodies): pinned and recorded",
                 (code, answer.get("pinned"), answer.get("scope"), len(c.state()["scope"])), (0, 101, "recorded", 101))
        _, again, _ = cli(root, task, "--all")
        check_eq("T14: the repeat is `unchanged`", again.get("scope"), "unchanged")
    finally:
        cleanup(root)
    root, task, c = cli_story()
    try:
        write_case(task, 1, "speakers")
        write_case(task, 1, "speaker-detail")
        write_case(task, 2, "speakers/live")
        _, answer, _ = cli(root, task, "--all")
        check_eq("T14: areas in sub-folders, one number in two of them: both keys, the nested area too",
                 (answer.get("scope"), c.state()["scope"]),
                 ("recorded", ["TC-002", "speaker-detail/TC-001", "speakers/TC-001"]))
    finally:
        cleanup(root)
    root, task, c = cli_story()
    try:
        code, answer, done = cli(root, task, "--all")
        check_eq("T14 (K2): no case at all: the refusal is exit 1, never a pass (AR-23, AR-28; SC5-12), no event", (code, len(c.store.read())), (1, 1))
        write_case(task, 1, ident="TC-009")
        code, _, done = cli(root, task, "--all")
        check("T14 (K3): a file with a wrong id is refused before any pin or event",
              code != 0 and not (task / "state" / "story-case-links.json").exists() and not revise_events(c), done.stdout + done.stderr)
        (task / "work" / "test-cases" / "TC-001.md").unlink()
        write_case(task, 1)
        (task / "state" / "story-case-links.json").write_text("{not json", encoding="utf-8")
        code, answer, done = cli(root, task, "--all")
        # what is true today: `C.load_json` reads a broken file as `{}`, so the pin REWRITES the links (the history of the
        # old file is lost silently, a finding for F6's file) and the scope is recorded over the fresh pin, with one event
        check_eq("T14: a broken link file is re-pinned and the scope recorded once",
                 (code, answer.get("pinned"), answer.get("scope"), len(revise_events(c))), (0, 1, "recorded", 1))
    finally:
        cleanup(root)


# --- the refusal (T11) -------------------------------------------------------------------------------------------------

def t11_the_refusal():
    root, parent, c = RS.keyed_story(SINGLE, gate=False)
    try:
        members = [f"x/TC-{n:03d}" for n in range(100, 121)]
        at, beyond = refusal_text(c, "S4", members[:20]), refusal_text(c, "S4", members)
        check("T11 (K13): 20 members are all named, no tail", all(m in at for m in members[:20]) and "in all" not in at, at[:200])
        check_in("T11: 21 members: the number of them is named", "(21 in all)", beyond)
        for name, scope in (("K16 a plan row", ["TS-1"]), ("K16a a case that does not exist", ["TC-099"])):
            text = refusal_text(c, "S4", scope)
            check_in(f"T11 ({name}): the new head", "the review scope does not hold yet: " + scope[0], text)
            check_in(f"T11 ({name}): the door, and that a plan row is not a case", "a plan row id is not a case id", text)
            check_in(f"T11 ({name}): and an id with no file is the designer's", "written by the designer first", text)
            check_not_in(f"T11 ({name}): no `expansion`", "expansion", text)
            check_not_in(f"T11 ({name}): no `gate A decision`", "gate A decision", text)
        check_eq("T11: a pinned case passes", refusal_text(c, "S4", ["TC-001"]), "")
        empty = dict(c.state(), scope=[])
        check_in("T11: an empty scope, no decision: the new head too", "the review scope does not hold yet",
                 refusal_text(c, "S4", ["TC-001"], empty))
        old = refusal_text(c, "S3", ["TC-099"], role="qa-worker")
        check_in("T11 (K15): not S4: the old text and its door", "scope expansion requires plan/gate revision", old)
    finally:
        cleanup(parent)
    root, parent, c = scope_story(gate=True)
    try:
        state = c.state()
        check_eq("T11 (K14): with an approved decision the new head is not offered", c._scope_not_recorded({"stage": "S4"}, state), False)
        stale = dict(state, decisions={k: dict(v, status="stale") for k, v in state["decisions"].items()})
        check_in("T11 (K14): a STALE decision is still a decision: the old text", "scope expansion requires plan/gate revision",
                 refusal_text(c, "S4", ["TC-099"], dict(stale, scope=[])))
        check_not_in("T11 (K14): and not the new head", "does not hold yet", refusal_text(c, "S4", ["TC-099"], dict(stale, scope=[])))
    finally:
        cleanup(parent)


# --- the driver and the CLI share one builder (T12) ------------------------------------------------------------------

def t12_twins():
    import io
    import contextlib
    import story_run
    root, parent, c = scope_story()
    sent = []

    def stub_for(story):
        class Stub:
            task_root, task = story, story.name

            def controller_state(self):
                return Controller(story).state()

            def controller(self, operation, *args, input_data=None):
                sent.append((operation, input_data))
                return {}
        return Stub()
    try:
        RS.pin_case_files(root, {n: ["s"] for n in range(1, 13)})
        expected = V.scope_request(root)
        story_run.Driver.revise_plan(stub_for(root))
        check_eq("T12: the driver sends exactly what `scope_request` builds", [(op, data) for op, data in sent], [("revise_plan", expected)])
        check_eq("T12: the reason is the one event 35 of run 12586 carries, word for word",
                 expected["reason"], "S4: 12 cases pinned; the approved scope is the case ids S4 produced")
        check_eq("T12: the key has the shape the hand-narrowing check reads",
                 expected["idempotency_key"].startswith(f"revise_plan:{root.name}:"), True)
        # K-A1 (CX2-17): the key is BYTE FOR BYTE the one built before the controller owned `_resolved_keys`: the revision and
        # twelve hex of the content hash of the KEYS (the index's own, here the bare ids) and the plan revision
        from event_store import content_hash
        state = Controller(root).state()
        check_eq("K-A1: the request's key is revision + hash of the resolved keys, as before",
                 expected["idempotency_key"],
                 f"revise_plan:{root.name}:{state['revision']}:"
                 + content_hash({"scope": [f"TC-{n:03d}" for n in range(1, 13)], "plan_revision": expected["plan_revision"]})[:12])
        asked = []
        original = Controller._resolved_keys
        try:
            Controller._resolved_keys = staticmethod(lambda resolution: asked.append(len(resolution)) or original(resolution))
            V.scope_request(root)
        finally:
            Controller._resolved_keys = staticmethod(original)
        check("K-A1: `_scope_plan` reads the keys of the pins through `Controller._resolved_keys`", len(asked) >= 1, str(asked))
        refused_member = [("TC-001", ["TC-001"], ""), ("TC-099", ["TC-099"], "no such case")]
        check_eq("K-A1 (mutant 16): a refused member names no key, whatever its `found` holds",
                 Controller._resolved_keys(refused_member), ["TC-001"])
    finally:
        cleanup(parent)
    root, parent, c = RS.keyed_story(SINGLE, gate=False)
    del sent[:]
    try:
        by_hand(c, ["TC-001", "TC-002"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            story_run.Driver.revise_plan(stub_for(root))
        check_eq("T12 (F6): a scope narrowed by hand: the driver sends nothing", sent, [])
        check_in("T12 (F6): ... and prints why", "the scope was set by hand and stays; pinned outside it: TC-003, TC-004", out.getvalue())
    finally:
        cleanup(parent)
    # F3: `pin_cases` prints `scope_note` although a stderr line comes after the JSON (`py` joins stdout and stderr)
    printed = io.StringIO()
    calls = []

    class PinStub:
        task_root = root

        def py(self, script, *args, check=False, **kwargs):
            calls.append(args[-1])
            if args[-1] == "--all":
                return 0, json.dumps({"pinned": 2, "scope": "not_recorded", "scope_note": "the note to print"}) \
                    + "\ncontroller: a stderr line that is last"
            return 0, "{}"
    with contextlib.redirect_stdout(printed):
        story_run.Driver.pin_cases(PinStub())
    check_in("T12 (F3): the note is printed with a stderr line after the JSON", "S4: the note to print", printed.getvalue())
    check_eq("T12 (F3): `--verify` still follows", calls[-1], "--verify")
    scripts_text = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in SCRIPTS.glob("*.py")]
    marker = "cases pinned; the approved scope"
    check_eq("T12 (AR-15): the request's reason is built at ONE site in scripts/ (`controller.SCOPE_REASON`, CX2-17 C-4)",
             sorted(p.name for p, text in scripts_text if marker in text), ["controller.py"])
    check_eq("T12 (positive control, same shape): the grep finds a name known to exist once",
             sorted(p.name for p, text in scripts_text if "def scope_request(" in text), ["case_versions.py"])


# --- the phase text (T13) ---------------------------------------------------------------------------------------------

def t13_s4_card():
    text = (PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s4.md").read_text(encoding="utf-8")
    forbidden = ("--operation revise_plan", "--scope <the design-review rows>")

    def stale(body):
        return [s for s in forbidden if s in body]
    check_eq("T13: s4.md names no separate scope step and no row ids as the critic's scope", stale(text), [])
    check_eq("T13 (negative control): the same check on a copy that holds one of them fails", stale(text + "\n" + forbidden[0]), [forbidden[0]])
    for needle in ("gate_a_stale", "scope_behind", "`--all` records"):
        check_in(f"T13: s4.md tells the conductor about {needle}", needle, text)


# --- the scope narrowed by hand (T15) --------------------------------------------------------------------------------

def t15_a_scope_narrowed_by_hand_stays():
    root, parent, c = scope_story()
    try:
        by_hand(c, ["TC-001", "TC-002", "TC-003"])
        events = len(revise_events(c))
        answer = V.record_scope(root)
        check_eq("T15 (K19): `--all` after a person dropped a case does not bring it back", answer.get("scope"), "not_recorded")
        check_eq("T15: the answer names the case outside the scope", answer.get("scope_behind"), ["TC-004"])
        check_in("T15: ... and the note says who set it and the door", "the scope was set by hand and stays; pinned outside it: TC-004; "
                 "to include them use `revise_plan`", answer.get("scope_note", ""))
        check_eq("T15: the scope and the journal are as the person left them",
                 (c.state()["scope"], len(revise_events(c))), (["TC-001", "TC-002", "TC-003"], events))
        notes = []
        check_eq("T15: `scope_request` writes nothing and says why", (V.scope_request(root, notes=notes), len(notes)), (None, 1))
        by_hand(c, ["TC-001", "TC-002", "TC-003", "TC-004"], tag="by-hand-2")
        check_eq("T15: the person brings it back with `revise_plan`; then it is `unchanged`", V.record_scope(root).get("scope"), "unchanged")
    finally:
        cleanup(parent)
    # F2: a hand-written key that starts like ours is still the person's, unless it is the WHOLE form with its own revision
    for name, tag in (("the prefix and a word", "revise_plan:{t}:by-hand"),
                      ("the whole form, a revision that is not the event's", "revise_plan:{t}:99:0123456789ab"),
                      ("the form without the hex tail", "revise_plan:{t}:1")):
        root, parent, c = scope_story()
        try:
            by_hand(c, ["TC-001", "TC-002", "TC-003"], tag=tag.format(t=c._ticket()))
            answer = V.record_scope(root)
            check_eq(f"T15 (F2): a key of {name}: the dropped case stays dropped",
                     (answer.get("scope"), c.state()["scope"]), ("not_recorded", ["TC-001", "TC-002", "TC-003"]))
        finally:
            cleanup(parent)
    # decision 2 of the first round: no `revise_plan` event at all (a scope from `initialize`) is not the person's word
    root, task, c = cli_story(init=False)
    try:
        c.apply("initialize", {"scope": ["TC-001"], "source_revision": "src-1", "known_paths": {"root": str(task)},
                               "idempotency_key": "init"})
        write_case(task, 1, "s")
        write_case(task, 2, "s")
        code, answer, _ = cli(root, task, "--all")
        check_eq("T15: no `revise_plan` event yet: the pins are recorded, not left as a hand-set scope",
                 (code, answer.get("scope"), c.state()["scope"], len(revise_events(c))), (0, "recorded", ["TC-001", "TC-002"], 1))
    finally:
        cleanup(root)


def t16_changed_bytes_on_the_exits_that_used_to_lose_them():
    """F5: `cases_changed` on the `unpinned` exit, and for a link pinned before areas existed."""
    import contextlib
    import io
    import os
    root, task, c = designed_story(2)
    original, cwd, project = Controller._current_gate_a, os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR")

    def run_main(*flags):
        out, argv = io.StringIO(), sys.argv
        sys.argv = ["case_versions.py", "--task-root", str(task), *flags]
        try:
            with contextlib.redirect_stdout(out):
                V.main()
        finally:
            sys.argv = argv
        return json.loads(out.getvalue().strip().splitlines()[-1])
    try:
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        os.chdir(root)
        run_main("--all")
        Controller._current_gate_a = lambda self, state: {"id": "gate-a"}
        # a case pinned as bare `TC-001` moves into an area with new bytes: the new key is `s/TC-001`
        (task / "work" / "test-cases" / "TC-001.md").unlink()
        write_case(task, 1, "s", body="moved into an area and rewritten")
        answer = run_main("--all")
        check_in("T16 (F5): a legacy bare link replaced by an area key still names the case", "s/TC-001", answer.get("cases_changed") or [])
        # `--all --cases-dir X` over a story with a case outside X: not recorded, and the changed case is still named
        write_case(task, 1, "s", body="rewritten again while the walk is narrowed")
        write_case(task, 3, "t", body="a third case nobody pinned")
        answer = run_main("--all", "--cases-dir", str(task / "work" / "test-cases" / "s"))
        check_eq("T16 (F5): the narrowed walk is `not_recorded`", answer.get("scope"), "not_recorded")
        check_in("T16: ... the door is named", "run --all without --cases-dir", answer.get("scope_note", ""))
        check_eq("T16: ... and a changed approved case is not lost on that exit", answer.get("cases_changed"), ["s/TC-001"])
    finally:
        Controller._current_gate_a = original
        os.chdir(cwd)
        if project is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = project
        cleanup(root)


def t17_no_pin_writes_nothing_and_a_refused_member_names_no_key():
    # K2: a story with a controller journal and NO pinned case: an empty scope is never written
    root, task, c = cli_story()
    try:
        plan = V._scope_plan(task, c)
        check_eq("T17 (K2, t-436): no pin: no request, no note, nothing behind or new, gate A not current",
                 (plan["request"], plan["note"], plan["behind"], plan["new"], plan["multi"], plan["gate_current"]),
                 (None, "", [], [], [], False))
        check_eq("T17: `scope_request` over no pin is None", V.scope_request(task, c), None)
        answer = V.record_scope(task)
        check_eq("T17: `record_scope` over no pin is `unchanged` and writes no event", (answer.get("scope"), len(revise_events(c))),
                 ("unchanged", 0))
    finally:
        cleanup(root)
    # the invariant `_scope_plan` leans on when it counts the keys the stored scope holds (`held`): a stored member the pins
    # do not resolve names NO key (`why` set, `found` empty), whatever the member is. A producer that returned keys beside a
    # reason would make the plan call a refused member held.
    root, parent, c = scope_story()
    try:
        rows = c._scope_membership(["TC-001", "TC-099", "not a case", 7, "s/TC-001", "zz/TC-001"])[1]
        refused = [(member, found) for member, found, why in rows if why]
        check_eq("T17 (held, t-436): every refused stored member names no key",
                 refused, [("TC-099", []), ("not a case", []), (7, []), ("zz/TC-001", [])])
        check_eq("T17: and the members that resolve name their keys", [(m, f) for m, f, why in rows if not why],
                 [("TC-001", ["TC-001"]), ("s/TC-001", ["TC-001"])])
    finally:
        cleanup(parent)


TESTS = [t1_skill_path_critic_starts_without_a_hand_made_revise_plan, t2_t3_repeat_and_growth, t4_no_controller_journal,
         t5_a_running_dispatch_and_a_lease_leave_the_pin_and_say_so, t6_respelling_never_stales_but_a_grown_number_does,
         t6b_a_bare_member_beside_its_own_keys_is_not_a_respelling, t7_new_case_at_a_current_gate_is_named_and_changed_bytes_are_not_silent, t7b_cli_compares_the_versions_around_the_pin,
         t8_an_index_that_cannot_be_built_is_the_controllers_refusal_in_the_note, t9_one_number_in_two_areas_records_both_keys,
         t10_scope_is_written_over_a_whole_pin_only_and_only_by_all, t14_battery, t11_the_refusal, t12_twins, t13_s4_card,
         t15_a_scope_narrowed_by_hand_stays, t16_changed_bytes_on_the_exits_that_used_to_lose_them,
         t17_no_pin_writes_nothing_and_a_refused_member_names_no_key]


def main():
    for test in TESTS:
        test()
    finish("test_case_versions_scope")


if __name__ == "__main__":
    main()
