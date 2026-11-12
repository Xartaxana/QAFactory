#!/usr/bin/env python3
"""GB-1a (t-1509, HF5-17): what a person decides at gate B is carried out BEFORE the story is closed.

Run 12586 (0.10.4): the person chose two bug drafts at gate B; the factory counted the story closed on the spot, refused the
bug reporter ("the story closed at ..."), and the reporter was released by a person's word. The model since 0.10.5: gate B
gives ORDERS (`bugs` to the bug reporter, `mr` to the delivery step); the story is `executing` while an order is due and
`closed` after every order is done or called off. One reading of it (`hooklib.story_closure`), one producer of the
statuses (`controller.gate_b_orders`).

Keys of the spec §5.0 / §5.1a: K0 the fixture chain, K1 the seam (the recorded run replayed by the new controller, the real
`story_step.py start`), K2 / K3 / K3r the three ways out for `bugs`, K4 / K4b the MR, K5 the damaged records, K6 the
stories of 0.10.4, K7 "after the decision" by event number, K8 the `settle_order` battery, K10 the readers, K13 the late bug.
The fixture is rebuilt by `fixtures/run-12586-gate-b/rebuild.py` (README.txt there says what was changed).
"""
import contextlib
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import controller as CTL  # noqa: E402
import event_store  # noqa: E402
import execution_request as EX  # noqa: E402
import hooklib  # noqa: E402
import stage_guard  # noqa: E402
from controller import Controller  # noqa: E402

import test_controller_state as BASE  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-gate-b" / "TP1-12586"
WORDS = "leave them as drafts, no bug now\n"


def project_env(root):
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")


def refused(call):
    """`(class name, text)` of the refusal `call` raises, or None when it passes."""
    try:
        call()
    except Exception as exc:                 # noqa: BLE001 - the class and the text are what the test reads
        return type(exc).__name__, str(exc)
    return None


def replay(task):
    """The recorded run replayed by the CURRENT controller: the projection (pipeline.json) written from the journal."""
    controller = Controller(task)
    controller._project_pipeline(CTL.projection(controller.store.read()))
    return controller


def fixture_story(prefix):
    """(project root, task root, controller) over a throwaway copy of the recorded run, projected."""
    root = temp_project(prefix)
    use_project(root)
    task = root / "qa-factory" / "artifacts" / "TP1-12586"
    shutil.copytree(FIXTURE, task)
    return root, task, replay(task)


def pipeline_of(task):
    return json.loads((task / "pipeline.json").read_text(encoding="utf-8"))


def start_reporter(root, task):
    """The REAL producer of the dispatch request: `story_step.py start` for the bug reporter."""
    return run_script("story_step.py", "start", "--task", task.name, "--stage", "S8", "--role", "qa-bug-reporter",
                      cwd=root, env=project_env(root))


def words_file(task, name, text=WORDS):
    path = task / "state" / "words" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def settle(root, task, *args):
    return run_script("controller.py", "--task-root", str(task), "--operation", "settle_order", *args, cwd=root, env=project_env(root))


def accept_without_evidence(controller, dispatch_id):
    controller.store.commit("accept", {"id": dispatch_id, "status": "accepted", "stage_complete": False}, "acc:" + dispatch_id,
                            None, None, controller.project)


def synthetic(root, drafts=(), bugs=None, mr=None, through_s8=True):
    """A story that is finished up to gate B (S0-S8 accepted, gate A exact), then gate B recorded through the controller's own
    `build_gate_decision` (so the orders are written the way the CLI writes them). Returns the controller."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    c = Controller(root)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    c.apply("decision", BASE.bind_gate_a(root, {
        "id": "A", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
        "source_revision": "src-1", "scope": ["TC-1"], "input_revision": "src-1", "idempotency_key": "A"}))
    for number in range(5, 9):
        BASE.accept_stage(c, root, f"S{number}")
    if through_s8:
        decide(c, drafts, bugs, mr)
    return c


def decide(c, drafts=(), bugs=None, mr=None, words="their words"):
    return c.apply("decision", c.build_gate_decision("B", words, list(drafts), bugs=bugs, mr=mr))


def reporter(c, identifier, **extra):
    """A bug reporter dispatch committed the way a start commits it (the validators are not what is under test here)."""
    c.store.commit("dispatch", {"id": identifier, "stage": "S8", "role": "qa-bug-reporter", "scope": ["TC-1"], "input_hash": "x",
                                "budget": {}, "known_paths": {}, **extra}, "d:" + identifier, None, None, c.project)


def state_of(c):
    return CTL.closure_of(c.state(), c._pipeline())


# --- K0: the fixture's chain -----------------------------------------------------------------------

def the_fixture_chain_holds_and_a_flipped_character_breaks_it():
    events = event_store.EventStore(FIXTURE).read()
    check_eq("K0: the recorded run is read through the store's own chain check: 148 events", len(events), 148)
    check_eq("K0: the last one is the gate B decision", (events[-1]["type"], events[-1]["payload"]["gate"]), ("decision", "B"))
    root = temp_project("qa-gb-chain-")
    try:
        copy = root / "TP1-12586"
        shutil.copytree(FIXTURE, copy)
        log = copy / "state" / "events.jsonl"
        log.write_text(log.read_text(encoding="utf-8").replace("1 and 2 are one bug", "1 and 3 are one bug", 1),
                       encoding="utf-8", newline="\n")
        got = refused(lambda: event_store.EventStore(copy).read())
        check("K0 negative: one flipped character in a payload is a chain conflict", got is not None and "corrupt event 148" in got[1], str(got))
    finally:
        cleanup(root)


# --- K1: the seam -------------------------------------------------------------------------------------

def the_recorded_run_replays_as_executing_and_the_reporter_starts():
    root, task, c = fixture_story("qa-gb-k1-")
    try:
        closure = state_of(c)
        check_eq("K1: the recorded run is `executing`, not closed", (closure["state"], closure["due"]), ("executing", ["bugs"]))
        gate_b = pipeline_of(task)["gates"]["B"]
        check("K1: decided_at is UTC in the form of closed_at", bool(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", gate_b["decided_at"])), str(gate_b))
        check_eq("K1: the decision was recorded by 0.10.4 (no orders): bugs derived, mr not", gate_b["orders"], {"bugs": "due", "mr": "not_ordered"})
        check("K1: no closed_at was stamped on the executing story", "closed_at" not in pipeline_of(task))
        action = c.next_action()
        check_eq("K1: next is execute_gate_b", action["action"], "execute_gate_b")
        check_eq("K1: it names the executor and carries both chosen drafts",
                 (action["orders"][0]["order"], action["orders"][0]["executor"], action["orders"][0]["selected_drafts"],
                  action["orders"][0]["released_by_person"]),
                 ("bugs", {"stage": "S8", "role": "qa-bug-reporter"},
                  ["ms-teams-move-project-mismatch", "ms-teams-occupied-project-mismatch"], False))
        check_not_in("K1: the reason names no option that cannot carry a person's words", "--reason", action["reason"])
        done = start_reporter(root, task)
        check("K1 (the seam): story_step.py start for the bug reporter is NOT refused as a closed story",
              done.returncode == 0 and "dispatched S8-qa-bug-reporter-1" in done.stdout, (done.stdout + done.stderr)[-500:])
        after = Controller(task).next_action()
        check("K1: and next no longer asks for the order: the reporter is on record", after["action"] != "execute_gate_b", str(after)[:200])
        # the red control: an order that is not due leaves the older road - the same call is refused as a closed story
        other = temp_project("qa-gb-k1c-")
        try:
            c2 = synthetic(other, drafts=(), mr="not_offered")
            got = refused(lambda: reporter_request(c2))
            check("K1 control: with nothing ordered the story is closed and the reporter is refused with the old prefix",
                  got is not None and got[1].startswith("the story closed at"), str(got))
        finally:
            cleanup(other)
    finally:
        cleanup(root)


def reporter_request(c):
    return c.apply("dispatch", {"id": "S8-qa-bug-reporter-9", "stage": "S8", "role": "qa-bug-reporter", "scope": ["TC-1"],
                                "input_hash": "x", "budget": {}, "known_paths": {}, "idempotency_key": "k-r9"})


# --- K2, K3, K3r: the three ways out of `bugs` ---------------------------------------------------------

def a_person_can_call_the_bugs_off_and_the_story_closes():
    root, task, c = fixture_story("qa-gb-k2-")
    try:
        done = settle(root, task, "--order", "bugs", "--outcome", "cancelled", "--words-file", str(words_file(task, "k2.txt")))
        check("K2: settle_order cancelled with the person's words passes", done.returncode == 0, done.stderr[-400:])
        answer = json.loads(done.stdout)
        check_eq("K2: the answer's next move is `closed`, into the retro", (answer["next_action"]["action"], answer["next_action"].get("stage")),
                 ("closed", "S9"))
        c = Controller(task)
        check_eq("K2: the order is cancelled with the words kept whole", (c.state()["decisions"]["gateB-TP1-12586"]["orders_settled"]["bugs"]["outcome"],
                                                                         c.state()["decisions"]["gateB-TP1-12586"]["orders_settled"]["bugs"]["words"]),
                 ("cancelled", WORDS))
        check("K2: closed_at is the time of the settlement", bool(pipeline_of(task).get("closed_at")) and pipeline_of(task)["closed_by"])
        again = settle(root, task, "--order", "bugs", "--outcome", "cancelled", "--words-file", str(words_file(task, "k2.txt")))
        check("K8: the same call twice is the same answer with no new event", again.returncode == 0 and json.loads(again.stdout).get("already_recorded") is True,
              again.stdout[-300:] + again.stderr[-300:])
    finally:
        cleanup(root)


def the_accepted_reporter_settles_bugs_and_a_release_cancels_them():
    root, task, c = fixture_story("qa-gb-k3-")
    try:
        check("K3: the reporter starts", start_reporter(root, task).returncode == 0)
        c = Controller(task)
        accept_without_evidence(c, "S8-qa-bug-reporter-1")
        gate_b = c.state()["decisions"]["gateB-TP1-12586"]
        check_eq("K3: the accept of the reporter made AFTER the decision settles `bugs` as done",
                 (gate_b["orders_settled"]["bugs"]["outcome"], gate_b["orders_settled"]["bugs"]["dispatch_id"]), ("done", "S8-qa-bug-reporter-1"))
        check_eq("K3: the story is closed", state_of(c)["state"], "closed")
    finally:
        cleanup(root)
    root, task, c = fixture_story("qa-gb-k3r-")
    try:
        check("K3r: the reporter starts", start_reporter(root, task).returncode == 0)
        c = Controller(task)
        answer = c.release_dispatch("S8-qa-bug-reporter-1", "leave the drafts, no bug now")
        gate_b = c.state()["decisions"]["gateB-TP1-12586"]
        check_eq("K3r: a release by a person's word cancels `bugs` with those words",
                 (gate_b["orders_settled"]["bugs"]["outcome"], gate_b["orders_settled"]["bugs"]["words"]), ("cancelled", "leave the drafts, no bug now"))
        check_eq("K3r: next is `closed`, never execute_gate_b again", answer["next_action"]["action"], "closed")
        check("K3r: the release of the executor is no reopening of the story", "reopened_at" not in pipeline_of(task), str(pipeline_of(task).get("reopened_at")))
    finally:
        cleanup(root)


# --- K4, K4b, K13: the MR ----------------------------------------------------------------------------------

def the_mr_is_done_only_with_its_record():
    root = temp_project("qa-gb-k4-")
    try:
        c = synthetic(root, drafts=("a",), mr="open")
        check_eq("K4: the new decision orders both", CTL.orders_due(c.state()), ["bugs", "mr"])
        reporter(c, "S8-qa-bug-reporter-1")
        accept_without_evidence(c, "S8-qa-bug-reporter-1")
        check_eq("K4: the reporter accepted: only the MR is due", CTL.orders_due(c.state()), ["mr"])
        for stage, role in (("S5", "qa-automator"), ("S9", "qa-retro-analyst")):
            got = refused(lambda: c.apply("dispatch", {"id": f"{stage}-x-9", "stage": stage, "role": role, "scope": ["TC-1"],
                                                      "input_hash": "x", "budget": {}, "known_paths": {}, "idempotency_key": "k" + stage}))
            check(f"K4: a {stage} dispatch on the executing story is refused, naming the orders and a door",
                  got is not None and got[0] == "StateConflict" and "not carried out yet (mr)" in got[1]
                  and "settle_order" in got[1] and "--words-file" in got[1], str(got))
        got = refused(lambda: c.settle_order("mr", "done"))
        check("K4b: `done` without --ref is a ValueError that names the MR record", got is not None and got[0] == "ValueError" and "--ref" in got[1], str(got))
        c.settle_order("mr", "done", ref="https://example/mr/1")
        pipeline = c._pipeline()
        check_eq("K4: the MR record settles the order and the story is closed", state_of(c)["state"], "closed")
        check_eq("K4: closed_at is the time of THAT settlement", pipeline.get("closed_at"),
                 c.state()["decisions"]["gateB-" + root.name]["orders_settled"]["mr"]["at"])
    finally:
        cleanup(root)
    root = temp_project("qa-gb-k4b-")
    try:
        c = synthetic(root, drafts=(), mr="open")
        c.settle_order("mr", "cancelled", ref="delivery step: nothing outward was done", reason_code="delivered_without_mr")
        check_eq("K4b: the factory's coded reason with the delivery step's record cancels the MR", state_of(c)["state"], "closed")
    finally:
        cleanup(root)
    root = temp_project("qa-gb-k13-")
    try:
        c = synthetic(root, drafts=(), mr="not_offered")
        check_eq("K13 pre: nothing ordered, closed at once (FR-23)", state_of(c)["state"], "closed")
        decide(c, drafts=(), bugs="ordered", mr="not_offered")
        check_eq("K13: a later decision for a bug with the MR not offered: only bugs is due", CTL.orders_due(c.state()), ["bugs"])
        check_eq("K13: and the story is executing again", state_of(c)["state"], "executing")
        check("K13: closed_at stays the first closure (a story closes once); the reading is the current state",
              bool(c._pipeline().get("closed_at")), str(c._pipeline().get("closed_at")))
    finally:
        cleanup(root)


# --- K5, K6: the damaged records and the older stories --------------------------------------------------------

def pipeline_with(orders_due, **gate_b):
    done = {"status": "done", "finished": "2026-10-20T10:00:00+00:00"}
    record = {"decision": "approved", "status": "approved", "decided_at": "2026-10-20T11:00:00+00:00", **gate_b}
    if orders_due is not hooklib:                 # `hooklib` stands for "the key is absent"
        record["orders_due"] = orders_due
    return {"stages": {"S8": done, "S9": {"status": "pending"}}, "gates": {"B": record}}


def a_damaged_record_is_never_read_as_nothing_owed():
    for label, damaged in (("a string", "bugs"), ("an integer", 5), ("a list with a non-name", [1]), ("null", None), ("an object", {"bugs": 1})):
        closure = hooklib.story_closure(pipeline_with(damaged))
        check_eq(f"K5: orders_due as {label} reads executing / unknown (FR-59)", (closure["state"], closure["due"]), ("executing", ["unknown"]))
        check_eq("K5: and story_closed is empty for it", hooklib.story_closed(pipeline_with(damaged)), "")
    check_eq("K5: declined, no orders: closed (a decline is an answer)",
             hooklib.story_closure(pipeline_with([], decision="declined", status="declined"))["state"], "closed")
    check_eq("K5: approved with nothing ordered: closed", hooklib.story_closure(pipeline_with([]))["state"], "closed")
    check_eq("K6: a file written by 0.10.4 (no orders_due key, closed_at) is read the old way",
             hooklib.story_closure(dict(pipeline_with(hooklib), closed_at="2026-10-20T11:00:00+00:00"))["state"], "closed")
    check_eq("K6: a person's word after the decision opens an executing story",
             hooklib.story_closure(dict(pipeline_with(["bugs"]), reopened_at="2026-10-20T12:00:00+00:00"))["state"], "open")
    check_eq("K6: the same word BEFORE the decision does not (compared as moments, whatever the offset)",
             hooklib.story_closure(dict(pipeline_with(["bugs"]), reopened_at="2026-10-20T13:30:00+03:00"))["state"], "executing")
    check_eq("K6: an unreadable decided_at is not a word: executing",
             hooklib.story_closure(dict(pipeline_with(["bugs"], decided_at="soon"), reopened_at="2026-10-20T12:00:00+00:00"))["state"], "executing")
    check_eq("edge: gates a list, gates.B a string: the old reading, open",
             (hooklib.story_closure({"stages": {"S8": {"status": "done"}}, "gates": []})["state"],
              hooklib.story_closure({"stages": {"S8": {"status": "done"}}, "gates": {"B": "approved"}})["state"]), ("open", "open"))
    check_eq("edge: no pipeline at all", hooklib.story_closure(None), {"state": "open", "closed_at": "", "due": []})
    # F19: the file says [] while an order is due: the reader trusts the file, the controller recomputes from its own state
    root = temp_project("qa-gb-f19-")
    try:
        c = synthetic(root, drafts=("a",))
        file = c._pipeline()
        file["gates"]["B"]["orders_due"] = []
        check_eq("K5/F19: hooklib trusts orders_due and reads closed", hooklib.story_closure(file)["state"], "closed")
        check_eq("K5/F19: the controller reads its own state: executing", state_of(c)["state"], "executing")
    finally:
        cleanup(root)


def a_story_of_0_10_4_is_read_as_it_was():
    root = temp_project("qa-gb-k6-")
    try:
        c = synthetic(root, through_s8=True)
        raw = {"id": "B-raw", "gate": "B", "action": "deliver", "status": "approved", "authorization_source": "human",
               "source_revision": "src-1", "scope": ["TC-1"], "input_revision": "src-1", "selected_drafts": ["d"], "idempotency_key": "Braw"}
        c.apply("decision", raw)
        check_eq("K6: a raw decision with drafts and no orders (F13) still derives `bugs` while the retro has not started",
                 CTL.orders_due(c.state()), ["bugs"])
        c.store.commit("stage_transition", {"task": root.name, "stage": "S9", "status": "running", "role": "qa-retro-analyst", "digest": ""},
                       "s9run", None, None, c.project)
        check_eq("K6/F14: S9 running at the update: the order is not derived", CTL.orders_due(c.state()), [])
    finally:
        cleanup(root)


# --- K7: after the decision is a number ------------------------------------------------------------------------

def an_older_reporter_does_not_settle_a_newer_decision():
    root = temp_project("qa-gb-k7-")
    try:
        c = synthetic(root, drafts=("a",))
        reporter(c, "S8-qa-bug-reporter-1")
        decide(c, drafts=("b",))
        accept_without_evidence(c, "S8-qa-bug-reporter-1")
        decisions = c.state()["decisions"]
        check_eq("K7: two decisions: the second one wins", CTL.latest_gate_b(c.state())["id"], "gateB-" + root.name + "-2")
        check_eq("K7: the reporter made before the second decision does not execute it: bugs is still due", CTL.orders_due(c.state()), ["bugs", "mr"])
        check("K7: and the accept did not settle the FIRST decision either (the newest decision is the one that counts)",
              "orders_settled" not in decisions["gateB-" + root.name] and "orders_settled" not in decisions["gateB-" + root.name + "-2"])
        seqs = [d["decided_seq"] for d in decisions.values() if d.get("gate") == "B"]
        check("K7: decided_seq are the events' own numbers, in order", seqs == sorted(seqs) and len(set(seqs)) == 2, str(seqs))
    finally:
        cleanup(root)


# --- K8: settle_order, the battery ------------------------------------------------------------------------------------

def settle_order_refuses_by_class_and_door():
    root = temp_project("qa-gb-k8-")
    try:
        c = synthetic(root, drafts=("a",), mr="open")
        revision = c.state()["revision"]

        def first(order, outcome, **kw):
            return refused(lambda: c.settle_order(order, outcome, **kw))
        for label, got, cls, needle in (
                ("an empty --order", first("", "done", ref="r"), "ValueError", "--order names the order"),
                ("an unknown --order", first("deploy", "done", ref="r"), "ValueError", "bugs, mr"),
                ("an unknown --outcome", first("mr", "maybe"), "ValueError", "done, cancelled"),
                ("done for bugs", first("bugs", "done", ref="r"), "ValueError", "bugs is done by the accepted qa-bug-reporter dispatch, not by a word"),
                ("cancelled with no words and no code", first("mr", "cancelled"), "ValueError", "--words-file"),
                ("an unknown --reason-code", first("mr", "cancelled", reason_code="because", ref="r"), "ValueError", "no_trace, delivered_without_mr"),
                ("a code with no --ref", first("mr", "cancelled", reason_code="no_trace"), "ValueError", "--ref"),
                ("--ref of 2001 characters", first("mr", "done", ref="x" * 2001), "ValueError", "at most 2000 characters")):
            check(f"K8: {label}: class {cls} and the sentence", got is not None and got[0] == cls and needle in got[1], str(got))
        check_eq("K8: nothing was written by any refusal", c.state()["revision"], revision)
        got = refused(lambda: c.settle_order("", "maybe", ref="x" * 2001))
        check("K8: several problems are ONE refusal listing all of them", got is not None and "3 problems" in got[1], str(got))
        c.settle_order("mr", "done", ref="x" * 2000)
        check_eq("K8 AT the limit: 2000 characters are taken", state_of(c)["due"], ["bugs"])
        c2root = temp_project("qa-gb-k8b-")
        try:
            c2 = synthetic(c2root, drafts=("a",), mr="open")
            c2.settle_order("mr", "done", ref="https://example/mr/\u2116 1\nline two")
            check_eq("K8: a --ref with a line break and non-ASCII text is stored as given",
                     c2.state()["decisions"]["gateB-" + c2root.name]["orders_settled"]["mr"]["ref"], "https://example/mr/\u2116 1\nline two")
            got = refused(lambda: c2.settle_order("mr", "cancelled", words="again"))
            check("K8: an order that is not due (already done) is a StateConflict with the statuses and the `next` door",
                  got is not None and got[0] == "StateConflict" and "not due" in got[1] and "next" in got[1], str(got))
        finally:
            cleanup(c2root)
        bare = temp_project("qa-gb-k8c-")
        try:
            c3 = synthetic(bare, through_s8=False)
            got = refused(lambda: c3.settle_order("mr", "cancelled", words="no"))
            check("K8: before gate B is decided: StateConflict with the gate-decision door",
                  got is not None and got[0] == "StateConflict" and "gate-decision --gate B" in got[1], str(got))
        finally:
            cleanup(bare)
        none = temp_project("qa-gb-k8d-")
        try:
            c4 = synthetic(none, drafts=(), mr="not_offered")
            got = refused(lambda: c4.settle_order("mr", "cancelled", words="no"))
            check("K8: on a `not_ordered` order: StateConflict, nothing to settle", got is not None and got[0] == "StateConflict" and "not_ordered" in got[1], str(got))
        finally:
            cleanup(none)
    finally:
        cleanup(root)


# --- K10: the readers ---------------------------------------------------------------------------------------------------

def the_readers_of_closure_see_executing():
    root, task, c = fixture_story("qa-gb-k10-")
    try:
        pipeline = pipeline_of(task)
        saved = (CTL.code_close_conflicts, CTL.code_close_facts)
        CTL.code_close_conflicts, CTL.code_close_facts = (lambda s, st, v=None: [], lambda s, st, v=None: {"running": [], "behind": None, "completed": False})
        try:
            got = refused(lambda: EX.s6_close_from_state(task, {"stages": {}, "scope": ["TC-1"]}, ["TC-1"]))
        finally:
            CTL.code_close_conflicts, CTL.code_close_facts = saved
        check("K10: execution_request adds no evidence to S6 once gate B is decided, executing included",
              got is not None and "S6 is already closed (the story is closed)" in got[1], str(got))
        out, saved_env = io.StringIO(), os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        try:
            with contextlib.redirect_stdout(out):
                stage_guard.stories()
        finally:
            if saved_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = saved_env
        check_in("K10: the listing says `executing gate B: bugs` out loud", "executing gate B: bugs", out.getvalue())
        check_eq("K10: story_closed is empty while executing (archive, stall and the doctor's closed list read it)",
                 hooklib.story_closed(pipeline), "")
    finally:
        cleanup(root)


def the_orders_come_from_the_data_row_not_from_code():
    table = hooklib.gate_orders()
    check_eq("AR-1: the orders are the S8 row of stages.json: bugs by the bug reporter, mr by the delivery step",
             (table["bugs"]["executor"], table["mr"]["executor"], table["bugs"]["gate"]), ({"stage": "S8", "role": "qa-bug-reporter"}, "delivery", "B"))
    check_eq("AR-1: a table that cannot be read names no order (never a guess)", hooklib.gate_orders({"stages": "x"}), {})
    check_eq("AR-1: an entry that is not an object is absent", hooklib.gate_orders({"stages": [{"gate_orders": {"a": 1, "b": {"executor": "x"}}}]}),
             {"b": {"executor": "x"}})


# --- t-1562 fix round: F1/F2 (doors on a closed story), F3 (a code is the MR's), F4 (projection-owned keys), F9 (the doc) ---------------

def a_closed_story_names_only_doors_that_open():
    """F1 / GB-3 K1 + K2 (killed by: the old closed-story return, `reopen_story` named with nothing held), F2 (killed by: `--reason` back
    in the `closed` reason of `next`)."""
    root = temp_project("qa-gb-f1-")
    try:
        c = synthetic(root, drafts=(), mr="not_offered")
        check_eq("F1 pre: nothing ordered, the story is closed at once", state_of(c)["state"], "closed")
        got = refused(lambda: reporter_request(c))
        text = got[1] if got else ""
        check("F1 K2: the first reporter on a closed story is refused as a closed story", got is not None and text.startswith("the story closed at"), str(got))
        check_not_in("F1 K2: no `reopen_story` (nothing is held back: that door does not open)", "reopen_story", text)
        check_not_in("F1 K2: no `rework --stage S8 --role qa-bug-reporter` (no accepted reporter exists)", "--role qa-bug-reporter", text)
        check_in("F1: the door that opens is the new gate B decision, by words file", "gate-decision --gate B", text)
        check_in("F1: ... with the bug order", "--bugs ordered --mr not_offered --words-file", text)
        decide(c, drafts=(), bugs="ordered", mr="not_offered")
        check_eq("F1 K1: that door opens: the second decision leaves `bugs` due", CTL.orders_due(c.state()), ["bugs"])
    finally:
        cleanup(root)
    root = temp_project("qa-gb-f1b-")
    try:
        c = synthetic(root, drafts=(), mr="not_offered")
        request = {"id": "S8-qa-worker-9", "stage": "S8", "role": "qa-worker", "scope": ["TC-1"], "input_hash": "x", "budget": {},
                   "known_paths": {}, "idempotency_key": "k-w9"}
        text = (refused(lambda: c.apply("dispatch", request)) or ("", ""))[1]
        check_in("F1: with an accepted dispatch of that stage and role, `rework` is named, with those", "rework --stage S8 --role qa-worker", text)
        check_not_in("F1: and the gate B decision is not named for a role that executes no order", "gate-decision", text)
        rework = c.build_rework_request("S8", "qa-worker", ["TC-1"], "their words", words_given=True)
        c.apply("dispatch", rework)
        check_eq("F1 K1: the rework door opens on the same state: the story is open", state_of(c)["state"], "open")
    finally:
        cleanup(root)
    root = temp_project("qa-gb-f1c-")
    try:
        c = synthetic(root, drafts=(), mr="not_offered")
        none = (refused(lambda: c.apply("dispatch", {"id": "S7-x-1", "stage": "S7", "role": "qa-nobody", "scope": ["TC-1"], "input_hash": "x",
                                                    "budget": {}, "known_paths": {}, "idempotency_key": "k-n1"})) or ("", ""))[1]
        check("F1 edge: no held work, no accepted dispatch of the role, not an executor: no word-door at all, `next` is the move (FR-57)",
              "--operation next" in none and "reopen_story" not in none and "rework" not in none and "gate-decision" not in none, none)
        held = [{"id": "d-held"}]
        both = CTL._closed_story_doors(c.state(), {"stage": "S8", "role": "qa-bug-reporter"}, held)
        check("F1 K1 (held): with work held back `reopen_story --dispatch` is named", "reopen_story --dispatch" in both, both)
        check_in("F1: S9 needs no word", "retro (S9) needs no word", CTL._closed_story_doors(c.state(), {"stage": "S9", "role": "qa-retro-analyst"}, []))
        reason = c.next_action()
        check_eq("F2: next on the closed story is `closed`", reason["action"], "closed")
        check_not_in("F2: the reason has no `--reason ` (it cannot carry a person's words)", "--reason ", reason["reason"])
        check_in("F2: and names `--words-file`", "--words-file", reason["reason"])
        check_in("F2: and says every order is settled", "every order it gave is settled", reason["reason"])
        check_in("F2: and the gate B decision door", "gate-decision --gate B", reason["reason"])
    finally:
        cleanup(root)


def a_reason_code_is_the_mr_orders_and_the_decision_has_no_projection_keys():
    """F3 (killed by: `--reason-code` accepted for `bugs`), F4 (killed by: `_decision_problems` without the owned-keys refusal)."""
    root = temp_project("qa-gb-f3-")
    try:
        c = synthetic(root, drafts=("a",), mr="open")
        revision = c.state()["revision"]
        for label, kw in (("code + ref", dict(reason_code="delivered_without_mr", ref="x")),
                          ("code + ref + the person's words", dict(reason_code="no_trace", ref="x", words="their words"))):
            got = refused(lambda: c.settle_order("bugs", "cancelled", **kw))
            check(f"F3: bugs + {label}: ValueError naming --words-file and release",
                  got is not None and got[0] == "ValueError" and "--words-file" in got[1] and "release" in got[1] and "`mr` order only" in got[1], str(got))
        got = refused(lambda: c.settle_order("bugs", "cancelled", reason_code="no_trace", ref="x" * 2001))
        check("F3: listed with the other shape problems at once", got is not None and "2 problems" in got[1], str(got))
        check_eq("F3: nothing was written", (c.state()["revision"], CTL.orders_due(c.state())), (revision, ["bugs", "mr"]))
        c.settle_order("bugs", "cancelled", words="their words")
        check_eq("F3: bugs is still called off by the person's words", CTL.gate_b_orders(c.state())["bugs"], "cancelled")
        c.settle_order("mr", "cancelled", reason_code="delivered_without_mr", ref="x")
        check_eq("F3: mr + code + ref is cancelled", CTL.gate_b_orders(c.state())["mr"], "cancelled")
    finally:
        cleanup(root)
    root = temp_project("qa-gb-f4-")
    try:
        c = synthetic(root, through_s8=True)
        raw = {"id": "B-raw", "gate": "B", "action": "deliver", "status": "approved", "authorization_source": "human",
               "source_revision": "src-1", "scope": ["TC-1"], "input_revision": "src-1", "selected_drafts": ["d"], "idempotency_key": "Braw",
               "orders": {"bugs": "due", "mr": "due"}, "orders_settled": {"bugs": {"outcome": "done"}, "mr": {"outcome": "done"}}}
        got = refused(lambda: c.apply("decision", raw))
        check("F4: a raw decision carrying orders_settled is refused, naming the projection as the writer",
              got is not None and got[0] == "ValueError" and "orders_settled" in got[1] and "projection" in got[1], str(got))
        for key, value in (("orders_due", []), ("decided_seq", 1), ("decided_at", "2026-01-01T00:00:00+00:00")):
            one = dict(raw, idempotency_key="B" + key, **{key: value})
            one.pop("orders_settled")
            got = refused(lambda: c.apply("decision", one))
            check(f"F4: a raw decision carrying {key} is refused", got is not None and key in got[1], str(got))
        check_eq("F4: nothing was recorded by any refusal: gate B is still the first decision", CTL.latest_gate_b(c.state())["id"] != "B-raw", True)
        clean = dict(raw, idempotency_key="Bclean")
        clean.pop("orders_settled")
        c.apply("decision", clean)
        check_eq("F4: with only `orders` it is recorded and both orders are due", CTL.orders_due(c.state()), ["bugs", "mr"])
        # the projection's own line of defence: a payload that got into the journal anyway is dropped on replay
        c.store.commit("decision", dict(clean, id="B-leak", idempotency_key="Bleak", orders_settled={"bugs": {"outcome": "done"}, "mr": {"outcome": "done"}}),
                       "leak", None, None, c.project)
        check_eq("F4 (projection): a payload that reached the journal anyway settles nothing on replay: both orders still due",
                 CTL.orders_due(c.state()), ["bugs", "mr"])
        check("F4 (projection) positive control: the leaked decision is the newest and carries its own `orders`",
              CTL.latest_gate_b(c.state())["id"] == "B-leak" and "orders" in CTL.latest_gate_b(c.state()), str(CTL.latest_gate_b(c.state()))[:200])
    finally:
        cleanup(root)


def the_controller_api_doc_keeps_derived_markdown():
    """F9: the allowlisted `markdown_projection` kind is named in `controller-api.md` (killed by: the phrase dropped again)."""
    text = (SCRIPTS.parent / "references" / "controller-api.md").read_text(encoding="utf-8")
    check("F9: controller-api.md names `derived Markdown` among the technical normalisations", "derived Markdown" in text)
    check("F9 negative control: the same check on the text with the phrase cut out fails", "derived Markdown" not in text.replace("derived Markdown", ""))
    check("F9: and the file stays within its 12000-byte cap", len(text.encode("utf-8")) <= 12000, str(len(text.encode("utf-8"))))


def main() -> None:
    a_closed_story_names_only_doors_that_open()
    a_reason_code_is_the_mr_orders_and_the_decision_has_no_projection_keys()
    the_controller_api_doc_keeps_derived_markdown()
    the_fixture_chain_holds_and_a_flipped_character_breaks_it()
    the_orders_come_from_the_data_row_not_from_code()
    the_recorded_run_replays_as_executing_and_the_reporter_starts()
    a_person_can_call_the_bugs_off_and_the_story_closes()
    the_accepted_reporter_settles_bugs_and_a_release_cancels_them()
    the_mr_is_done_only_with_its_record()
    a_damaged_record_is_never_read_as_nothing_owed()
    a_story_of_0_10_4_is_read_as_it_was()
    an_older_reporter_does_not_settle_a_newer_decision()
    settle_order_refuses_by_class_and_door()
    the_readers_of_closure_see_executing()
    finish("test_gate_b_orders")


if __name__ == "__main__":
    main()
