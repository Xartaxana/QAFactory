#!/usr/bin/env python3
"""CX2-17 part C1: ONE reader of the story's name (`Controller._ticket`) and the quality of the scope texts.

Keys: K-T1..K-T5 (the name), K-L1..K-L4 (the list cut), K-I1 (an index that cannot be built), K-E10 (a literal scope member
fails closed on a normalised store). Expectations come from the invariants of the node, not from the output of the code
(FR-58): E20 the empty and the dotted name are unreachable; E21 a live worker is never lost to another spelling of its story's
folder; E21b a record is found by the reader that was given the same `--task`; E23-E25 a cut list names its number; E26 the three
answers of an index that cannot be built; E27 a literal member is refused, not resolved.
"""
import contextlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack  # noqa: E402
import contract  # noqa: E402
import detector_verdict  # noqa: E402
import dispatch_liveness  # noqa: E402
import hooklib  # noqa: E402
from controller import Controller, SCOPE_SHOWN, apply_door  # noqa: E402
import test_controller_rework_scope as RS  # noqa: E402  (keyed_story, refusal)

NAME = "TP2-2406"


@contextlib.contextmanager
def patched(owner, name, value):
    saved = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, saved)


@contextlib.contextmanager
def no_run_mode():
    saved = os.environ.pop("QA_FACTORY_RUN_MODE", None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ["QA_FACTORY_RUN_MODE"] = saved


# --- the fixture: a story under a project, a dispatch running --------------------------------------

def live_story(kind=None):
    """`(project, art, root_spelling, receipt_spelling, controller)`: the story folder NAME under a project, S0 dispatched
    (running). The journal is written through the spelling the Controller is opened on (`event_store` reads a journal only
    under the name it was written with: `task_id` is `root.name`), so a second spelling means a story BORN under it: `kind` is
    one of `spellings`' kinds. (A root given as `.` cannot commit or read a journal at all: `event_store` takes `task_id` from
    `root.name`, empty for `.` - a finding of this node, outside its owns; the keys below hand a `.` controller its state.)"""
    project = temp_project("qa-story-name-")
    art = project / "qa-factory" / "artifacts"
    task = art / NAME
    task.mkdir(parents=True)
    root_name, receipt_name = NAME, NAME
    if kind:
        _, root_name, receipt_name = next(pair for pair in spellings(art, NAME) if pair[0] == kind)
    (task / "pipeline.json").write_text(json.dumps({"ticket": NAME, "stages": {}, "gates": {}, "run_mode": {"mode": "desktop"}}),
                                        encoding="utf-8")
    c = Controller(art / root_name)
    c.apply("initialize", {"scope": [], "source_revision": "src-1", "known_paths": {"root": str(project)}, "idempotency_key": "init"})
    c.apply("dispatch", {"id": "d1", "stage": "S0", "role": "qa-worker", "scope": [], "input_hash": "S0", "budget": {},
                         "known_paths": {}, "idempotency_key": "dispatch-d1"})
    return project, art, root_name, receipt_name, c


def available_kinds():
    """The kinds of second spelling this machine can make (E22: none means the keys that need one report a SKIP)."""
    probe = temp_project("qa-story-name-probe-")
    try:
        (probe / "qa-factory" / "artifacts" / NAME).mkdir(parents=True)
        return [kind for kind, _, _ in spellings(probe / "qa-factory" / "artifacts", NAME)]
    finally:
        cleanup(probe)


def write_receipt(project, task_id, dispatch_id="d1"):
    directory = project / "qa-factory" / "state" / "host-dispatches"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"r-{len(list(directory.glob('*.json')))}.json").write_text(json.dumps(
        {"task_id": task_id, "dispatch_id": dispatch_id, "status": "running", "agent_type": "qa-worker", "bound_at": 1000.0}),
        encoding="utf-8")


def clear_receipts(project):
    for path in (project / "qa-factory" / "state" / "host-dispatches").glob("*.json"):
        path.unlink()


def spellings(art, name):
    """[(kind, folder spelling the Controller is opened on, spelling a receipt carries)]: the same folder under another spelling,
    both ways. A case-blind disk gives the case pair; a link needs the right to make one (E22: otherwise the kind is absent)."""
    pairs, other = [], name.swapcase()
    try:
        if other != name and os.path.samefile(art / other, art / name):
            pairs += [("case, root", other, name), ("case, receipt", name, other)]
    except OSError:
        pass
    try:
        os.symlink(art / name, art / "alias-of-story", target_is_directory=True)
        pairs += [("link, receipt", name, "alias-of-story"), ("link, root", "alias-of-story", name)]
    except (OSError, NotImplementedError):
        pass
    return pairs


def checkpoint(c, state=None):
    return RS.refusal(lambda: c.validate("checkpoint", {"id": "d1", "status": "paused"}, state or c.state()))


VETO = "host worker is still active"
FOREIGN = [{"path": "t.jsonl", "dispatch_id": "zzz", "role": "zzz", "ticket": "ZZZ", "first_at": 1.0, "last_at": 2.0}]


# --- K-T2, K-T3: a root given as `.` --------------------------------------------------------------

def k_t2_t3_a_dot_root_names_its_folder():
    old = os.getcwd()
    project = None
    try:
        project, art, _, _, written = live_story()
        task, state = art / NAME, written.state()
        os.chdir(task)
        c = Controller(Path("."))
        check_eq("K-T2: `_ticket()` of root `.` is the folder's name", c._ticket(), NAME)
        check_in("K-T2: the resume door names the story", f"story_step.py resume --task {NAME} --dispatch-id d1", c._resume_door("d1"))
        with patched(Controller, "state", lambda self: state), patched(Controller, "gate_inputs", lambda self: {}), \
                patched(Controller, "_plan_document", lambda self: {"rows": []}):
            check_eq("K-T2: the gate decision id is `gate<X>-<story>`", c.build_gate_decision("A", "go on")["id"], f"gateA-{NAME}")
        (task / "pipeline.json").unlink()
        check_eq("K-T2: pipeline.json's `ticket` is the folder's name", c._project_pipeline(state).get("ticket"), NAME)
        check_in("K-T2 (apply_door): the door names the story", f"story_step.py start --task {NAME} ", apply_door("dispatch", Path(".")))
        check_in("K-T2: `..` is no name either: the door names the folder it points at",
                 "--task artifacts ", apply_door("dispatch", Path("..")))
        # K-T3: a live receipt, root `.`: the veto stands (before the node `.name` was empty and the veto was lifted silently)
        write_receipt(project, NAME)
        check_in("K-T3: a live receipt of the story vetoes the checkpoint of root `.`", VETO, checkpoint(c, state))
        clear_receipts(project)
        write_receipt(project, "OTHER-1")
        check_not_in("K-T3 control: a receipt of ANOTHER story (dispatch ids repeat) is no veto", VETO, checkpoint(c, state))
    finally:
        os.chdir(old)
        if project is not None:
            cleanup(project)


# --- K-T4: a live worker is never lost to a spelling -------------------------------------------------

def k_t4_a_live_worker_is_never_lost_to_a_spelling():
    kinds = available_kinds()
    for missing, why in (("case, root", "a case-sensitive disk"), ("link, root", "no right to make a symbolic link")):
        if missing not in kinds:
            print(f"SKIP K-T4/K-T5 [{missing.split(',')[0]}]: this machine has {why} (E22): that second spelling cannot be made here")
    with no_run_mode():
        for kind in kinds:
            project, art, root_name, receipt_name, c = live_story(kind)
            try:
                write_receipt(project, receipt_name)
                label = f"K-T4 [{kind}]"
                check_eq(f"{label}: `_ticket()` is the spelling the caller wrote", c._ticket(), root_name)
                check_in(f"{label}: `_story_names` holds the receipt's spelling", receipt_name, c._story_names(project))
                check_in(f"{label}: the checkpoint veto stands", VETO, checkpoint(c))
                with patched(dispatch_liveness, "transcripts", lambda _project: list(FOREIGN)):
                    check_eq(f"{label}: `liveness_fixes` does not close the worker", c.liveness_fixes(now=time.time() + 10000), [])
                dispatch = c.state()["dispatches"]["d1"]
                answer, _ = c.launch_answer(dispatch)
                check_eq(f"{label}: `launch_answer` does not launch a second worker", answer, None)
                check(f"{label}: `_launched_after` sees the receipt", c._launched_after(dispatch, None, {}) is True)
            finally:
                cleanup(project)
    # the controls: the same story with no receipt IS closed and IS offered a launch, and a foreign receipt adds no name
    with no_run_mode():
        project, art, root_name, receipt_name, c = live_story()
        try:
            with patched(dispatch_liveness, "transcripts", lambda _project: list(FOREIGN)):
                closed = [fix["kind"] for fix in c.liveness_fixes(now=time.time() + 10000)]
            check_eq("K-T4 control: with no receipt the dispatch is closed as never started", closed, ["never_started"])
            answer, _ = c.launch_answer(c.state()["dispatches"]["d1"])
            check("K-T4 control: with no receipt a launch is offered", bool(answer) and answer["action"] in ("launch", "wait_start"), str(answer))
            write_receipt(project, "OTHER-1")
            check_eq("K-T4 control: a receipt of another story adds no name", c._story_names(project), [NAME])
        finally:
            cleanup(project)


def k_t4_names_and_the_merge():
    project, art, _, _, c = live_story()
    try:
        for bad in ("", ".", "..", "a/b", "a\\b", "C:x", 5, None, ["x"]):
            write_receipt(project, bad)
        (project / "qa-factory" / "state" / "host-dispatches" / "broken.json").write_text("{not json", encoding="utf-8")
        check_eq("K-T4: a task id that is no path component, and a broken receipt file, add no name", c._story_names(project), [NAME])
        seen = [b.get("task_id") for b in dispatch_liveness.host_bindings(project)]
        check_eq("K-T4: `dispatch_liveness.host_bindings` reads the same receipts as `worker_lifecycle.bindings`", seen,
                 [b.get("task_id") for b in __import__("worker_lifecycle").bindings(project) if isinstance(b, dict)])
        # the merge: ALIVE > UNKNOWN > RETURNED > ABANDONED > NEVER_STARTED, whichever name answers first
        order = ["alive", "unknown", "returned", "abandoned", "never_started"]
        answers = {}

        def fake(_project, ticket, _record, now=None):
            return {"state": answers[ticket], "evidence": [ticket]}
        with patched(dispatch_liveness, "state", fake):
            for senior in range(len(order)):
                for junior in range(senior + 1, len(order)):
                    for first, second in ((senior, junior), (junior, senior)):
                        answers.update({"n1": order[first], "n2": order[second]})
                        got = c._liveness(project, {"id": "d1"}, names=["n1", "n2"])["state"]
                        check_eq(f"K-T4: {order[first]} then {order[second]} answers {order[senior]}", got, order[senior])
            answers.update({"n1": "something-new", "n2": "returned"})
            check_eq("K-T4: a state outside the list ranks as unknown, the side that closes nothing",
                     c._liveness(project, {"id": "d1"}, names=["n2", "n1"])["state"], "something-new")
    finally:
        cleanup(project)


def k_t4_a_receipt_that_cannot_be_judged_removes_no_other():
    """K-T4 (F-2): a receipt that breaks `samefile` (NUL is a ValueError; `*` and a long name are OSError) written BEFORE the real
    spelling adds nothing and never hides the receipts after it; a project whose artifact root cannot be read keeps `_ticket()`."""
    with no_run_mode():
        for kind in (k for k in available_kinds() if k.endswith("receipt")):
            project, art, root_name, receipt_name, c = live_story(kind)
            try:
                for bad in ("A\x00B", "a*b", "x" * 5000, "name."):
                    write_receipt(project, bad)
                write_receipt(project, receipt_name)
                check_in(f"K-T4 (F-2) [{kind}]: the real spelling is a name after four receipts that cannot be judged", receipt_name,
                         c._story_names(project))
                check_in(f"K-T4 (F-2) [{kind}]: so the veto stands", VETO, checkpoint(c))
            finally:
                cleanup(project)
    project, art, _, _, c = live_story()
    try:
        write_receipt(project, "OTHER-1")
        with patched(hooklib, "artifact_root", lambda *a, **k: (_ for _ in ()).throw(AttributeError("a config that is no mapping"))):
            check_eq("K-T4 (F-2): an artifact root that cannot be read leaves the one name, and raises nothing", c._story_names(project), [NAME])
    finally:
        cleanup(project)


# --- K-T5: a record is found by the reader with the same `--task` -------------------------------------

def k_t5_a_record_is_found_by_the_same_task():
    saved = hooklib._PROJECT_ROOT_CACHE
    try:
        for kind in available_kinds():
            project, art, root_name, _, c = live_story(kind)
            try:
                hooklib._PROJECT_ROOT_CACHE = project
                words = f"PERSON: row moved by hand ({kind})"
                with patched(Controller, "_mark_plan_overrides", lambda self, w: ["TS-1"]):
                    c._after_commit("revise_plan", {"reason": words})
                check_in(f"K-T5 [{kind}]: `brief_pack.answers_of(<name as in --task-root>)` finds the record", "TS-1: " + words,
                         brief_pack.answers_of(root_name, project))
            finally:
                cleanup(project)
    finally:
        hooklib._PROJECT_ROOT_CACHE = saved


# --- K-L1..K-L4: the one list cut ----------------------------------------------------------------------

def k_l_the_list_cut_names_its_number():
    listed = Controller._listed
    at, beyond = [f"x/TC-{n:03d}" for n in range(100, 120)], [f"x/TC-{n:03d}" for n in range(100, 121)]
    check_eq("K-L1: 20 members are all named, no tail (E23)", listed(at), ", ".join(at))
    check_eq("K-L1: 21 members: the first 20 and the number, never the 21st", listed(beyond), ", ".join(at) + " (21 in all)")
    check_eq("K-L1: `sep` joins the shown items", listed(beyond, sep="; "), "; ".join(at) + " (21 in all)")
    check_eq("K-L3: an empty list is the empty text (E25)", (listed([]), listed([], sep="; ")), ("", ""))
    check_eq("K-L4: a repeated id is named once and counted once", listed(["a", "a", "b"]), "a, b")
    check_eq("K-L4: `named` keeps its own tail by default", detector_verdict.named(["a", "b", "c"], 2), "a, b and 1 more")
    check_eq("K-L4: `named(where=...)` keeps its place", detector_verdict.named(["a", "b", "c"], 2, where="the list"), "a, b and 1 more (the list)")
    check_eq("K-L4: `named(tail=...)` names the whole count; exactly `limit` is no tail",
             (detector_verdict.named(["a", "b", "c"], 2, tail=" ({n} in all, {k} left)"), detector_verdict.named(["a", "b"], 2, tail=" ({n})")),
             ("a, b (3 in all, 1 left)", "a, b"))
    root, parent, c = RS.keyed_story(gate=False)
    try:
        members = [f"a{n}/TC-001" for n in range(1, SCOPE_SHOWN + 2)]
        text = " ".join(str(t) for _, t in c._revise_scope_problems(members))
        first_areas = "; ".join(f"{m}: pinned in: session-feedback" for m in members[:SCOPE_SHOWN])
        check_in("K-L2: the areas are cut at the limit, separated by `; ` and the number is named (E24)",
                 f"({first_areas} (21 in all))", text)
        check_not_in("K-L2: the 21st area is not listed", f"{members[-1]}: pinned in", text)
        with patched(contract, "case_link_issues", lambda _root: [f"TC-{n}, link broken" for n in range(1, SCOPE_SHOWN + 2)]):
            text = " ".join(str(t) for _, t in c._revise_scope_problems(members))
        issues = "; ".join(f"TC-{n}, link broken" for n in range(1, SCOPE_SHOWN + 1))
        check("K-L2: the broken pins are cut at the limit, `; `-separated, with the number", text.endswith(f"; broken pins: {issues} (21 in all)"), text[-200:])
        text = " ".join(str(t) for _, t in c._revise_scope_problems(["TC-010"]))
        check_not_in("K-L3: no areas, no tail of areas (E25)", "pinned in: ", text)
        check_not_in("K-L3: no issues, no tail of broken pins", "broken pins", text)
    finally:
        cleanup(parent)
    # `_unapproved_text`: stored spellings the index keys differently (21 numbers, each held by two areas), cut with the number too
    many = {n: ["a", "b"] for n in range(1, SCOPE_SHOWN + 2)}
    root, parent, c = RS.keyed_story(areas=many, gate=False)
    try:
        stored = [f"TC-{n:03d}" for n in sorted(many)]
        text = c._unapproved_text([("zz", "x")], stored)
        check_in("K-L2: `_unapproved_text` cuts the spellings with `; ` and names the number", "(21 in all) - record it in that spelling", text)
        check_in("K-L2: its 20th is the last named", "TC-019, which the case index keys as a/TC-019, b/TC-019; TC-020, which the case "
                 "index keys as a/TC-020, b/TC-020 (21 in all)", text)
        check_not_in("K-L2: the 21st is not", "TC-021, which", text)
    finally:
        cleanup(parent)


# --- K-I1: an index that cannot be built (E26) -------------------------------------------------------------

def k_i1_the_three_answers_of_a_missing_index():
    root, parent, c = RS.keyed_story(gate=False)
    try:
        def broken(_root):
            raise ValueError("case identity collision")
        state = c.state()
        with patched(contract, "case_index", broken):
            check_eq("K-I1: `_index_or_none` is None", c._index_or_none(), None)
            refused = RS.refusal(lambda: c._index_or_none(strict=True))
            check_in("K-I1: `strict` raises the error itself", "case identity collision", refused)
            mapping, dispositions, basis = c._case_rows(state)
            check_eq("K-I1: `_case_rows` falls back to the plan's scenarios, never raises", basis, "required_scenarios")
            check_in("K-I1: `_scope_membership(strict=True)` raises", "case identity collision",
                     RS.refusal(lambda: c._scope_membership(["TC-001"], strict=True)))
            ids, resolution = c._scope_membership(["TC-001", "TC-099"])
            check_eq("K-I1: the non-strict answer is literal (a pinned id passes, another is not pinned)",
                     [(m, why) for m, _, why in resolution], [("TC-001", ""), ("TC-099", "not pinned")])
            check_eq("K-I1: the pinned ids are still known", ids, ["TC-001", "TC-002", "TC-003", "TC-004"])
        with patched(contract, "case_index", lambda _root: contract.CaseIndex()):
            check("K-I1: an EMPTY index is an index, not an error", c._index_or_none() is not None)
            ids, resolution = c._scope_membership(["TC-099"], strict=True)
            check_eq("K-I1: an empty index refuses a member nobody pinned by its resolution, it does not raise",
                     [bool(why) for _, _, why in resolution], [True])
    finally:
        cleanup(parent)


# --- K-E10: a literal scope member fails closed on a normalised store ---------------------------------------

def k_e10_a_bare_member_is_refused_and_a_key_is_taken():
    for operation, ok_key in (("semantic_reopen", "reopen"), ("invalidate", "invalidate")):
        root, parent, c = RS.keyed_story()
        try:
            events = len(c.store.read())
            bare = RS.refusal(lambda: c.apply(operation, {"reason": "r", "affected_scope": ["TC-003"], "idempotency_key": "bare"}))
            check_in(f"K-E10 [{operation}]: a bare TC-003 two areas hold is refused, literal and fail-closed (E10, E27)",
                     "affected", bare)
            check_eq(f"K-E10 [{operation}]: and no event was written", len(c.store.read()), events)
            c.apply(operation, {"reason": "r", "affected_scope": ["feedback-api/TC-003"], "idempotency_key": ok_key})
            check_eq(f"K-E10 [{operation}]: the key itself is accepted (an event was written)", len(c.store.read()), events + 1)
            if operation == "semantic_reopen":
                statuses = [d["status"] for d in c.state()["decisions"].values() if d.get("gate") == "A"]
                check_eq("K-E10: the gate A decision holding that key is stale", statuses, ["stale"])
        finally:
            cleanup(parent)


# =====================================================================================================
# CX2-17 part C2: the scope read by every reader (the driver's pins, the manual block), the repeated key, the doors,
# the lease, the words of the code. Expectations come from the invariants of section 8.2 of the spec, not from the output of the code.
# =====================================================================================================

from harness import run_mode, run_script  # noqa: E402
import case_versions as V  # noqa: E402
import story_run  # noqa: E402
import test_controller_state as BASE  # noqa: E402
from controller import MANUAL_BLOCK_CASES, SCOPE_REASON, code_scope_write, manual_done_cases  # noqa: E402
from event_store import IdempotencyKeyReused, StateConflict  # noqa: E402

BLOCK_HEAD = "manual runner block must name"
AREAS6 = {1: ["a"], 2: ["a"], 3: ["a"], 4: ["a"], 5: ["a"], 6: ["a", "b"]}     # TC-006 is held by two areas: bare = two keys
BARE6 = [f"TC-{n:03d}" for n in range(1, 7)]


def six_story():
    """A keyed story whose approved scope is the six cases of AREAS6 (seven keys: `a/TC-006`, `b/TC-006` and five bare)."""
    root, parent, c = RS.keyed_story(gate=False)
    RS.pin_case_files(root, AREAS6)
    c.apply("revise_plan", {"scope": BARE6, "plan_revision": "sha256:plan-6", "reason": "the cases", "idempotency_key": "six"})
    return root, parent, c


def manual_request(scope, manual, name="S6-qa-runner-1", key=None):
    return {"id": name, "stage": "S6", "role": "qa-runner", "scope": scope, "input_hash": "h", "budget": {}, "known_paths": {},
            "execution_kind": "manual", "manual_case_ids": manual, "idempotency_key": key or "m-" + name}


def block_refusal(c, request):
    """The refusal of `apply` for a manual runner block ('' = it passed the block check and met a later one or none). The plan's
    own half membership is out of this key's question (the scope map is), so it is silenced."""
    with patched(Controller, "_half_membership_problems", lambda self, *a: []), run_mode("driver"):
        return RS.refusal(lambda: c.apply("dispatch", request))


def k_p1_the_driver_reads_the_pins_the_controller_reads():
    root, parent, c = RS.keyed_story(gate=False)

    class Stub:
        task_root = root
        pinned_cases = story_run.Driver.pinned_cases
        critic_scope = story_run.Driver.critic_scope

        def controller_state(self):
            return Controller(root).state()
    links = root / "state" / "story-case-links.json"
    try:
        stub = Stub()
        check_eq("K-P1: the pinned story: every case once", stub.pinned_cases(), ["TC-001", "TC-002", "TC-003", "TC-004"])
        for name, body in (("a link with no version", [{"case_id": "TC-001", "version": "cv_1"}, {"case_id": "TC-009"}]),
                           ("an empty version", [{"case_id": "TC-001", "version": "cv_1"}, {"case_id": "TC-009", "version": ""}]),
                           ("no case id, a string, a list", [{"case_id": "TC-001", "version": "cv_1"}, {"version": "v"}, "junk", ["x"]])):
            links.write_text(json.dumps({"links": body}), encoding="utf-8")
            check_eq(f"K-P1 (E30): {name} is not pinned, as the controller counts it", stub.pinned_cases(), ["TC-001"])
            check_eq(f"K-P1: and the controller's own filter says the same ({name})",
                     sorted({str(l["case_id"]) for l in Controller(root)._pinned_links()}), stub.pinned_cases())
            check_not_in(f"K-P1: the critic's scope does not hold it ({name})", "TC-009", " ".join(stub.critic_scope()))
        links.write_text("{not json", encoding="utf-8")
        check_eq("K-P1 (E30): a broken file pins nothing, the critic's scope is empty", (stub.pinned_cases(), stub.critic_scope()), ([], []))
        links.unlink()
        check_eq("K-P1 (E30): no file: nothing pinned", (stub.pinned_cases(), stub.critic_scope()), ([], []))
    finally:
        cleanup(parent)


def k_c7_the_critic_scope_is_one_computation():
    root, parent, c = RS.keyed_story(gate=False)
    try:
        plan = root / "work" / "test-plan.json"
        document = json.loads(plan.read_text(encoding="utf-8"))
        rows = document["rows"] if isinstance(document, dict) else document
        check_eq("K-C7: no design-review row: every pinned case", V.review_scope(root), ["TC-001", "TC-002", "TC-003", "TC-004"])
        next(r for r in rows if r["id"] == "TS-2")["design_review_required"] = True
        plan.write_text(json.dumps(document), encoding="utf-8")
        check_eq("K-C7: one design-review row: the cases of that row only", V.review_scope(root), ["TC-002"])

        class Stub:
            task_root = root
            pinned_cases = story_run.Driver.pinned_cases

            def controller_state(self):
                return Controller(root).state()
        check_eq("K-C7: the driver's critic scope IS that function", story_run.Driver.critic_scope(Stub()), ["TC-002"])
        plan.write_text("{broken", encoding="utf-8")
        check_eq("K-C7: a plan that cannot be read narrows nothing", V.review_scope(root), ["TC-001", "TC-002", "TC-003", "TC-004"])
    finally:
        cleanup(parent)


def k_m_the_manual_block_is_read_by_the_same_map():
    root, parent, c = six_story()
    try:
        scope = list(c.state()["scope"])
        check_eq("K-M setup: the approved scope is seven keys", len(scope), 7)
        text = block_refusal(c, manual_request(["TC-006"], ["TC-006"]))
        check_not_in("K-M1 (E30..): a bare id two areas hold, in a dispatch of that bare id, is inside its scope", BLOCK_HEAD, text)
        text = block_refusal(c, manual_request(BARE6, BARE6[:5], name="S6-qa-runner-2"))
        check_not_in("K-M2 (E32): MANUAL_BLOCK_CASES bare ids of one area each pass", BLOCK_HEAD, text)
        check_eq("K-M2 setup: the limit is 5", MANUAL_BLOCK_CASES, 5)
        text = block_refusal(c, manual_request(BARE6, BARE6[1:], name="S6-qa-runner-3"))
        check_in("K-M2 (E33): five bare ids, one in two areas, are SIX cases: split the block",
                 "it names 6 cases, at most 5: split the block", text)
        check_not_in("K-M2: and not 'not in the dispatch scope'", "not in the dispatch scope", text)
        text = block_refusal(c, manual_request(BARE6, ["TC-099"], name="S6-qa-runner-4"))
        check_in("K-M3 (E34): an id the map cannot resolve stays as written and is refused", "not in the dispatch scope: TC-099", text)
        text = block_refusal(c, manual_request(BARE6, "TC-001", name="S6-qa-runner-5"))
        check_in("K-M (E31): a manual block that is no list is refused in the old words", "manual_case_ids is not a list", text)
        text = block_refusal(c, manual_request(BARE6, [], name="S6-qa-runner-6"))
        check_in("K-M (E31): an empty list is refused in the old words", "it names no case", text)
        mine = ["TC-001", "TC-003"]
        request = manual_request(["TC-001", "TC-003"], mine, name="S6-qa-runner-7")
        block_refusal(c, request)
        check_eq("K-M: the caller's own list is untouched (FR-45)", mine, ["TC-001", "TC-003"])
        # E35 (C-6): a block accepted while the scope was bare carried the bare id; the keys are not its cases
        state = {"dispatches": {"old": {"stage": "S6", "status": "accepted", "execution_kind": "manual", "manual_case_ids": ["TC-003"]}}}
        done = manual_done_cases(state)
        check_eq("K-M4 (E35): the bare id the record carries is what is done", done, {"TC-003"})
        check("K-M4: and the keys it now means are NOT done: they go again (a repeat, never a false 'done')",
              not ({"a/TC-003", "b/TC-003"} & done), str(done))
    finally:
        cleanup(parent)
    # E36: the replay of a committed block after the index moved keeps the door, `manual_case_ids` among the fields
    root, parent, c = RS.keyed_story(gate=False)
    try:
        request = manual_request(["TC-003"], ["TC-003"], name="S6-qa-runner-1", key="seed")
        with patched(Controller, "validate", lambda self, operation, p, state: None):
            c.apply("dispatch", dict(request))
        held = c.state()["dispatches"]["S6-qa-runner-1"]
        check_eq("K-M5 setup: the committed block is written in the keys", held["manual_case_ids"],
                 ["feedback-api/TC-003", "session-feedback/TC-003"])
        RS.pin_case_files(root, {**RS.AREAS, 3: ["feedback-api", "session-feedback", "billing"]})     # a third area holds TC-003
        with run_mode("driver"):
            text = RS.refusal(lambda: c.apply("dispatch", dict(request)))
        check_in("K-M5 (E36): a replay after the index moved is the N-2 refusal", "idempotency key reused with different inputs: "
                 "dispatch S6-qa-runner-1 was committed with scope", text)
        check_in("K-M5: with its door", "--operation revise_plan", text)
        exc = IdempotencyKeyReused("x", key="seed", fields=("manual_case_ids",))
        check_eq("K-M5: the manual block is a field of that answer (the scope differs too, so the committed scope is named)",
                 c._replayed_with_other_scope(IdempotencyKeyReused("x", key="seed", fields=("scope", "manual_case_ids")), "dispatch",
                                              dict(request, scope=["TC-003"]), c.state()), held["scope"])
        check_eq("K-M5: a block-only difference with the same scope is left to the store's own words",
                 c._replayed_with_other_scope(exc, "dispatch", dict(request, scope=held["scope"]), c.state()), None)
    finally:
        cleanup(parent)


def k_m6_the_three_roads_read_the_block_by_one_map():
    """K-M6 (F-1, AR-19): `apply`, `prepare` and `story_step.py start` read a manual block through `Controller._manual_keys`, so a
    bare id that two areas hold is judged against the plan's half (and registered) as every one of its keys on every road."""
    import types
    from unittest import mock
    import manual_evidence
    import story_step
    import runtime_paths
    root, parent, c = RS.keyed_story(gate=False)
    try:
        BASE.seed_plan(root, [RS.plan_row(n, "manual-agent") for n in (1, 2, 3, 4)])     # every case is the manual half's
        RS.pin_case_files(root, RS.AREAS)       # (`seed_plan` clears the case files the index reads)
        state = c.state()
        keys = ["feedback-api/TC-003", "session-feedback/TC-003"]
        check_eq("K-M6: a bare id of two areas is both of its keys", c._manual_keys(["TC-003"], state), keys)
        check_eq("K-M6: an id the map cannot resolve stays as written", c._manual_keys(["TC-099"], state), ["TC-099"])
        check_eq("K-M6 (E31): no list and an empty list are returned as given", (c._manual_keys("TC-003", state), c._manual_keys([], state)),
                 ("TC-003", []))
        premise = c._half_membership_problems("S6", state, ["TC-003"], "manual")
        check("K-M6 premise: the half check judges the BARE spelling literally (it is the reason for the one map)", bool(premise), str(premise))
        check_eq("K-M6: the keys of that id are in the manual half", c._half_membership_problems("S6", state, keys, "manual"), [])
        with patched(runtime_paths, "resolve_runtime", lambda task, project: {"project_root": str(parent), "plugin_root": str(parent)}):
            packet = c.prepare({"stage": "S6", "role": "qa-runner", "execution_kind": "manual", "scope": ["TC-003"],
                                "manual_case_ids": ["TC-003"], "id": "S6-qa-runner-1"})
        check_eq("K-M6: `prepare` carries the block in keys and does not refuse the bare id", packet["dispatch_request"]["manual_case_ids"], keys)
        args = types.SimpleNamespace(task=NAME, stage="S6", role="qa-runner", scope="TC-003", execution_kind="manual", id=None)
        prepared = []

        def fake_prepare(task_root, case):
            prepared.append(case)
            return [], "", ""
        with mock.patch.object(manual_evidence, "prepare_for_block", fake_prepare), \
                mock.patch.object(story_step, "_task_root", lambda task: root):
            block, lines, code = story_step._manual_block_check(args, c, state)
            check_eq("K-M6: `story_step.py start` takes the bare id: the block is its keys, exit 0, no refusal", (block, lines, code), (keys, [], 0))
            check_eq("K-M6: and each case is prepared under its key, as the driver does", prepared, keys)
            legacy = dict(state, plan_contract_mode="legacy")
            check_eq("K-M6 (legacy mode): the written spelling stays", story_step._manual_block_check(args, c, legacy)[0], ["TC-003"])
    finally:
        cleanup(parent)


def k_r_a_hand_written_key_reused():
    root, parent, c = RS.keyed_story(gate=False)
    try:
        def record(scope, key, reason="the cases", **extra):
            return c.apply("revise_plan", dict({"scope": scope, "plan_revision": "sha256:plan-2", "reason": reason,
                                                "idempotency_key": key}, **extra))
        first = record(["TC-001", "TC-002"], "mine")
        events = len(c.store.read())
        again = record(["TC-001", "TC-002"], "mine")
        check_eq("K-R2 (E37): the same request under the same key is the same answer, no refusal and no event",
                 (len(c.store.read()), again == first), (events, True))
        revision = c.state()["revision"]
        text = RS.refusal(lambda: record(["TC-001", "TC-002"], "mine", reason="another reason"))
        check_in("K-R1 (E38): another reason: the second form names the field, not the scope",
                 "idempotency key reused with different reason: the key mine holds another request. A new request takes a key of its "
                 f"own and expected_revision {revision}", text)
        check_not_in("K-R1: and does not claim a scope", "different scope", text)
        record(["TC-001"], "other")        # the state's scope is now [TC-001]; the event of "mine" holds two cases
        revision = c.state()["revision"]
        text = RS.refusal(lambda: record(["TC-003"], "mine"))
        check_in("K-R1 (E38a): another scope: the first form, with the scope the KEY was committed with (not the state's)",
                 "idempotency key reused with a different scope: the key mine was committed with scope [TC-001, TC-002]; this "
                 "request names [feedback-api/TC-003, session-feedback/TC-003]. A new request takes a key of its own and "
                 f"expected_revision {revision}", text)
        before = len(c.store.read())
        record(["TC-003"], "mine-2", expected_revision=revision)
        check_eq("K-R1 (FR-2): the door the refusal names is one the caller can use: a key of its own and the revision pass",
                 (len(c.store.read()), c.state()["scope"]), (before + 1, ["feedback-api/TC-003", "session-feedback/TC-003"]))
        # K-R3 (E39, E40-like): the other refusals pass on untouched
        with patched(Controller, "validate", lambda self, operation, p, state: None):
            c.apply("dispatch", {"id": "run-1", "stage": "S5", "role": "qa-automator", "scope": ["TC-001"], "input_hash": "h",
                                 "budget": {}, "known_paths": {}, "idempotency_key": "d1"})
        other = RS.refusal(lambda: record(["TC-001"], "fresh"))
        check_in("K-R3: a refusal that is not a reused key (a running dispatch) is passed on in its own words",
                 "checkpoint active work before revising scope", other)
        text = RS.refusal(lambda: c.apply("dispatch", {"id": "run-1", "stage": "S5", "role": "qa-automator", "scope": ["TC-002"],
                                                       "input_hash": "h", "budget": {}, "known_paths": {}, "idempotency_key": "d1"}))
        check_in("K-R3 (E39): a reused DISPATCH key keeps the N-2 text, not this branch", "idempotency key reused with different "
                 "inputs: dispatch run-1", text)
        check_not_in("K-R3: and does not say 'holds another request'", "holds another request", text)
    finally:
        cleanup(parent)


def k_d_the_doors_name_both_moves():
    root, parent, c = RS.keyed_story(gate=False)
    try:
        door = c._scope_door([RS.KEYED], ["TC-004"])
        check_in("K-D1 (E40): the door names `--all`, and that it does not write a scope set by hand", "`case_versions.py --all` records "
                 "the pinned ones unless the scope was set by hand; otherwise", door)
        check_in("K-D1: and the move that does, with the pinned ids (the pin of test_controller_rework_scope)",
                 "`--operation revise_plan` (scope = TC-001, TC-002, TC-003, TC-004;", door)
        check_in("K-D1: the own-key refusal sends to the pin step", "recorded at S4 by `case_versions.py --all`",
                 c._own_key_problem([RS.KEYED])[1])
        # E41: an empty scope under a plan with rows: the door names `--all` and the person's word stays
        c.apply("revise_plan", {"scope": [], "plan_revision": "sha256:plan-e", "reason": "nothing yet", "idempotency_key": "empty"})
        state = c.state()
        with run_mode("driver"):
            problems = [text for _, text in c._decision_problems({"id": "g", "gate": "A", "action": "approve", "status": "approved",
                                                                  "authorization_source": "human", "source_revision": "src-1",
                                                                  "scope": [], "input_revision": "sha256:plan-e"}, state)]
        joined = " | ".join(problems)
        check_in("K-D2 (E41): an empty scope: `--all` with the story's root, and the hand-written door too",
                 f"record the reviewed scope with `case_versions.py --task-root {root} --all` (or `--operation revise_plan`)", joined)
        check_in("K-D2: and the person's word (waiver) is still offered", "waiver.py", joined)
        done = run_script("case_versions.py", "--task-root", root, "--all", cwd=parent)
        check("K-D2 (E41): `--all` with no case file answers a refusal, never a trace",
              "Traceback" not in done.stderr + done.stdout and done.returncode != 0, f"{done.returncode} {done.stderr[-200:]}")
    finally:
        cleanup(parent)


def lease_story(owner="sess-1"):
    root, parent, c = RS.keyed_story(gate=False)
    c.apply("handoff", {"owner_session_id": None, "host_capability": "manual_continuation",
                        "expected_revision": c.state()["revision"], "lease": {"owner_session_id": owner, "generation": 1},
                        "idempotency_key": "lease"})
    return root, parent, c


def k_l_the_lease_and_the_hand_written_door():
    root, parent, c = lease_story()
    try:
        base = {"scope": ["TC-001", "TC-002"], "plan_revision": "sha256:plan-2", "reason": "the cases", "idempotency_key": "hand"}
        check_in("K-L5 (E42): no owner in the request: the old refusal", "stale or missing orchestrator lease",
                 RS.refusal(lambda: c.apply("revise_plan", dict(base))))
        check_in("K-L5: a wrong owner: the same refusal", "stale or missing orchestrator lease",
                 RS.refusal(lambda: c.apply("revise_plan", dict(base, owner_session_id="somebody-else"))))
        check_eq("K-L5: nothing was written", c.state()["scope"], ["TC-001", "TC-002", "TC-004", "feedback-api/TC-003", "session-feedback/TC-003"])
        request = dict(base, owner_session_id="sess-1")
        c.apply("revise_plan", request)
        check_eq("K-L6 (E43): the right owner: the scope is written", c.state()["scope"], ["TC-001", "TC-002"])
        check_eq("K-L6: the caller's own request keeps its field (FR-45)", request["owner_session_id"], "sess-1")
        check("K-L6: the field is not a fact of the plan: not in the projection, not in the payload",
              "owner_session_id" not in c.state() and "owner_session_id" not in c.store.read()[-1]["payload"],
              str(sorted(c.state()))[:200])
        events = len(c.store.read())
        c.apply("revise_plan", dict(request))
        check_eq("K-L6: and the same request again is a replay", len(c.store.read()), events)
    finally:
        cleanup(parent)


def k_l7_the_driver_under_its_own_lease():
    root, parent, c = lease_story("driver:T:5")
    try:
        revision = c.state()["revision"]      # the last record of the scope is the code's own (a scope set by hand would stay)
        c.apply("revise_plan", {"scope": RS.ALL_BARE, "plan_revision": "sha256:plan-1", "reason": "S4: pinned cases",
                                "expected_revision": revision, "owner_session_id": "driver:T:5",
                                "idempotency_key": f"revise_plan:{c._ticket()}:{revision}:0123456789ab"})
        RS.pin_case_files(root, {**RS.AREAS, 5: ["session-feedback"]})

        class Stub:
            task_root, task = root, root.name

            def controller_state(self):
                return Controller(root).state()

            def controller(self, operation, *args, input_data=None):
                try:
                    return {"event": Controller(root).apply(operation, dict(input_data))}
                except (ValueError, StateConflict) as exc:
                    raise story_run.Refusal(f"controller {operation}:\n{exc}")
        story_run.Driver.revise_plan(Stub())
        check_in("K-L7 (E43a): after a rollover the driver records the pinned cases under its own lease", "TC-005", " ".join(c.state()["scope"]))
    finally:
        cleanup(parent)


def k_w_the_words_of_the_code_are_not_the_words_of_a_person():
    # the one recogniser, on its inputs (E46a: both match -> the code's; E46: the key alone -> a person's)
    reason = SCOPE_REASON.format(n=4)
    key = "revise_plan:T-1:7:0123456789ab"
    for name, args, want in (("key and reason of the code", (key, 7, reason, "T-1"), True),
                             ("any whole n", (key, 7, SCOPE_REASON.format(n=120), "T-1"), True),
                             ("the key of the code, a person's reason", (key, 7, "PERSON: TS-2 by hand", "T-1"), False),
                             ("the reason with a tail", (key, 7, reason + " and more", "T-1"), False),
                             ("a revision that is not the event's", (key, 8, reason, "T-1"), False),
                             ("another story's key", (key, 7, reason, "T-2"), False),
                             ("n that is no number", (key, 7, SCOPE_REASON.format(n="x"), "T-1"), False),
                             ("no reason", (key, 7, None, "T-1"), False),
                             ("a hand key", ("by-hand", 7, reason, "T-1"), False)):
        check_eq(f"K-W: code_scope_write is {want} for {name}", code_scope_write(*args), want)
    project, art, root_name, _, c = live_story()
    saved = hooklib._PROJECT_ROOT_CACHE
    try:
        hooklib._PROJECT_ROOT_CACHE = project
        marks = []

        def fake_marks(self, words):
            marks.append(words)
            return ["TS-1"]
        revision = c.state()["revision"]
        code_key = f"revise_plan:{c._ticket()}:{revision}:0123456789ab"
        with patched(Controller, "_mark_plan_overrides", fake_marks):
            c._after_commit("revise_plan", {"reason": SCOPE_REASON.format(n=4)}, key=code_key, revision=revision)
            check_eq("K-W1 (E44): a write of the code marks no row", marks, [])
            check_not_in("K-W1: and writes no word of a person", "TS-1", brief_pack.answers_of(root_name, project))
            c._after_commit("revise_plan", {"reason": "PERSON: row moved by hand"}, key="by-hand", revision=revision)
            check_eq("K-W2 (E45): a hand-written key: the row is marked with the words", marks, ["PERSON: row moved by hand"])
            check_in("K-W2: and the words reach the brief's reader, whole", "TS-1: PERSON: row moved by hand",
                     brief_pack.answers_of(root_name, project))
            marks.clear()
            c._after_commit("revise_plan", {"reason": "PERSON: keep TS-2 manual"}, key=code_key, revision=revision)
            check_eq("K-W3 (E46): the key of the code with the words of a person is the person's: marked, words whole",
                     marks, ["PERSON: keep TS-2 manual"])
            check_in("K-W3: and the word is kept for every later brief", "TS-1: PERSON: keep TS-2 manual",
                     brief_pack.answers_of(root_name, project))
    finally:
        hooklib._PROJECT_ROOT_CACHE = saved
        cleanup(project)
    # E44a: the real sequence - a person's words on a row, then a write of the code that leaves the row dropped: the words stay
    root, parent, c = RS.keyed_story(gate=False)
    try:
        c._capture_plan_baseline(c.state())
        words = "PERSON: TS-2 by hand"
        c.apply("revise_plan", {"scope": ["TC-001", "TC-003", "TC-004"], "plan_revision": "sha256:plan-h", "reason": words,
                                "idempotency_key": "hand"})

        def row():
            rows = json.loads((root / "work" / "test-plan.json").read_text(encoding="utf-8"))
            return next(r for r in (rows["rows"] if isinstance(rows, dict) else rows) if r["id"] == "TS-2")
        marked = {k: row().get(k) for k in ("overridden", "overridden_by", "overridden_words", "overridden_change")}
        check_eq("K-W1 setup: the person's write marked the row with their words", marked["overridden_words"], words)
        areas = {n: a for n, a in RS.AREAS.items() if n != 2}
        RS.pin_case_files(root, areas)
        revision = c.state()["revision"]
        c.apply("revise_plan", {"scope": ["TC-001", "TC-003", "TC-004"], "plan_revision": "sha256:plan-c", "reason": SCOPE_REASON.format(n=3),
                                "expected_revision": revision, "idempotency_key": f"revise_plan:{c._ticket()}:{revision}:0123456789ab"})
        check_eq("K-W1 (E44a): a write of the code after it leaves the person's words byte for byte, and the rest of the mark",
                 {k: row().get(k) for k in marked}, marked)
    finally:
        cleanup(parent)


def k_bat2_the_cli_battery():
    root, parent, c = RS.keyed_story(gate=False)
    try:
        events = len(c.store.read())
        base = {"plan_revision": "sha256:plan-b", "reason": "the cases"}
        many = [f"TC-{n:03d}" for n in range(100, 121)]
        battery = (("21 members", dict(base, scope=many, idempotency_key="b1")),
                   ("nested areas", dict(base, scope=["a/b/c/TC-001", "x/y/TC-002"], idempotency_key="b2")),
                   ("cyrillic and a space", dict(base, scope=[chr(0x438) + chr(0x434) + " 1/TC-001", "TC 001"], idempotency_key="b3")),
                   ("scope: [[]]", dict(base, scope=[[]], idempotency_key="b4")),
                   ("scope: a string", dict(base, scope="x", idempotency_key="b5")),
                   ("a key of 10000 characters", dict(base, scope=["TC-099"], idempotency_key="k" * 10000)))
        for name, body in battery:
            path = parent / "battery.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            done = run_script("controller.py", "--task-root", root, "--operation", "revise_plan", "--input", path, cwd=parent)
            check(f"K-bat2 [{name}]: a refusal and no trace", done.returncode != 0 and "Traceback" not in done.stderr + done.stdout,
                  f"{done.returncode} {(done.stderr + done.stdout)[-200:]}")
        check_eq("K-bat2: nothing was written by any of them", len(c.store.read()), events)
        path = parent / "battery.json"
        path.write_text(json.dumps(dict(base, scope=[], idempotency_key="b-empty")), encoding="utf-8")
        done = run_script("controller.py", "--task-root", root, "--operation", "revise_plan", "--input", path, cwd=parent)
        check_eq("K-bat2 [scope: []]: legal (an empty scope is a scope): exit 0, no trace",
                 (done.returncode, "Traceback" in done.stderr + done.stdout), (0, False))
        check_eq("K-bat2 [scope: []]: and the scope on record is empty", Controller(root).state()["scope"], [])
    finally:
        cleanup(parent)


def main():
    k_t2_t3_a_dot_root_names_its_folder()
    k_t4_a_live_worker_is_never_lost_to_a_spelling()
    k_t4_names_and_the_merge()
    k_t4_a_receipt_that_cannot_be_judged_removes_no_other()
    k_t5_a_record_is_found_by_the_same_task()
    k_l_the_list_cut_names_its_number()
    k_i1_the_three_answers_of_a_missing_index()
    k_e10_a_bare_member_is_refused_and_a_key_is_taken()
    k_p1_the_driver_reads_the_pins_the_controller_reads()
    k_c7_the_critic_scope_is_one_computation()
    k_m_the_manual_block_is_read_by_the_same_map()
    k_m6_the_three_roads_read_the_block_by_one_map()
    k_r_a_hand_written_key_reused()
    k_d_the_doors_name_both_moves()
    k_l_the_lease_and_the_hand_written_door()
    k_l7_the_driver_under_its_own_lease()
    k_w_the_words_of_the_code_are_not_the_words_of_a_person()
    k_bat2_the_cli_battery()
    finish("test_controller_scope_expansion")


if __name__ == "__main__":
    main()
