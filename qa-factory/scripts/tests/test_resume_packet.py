#!/usr/bin/env python3
"""A stopped role resumes in one step, and an evidence refusal names the path.

TP2-2553, section 1: a role stopped; the hook refused the resume because nothing had
ever recorded an `agent_id`; `accept` refused the blocked dispatch with "only the active
dispatch can finish"; the orchestrator hand-built a retry dispatch and its acceptance was
refused with the bare words "missing or outside-task evidence" — no path, no root, no hint
that the reference was absolute. Five steps, two receipts, about two hours.

Four rules here. Every evidence reference is judged by `contract.evidence_ref_issue`, so the
refusal is one sentence a person can act on. A stopped dispatch that nothing replaced carries
its own retry packet in `next` and in `recover`, ready for `--operation dispatch --input`.
`accept` on a dispatch a retry has taken over names that retry, and on a stopped one names
both ways out. And the id the host gave the agent travels from the dispatch request into
pipeline.json, which is where the resume rule looks for it.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     mark_project, temp_project)

sys.path.insert(0, str(SCRIPTS))
from controller import Controller  # noqa: E402
from event_store import StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework as REWORK  # noqa: E402  (designer_story, refusal fixtures)

SCOUT = "S1-qa-scout-1"


def at_s1(root: Path) -> Controller:
    """A story with S0 accepted, ready to dispatch S1."""
    mark_project(root)
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    BASE.accept_stage(controller, root, "S0")
    return controller


def evidence(root: Path, name: str) -> dict:
    path = root / name
    path.write_text(name, encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def dispatch_scout(controller: Controller, identity: str = SCOUT, **extra) -> dict:
    request = {"id": identity, "stage": "S1", "role": "qa-scout", "scope": ["TC-1"],
               "input_hash": "sources-1", "budget": {}, "known_paths": {},
               "idempotency_key": "d-" + identity, **extra}
    controller.apply("dispatch", dict(request))
    return request


def block(controller: Controller, identity: str = SCOUT, reason: str = "the tracker did not answer"):
    controller.apply("checkpoint", {"id": identity, "status": "blocked", "reason": reason,
                                    "checkpoint": {"remaining": ["TC-1"]},
                                    "idempotency_key": "cp-" + identity})


def refused(call) -> str:
    try:
        call()
    except (ValueError, StateConflict) as exc:
        return str(exc)
    return ""


# --- (a) an evidence refusal names the path, the root and the spelling that works ----------

def an_evidence_refusal_names_the_path():
    root = temp_project("qa-resume-evidence-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller)
        ref = evidence(root, "manifest.json")

        absolute = refused(lambda: controller.apply("accept", {
            "id": SCOUT, "status": "accepted", "idempotency_key": "a-abs",
            "evidence_refs": [dict(ref, path=str((root / "manifest.json").resolve()))]}))
        check_in("an absolute path is still refused", "is absolute", absolute)
        check_in("and the refusal prints the spelling that works", "manifest.json", absolute)
        check_not_in("never the bare words of 2553", "missing or outside-task", absolute)

        missing = refused(lambda: controller.apply("accept", {
            "id": SCOUT, "status": "accepted", "idempotency_key": "a-missing",
            "evidence_refs": [{"path": "work/nowhere.json", "sha256": "0" * 64}]}))
        check_in("a missing file names the path", "work/nowhere.json", missing)
        check_in("and the task root it was looked for under", str(root.resolve()), missing)

        (root / "manifest.json").write_text("changed after it was referenced", encoding="utf-8")
        stale = refused(lambda: controller.apply("accept", {
            "id": SCOUT, "status": "accepted", "idempotency_key": "a-stale",
            "evidence_refs": [ref]}))
        check_in("a file that moved on says stale", "stale", stale)
        check_in("and says so of the file, not of the task", "manifest.json", stale)
    finally:
        cleanup(root)


# --- (b) a stopped dispatch carries its own retry packet -----------------------------------

def a_stopped_dispatch_carries_its_retry_packet():
    root = temp_project("qa-resume-packet-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller, purpose="initial")
        block(controller)

        action = controller.next_action()
        check_eq("the stopped role is what `next` answers", action["action"], "resume_checkpoint")
        packet = action.get("packet") or {}
        check_eq("the retry is named after the role, not the old id", packet.get("id"), "S1-qa-scout-2")
        check_eq("it supersedes the dispatch that stopped", packet.get("parent_retry"), SCOUT)
        check_eq("it inherits the checkpoint verbatim, as the validator demands",
                 packet.get("checkpoint"), {"remaining": ["TC-1"]})
        check_eq("and the inputs, so the work is the same work",
                 [packet.get("stage"), packet.get("role"), packet.get("scope"), packet.get("input_hash")],
                 ["S1", "qa-scout", ["TC-1"], "sources-1"])
        check_eq("what the old dispatch was for travels with it", packet.get("purpose"), "initial")
        check_in("the reason names the command that sends it",
                 "--operation dispatch --input", action.get("reason") or "")
        check_in("and still says what stopped the role",
                 "the tracker did not answer", action.get("reason") or "")

        # The whole point: no edits. This is `--operation dispatch --input <that file>`.
        controller.apply("dispatch", json.loads(json.dumps(packet)))
        state = controller.state()
        check_eq("the dispatch that stopped is superseded, not a second open one",
                 state["dispatches"][SCOUT]["status"], "superseded")
        check_eq("and the retry is the running one",
                 state["dispatches"]["S1-qa-scout-2"]["status"], "running")

        controller.apply("accept", {"id": "S1-qa-scout-2", "status": "accepted",
                                    "stage_complete": True,
                                    "evidence_refs": [evidence(root, "manifest.json")],
                                    "idempotency_key": "a-retry"})
        check_eq("the retry closes S1 with the evidence the role wrote",
                 controller.state()["stages"]["S1"]["status"], "completed")
    finally:
        cleanup(root)


def a_replaced_checkpoint_gets_no_second_retry():
    root = temp_project("qa-resume-replaced-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller)
        block(controller)
        controller.apply("dispatch", json.loads(json.dumps(controller.next_action()["packet"])))
        block(controller, "S1-qa-scout-2", "the tracker still did not answer")
        action = controller.next_action()
        check_eq("the answer is the later checkpoint", action.get("dispatch_id"), "S1-qa-scout-2")
        check("which is the one that carries the packet", bool(action.get("packet")))
        check_eq("and only one packet is offered at a time",
                 [p["dispatch_id"] for p in controller.retry_packets()], ["S1-qa-scout-2"])
    finally:
        cleanup(root)


# --- (b2) later work of the stage outranks what came before it (B-312) ----------------------
#
# TP2-2406: an S5 dispatch was returned, a later one of the same stage never started, and
# `next` kept answering `resolve_return` for the OLD one - the legacy test gives 39/41 and
# "relaunch" expected. Only an accepted later dispatch used to count as "later work".

def entry(identifier, status, stage="S5", role="qa-automator", **extra):
    return dict({"id": identifier, "stage": stage, "role": role, "status": status,
                 "scope": ["TC-081"], "input_hash": "bytes-1", "known_paths": {}, "budget": {}},
                **extra)


def next_for(entries, stages=None, revision=41, pipeline=None, reopened_at=None, **state_extra):
    state = {"dispatches": {d["id"]: d for d in entries},
             "stages": stages if stages is not None else {"S5": {"status": "pending"}},
             "environment_jobs": [], "decisions": {}, "revision": revision}
    if reopened_at:
        state["reopened_at"] = reopened_at
    state.update(state_extra)
    return Controller._next_action_for_state(state, pipeline)


def a_newer_unlaunched_dispatch_outranks_an_older_return():
    """A recovery record is current work, not an older return's retry target."""
    state = {"dispatches": {
        "S5-qa-automator-26": {"id": "S5-qa-automator-26", "stage": "S5",
                                  "role": "qa-automator", "status": "returned_unaccepted",
                                  "scope": ["TC-081"], "input_hash": "bytes-1",
                                  "known_paths": {}, "budget": {}},
        "S5-qa-automator-29": {"id": "S5-qa-automator-29", "stage": "S5",
                                  "role": "qa-automator", "status": "never_started",
                                  "scope": ["TC-081"], "input_hash": "bytes-1",
                                  "known_paths": {}, "budget": {}},
    }, "stages": {"S5": {"status": "pending"}}, "environment_jobs": {}, "revision": 41}
    action = Controller._next_action_for_state(state)
    check_eq("a newer never-started dispatch outranks an older returned receipt",
             action.get("action"), "relaunch")
    check_eq("and relaunches the newest recovered dispatch", action.get("closed_dispatch_id"),
             "S5-qa-automator-29")


def later_work_of_the_stage_hides_what_it_replaced():
    old, new = "S5-qa-automator-1", "S5-qa-automator-2"
    for label, older in (("blocked", "blocked"), ("paused", "paused"), ("incomplete", "incomplete")):
        action = next_for([entry(old, older, checkpoint={"remaining": ["TC-081"]}),
                           entry(new, "never_started")])
        check_eq(f"a later never-started dispatch hides an older {label} one: relaunch, not resume",
                 (action["action"], action.get("closed_dispatch_id")), ("relaunch", new))
    action = next_for([entry(old, "abandoned"), entry(new, "never_started")])
    check_eq("it hides an older abandoned one too", action["action"], "relaunch")

    action = next_for([entry(old, "returned_unaccepted"), entry(new, "released_by_person")])
    check_eq("a later dispatch a person released hides the older return and is relaunched",
             (action["action"], action.get("closed_dispatch_id")), ("relaunch", new))
    action = next_for([entry(old, "returned_unaccepted"), entry(new, "accepted")])
    check("a later accepted dispatch hides it, as it always did",
          action["action"] not in ("resolve_return", "resume_checkpoint", "relaunch"), action)
    action = next_for([entry(old, "returned_unaccepted"), entry(new, "returned_unaccepted")])
    check_eq("a later return is the one to settle",
             (action["action"], action.get("dispatch_id")), ("resolve_return", new))

    for status in ("superseded", "stale"):
        action = next_for([entry(old, "returned_unaccepted"), entry(new, status)])
        check_eq(f"a later {status} dispatch hides nothing: the return is still to settle",
                 (action["action"], action.get("dispatch_id")), ("resolve_return", old))
        action = next_for([entry(old, "blocked", checkpoint={"remaining": ["TC-081"]}),
                           entry(new, status)])
        check_eq(f"nor does it hide a stopped one when it is {status}",
                 (action["action"], action.get("dispatch_id")), ("resume_checkpoint", old))

    action = next_for([entry(old, "returned_unaccepted"),
                       entry("S6-qa-automator-1", "never_started", stage="S6")],
                      stages={"S5": {"status": "pending"}, "S6": {"status": "pending"}})
    check_eq("work of ANOTHER stage never hides a return",
             (action["action"], action.get("dispatch_id")), ("resolve_return", old))


# --- (b3) a never-started REWORK of an accepted stage is relaunched (found with B-312) ------

def a_never_started_rework_of_an_accepted_stage_is_relaunched():
    done = {"S5": {"status": "completed"}}
    plain = next_for([entry("S5-qa-automator-1", "never_started")], stages=done)
    check("a never-started dispatch with no rework_of on a completed stage keeps its behaviour",
          plain["action"] != "relaunch", plain)
    rework = next_for([entry("S5-qa-automator-1", "never_started", rework_of="S5-qa-automator-0")],
                      stages=done)
    check_eq("a never-started rework dispatch is relaunchable whatever the stage's status",
             (rework["action"], rework.get("closed_dispatch_id")), ("relaunch", "S5-qa-automator-1"))
    for status in ("skipped", "pending", "running"):
        action = next_for([entry("S5-qa-automator-1", "never_started", rework_of="x")],
                          stages={"S5": {"status": status}})
        check_eq(f"and when the stage is {status}", action["action"], "relaunch")
    freed = next_for([entry("S5-qa-automator-1", "released_by_person", rework_of="x")], stages=done)
    check("a rework a person released is not relaunched on an accepted stage: that word asked for nothing",
          freed["action"] != "relaunch", freed)


def a_closed_story_is_never_told_to_start_work():
    """The exemption above is for a story somebody is still working on. On a CLOSED one (gate B
    decided, S8 done) `next` answered `relaunch` forever, and `validate` has no closed-story
    check, so work could start without the person's word - which `build_rework_request`
    refuses. Reopening stays the person's word: `release` / `rework --reason` write `reopened_at`."""
    done = {f"S{i}": {"status": "completed"} for i in range(9)}
    rework = entry("S5-qa-automator-2", "never_started", rework_of="S5-qa-automator-1")
    closed = {"closed_at": "2026-09-30T10:00:00+00:00"}
    action = next_for([rework], stages=done, pipeline=closed)
    check_eq("a never-started rework on a CLOSED story is not relaunched: `next` says closed",
             action["action"], "closed")
    open_story = next_for([rework], stages=done, pipeline=None)
    check_eq("the same state on a story that is not closed is relaunched",
             (open_story["action"], open_story.get("closed_dispatch_id")),
             ("relaunch", "S5-qa-automator-2"))
    reopened = next_for([rework], stages=done, pipeline=closed, reopened_at="2026-10-01T10:00:00+00:00")
    check_eq("and a story a person's word reopened is open again",
             reopened["action"], "relaunch")
    # What was NOT new stays as it was: an unfinished stage's never-started dispatch is relaunched
    # on a closed story too (the retro stage can still be open); the exemption added nothing here.
    pending = next_for([entry("S9-qa-retro-1", "never_started", stage="S9", role="qa-retro")],
                       stages=dict(done, S9={"status": "pending"}), pipeline=closed)
    check_eq("a never-started dispatch of a stage that is still open is judged as before",
             pending["action"], "relaunch")
    # A return that is still unsettled outranks `closed`, as it always did.
    held = next_for([entry("S5-qa-automator-1", "returned_unaccepted"), rework],
                    stages=done, pipeline=closed)
    check_eq("a return nobody settled is still the answer on a closed story, not a hidden one",
             (held["action"], held.get("dispatch_id")), ("resolve_return", "S5-qa-automator-1"))


def a_closed_story_holds_work_that_never_started():
    """B-331 (C1-6a, t-1151): a CLOSED story with an unfinished stage's dispatch that never reached an agent was told to
    `relaunch` it - the driver ran the role with no question. Now `next` answers `closed` and carries `held`: stage, role,
    reason, NO packet (a packet dispatched on a closed story is refused). The retro is the one stage that still runs."""
    done = {f"S{i}": {"status": "completed"} for i in range(6)}
    closed = {"closed_at": "2026-09-30T10:00:00+00:00"}
    never = entry("S6-qa-runner-1", "never_started", stage="S6", role="qa-runner", reason="the hook refused the call")
    stages = dict(done, S6={"status": "pending"}, S7={"status": "completed"}, S8={"status": "completed"})
    action = next_for([never], stages=stages, pipeline=closed)
    check_eq("an open stage's never-started dispatch on a CLOSED story is held, not relaunched: `next` says closed",
             action["action"], "closed")
    check_eq("`held` names the dispatch, its stage and role, and why it never started",
             action.get("held"), [{"dispatch_id": "S6-qa-runner-1", "stage": "S6", "role": "qa-runner",
                                   "reason": "the hook refused the call"}])
    check_not_in("and carries no packet: the packet's only road is a person's word", "dispatch_request", json.dumps(action))
    check_in("the reason tells the orchestrator the held work waits for a person", "held for a person's word", action["reason"])
    check_eq("the same state on a story that is NOT closed is relaunched and holds nothing",
             (next_for([never], stages=stages)["action"], "held" in next_for([never], stages=stages)), ("relaunch", False))
    check("nothing never-started: no `held` key at all (a finished story is just finished)",
          "held" not in next_for([entry("S5-qa-automator-1", "accepted")], stages=stages, pipeline=closed))

    # the retro is never held (J1's one exception); with the held question pending the retro stays pending and is flagged
    retro = entry("S9-qa-retro-1", "never_started", stage="S9", role="qa-retro")
    retro_open = dict(stages, S9={"status": "pending"})
    check_eq("S9 open on a closed story is relaunched, no question: the retro never needs a reopen",
             next_for([retro], stages=retro_open, pipeline=closed)["action"], "relaunch")
    both = next_for([never], stages=retro_open, pipeline=closed)
    check_eq("held AND retro pending: both ride on one `closed` action (the driver asks the held question first)",
             (both["action"], bool(both.get("held")), both.get("retro_pending"), both.get("stage")),
             ("closed", True, True, "S9"))

    # several held pieces of work: one list; the last dispatch of a stage+role stands for it
    many = next_for([entry("S5-qa-automator-1", "never_started", rework_of="S5-qa-automator-0"), never,
                     entry("S6-qa-runner-2", "never_started", stage="S6", role="qa-runner")],
                    stages=dict(stages, S5={"status": "completed"}), pipeline=closed)
    check_eq("several held dispatches are listed in one answer, a stage+role once (its last dispatch)",
             [h["dispatch_id"] for h in many["held"]], ["S5-qa-automator-1", "S6-qa-runner-2"])
    # a never-started rework of a completed stage was never relaunched on a closed story - now it is at least ASKED about
    check_eq("a never-started rework on a completed stage is held too (it was silently dropped before)",
             next_for([entry("S5-qa-automator-2", "never_started", rework_of="S5-qa-automator-1")], stages=done,
                      pipeline=closed)["held"][0]["dispatch_id"], "S5-qa-automator-2")
    check("a dispatch with no rework_of on a completed stage is history, not held",
          "held" not in next_for([entry("S5-qa-automator-2", "never_started")], stages=done, pipeline=closed))
    # Q1 (the Lead's answer, t-699 §12): a person's `release` freed the stage and asked for nothing; the question must not
    # offer a `leave` that `leave_unlaunched` refuses by name - so a RELEASED dispatch is NOT held, closed story or not
    freed = next_for([entry("S6-qa-runner-3", "released_by_person", stage="S6", role="qa-runner")], stages=stages, pipeline=closed)
    check_eq("a RELEASED dispatch of an open stage on a closed story is absent from `held`, and is not relaunched",
             ("held" in freed, freed["action"]), (False, "closed"))
    mixed = next_for([entry("S6-qa-runner-3", "released_by_person", stage="S6", role="qa-runner"),
                      entry("S5-qa-automator-4", "never_started", rework_of="S5-qa-automator-3")],
                     stages=dict(stages, S5={"status": "completed"}), pipeline=closed)
    check_eq("beside a never-started one, only the never-started one is held",
             [h["dispatch_id"] for h in mixed["held"]], ["S5-qa-automator-4"])

    # TEMPORAL: a story closed before `reopen_story` existed has no `reopened_at` and no covers: it is read as never reopened
    check_eq("a story closed before this change (no reopened_at, no covers) is held like any closed story",
             next_for([never], stages=stages, pipeline=closed)["action"], "closed")
    # after a person's reopen of the covered set: the covered is relaunched, a held dispatch the word did not name stays held
    other = entry("S5-qa-automator-2", "never_started", rework_of="S5-qa-automator-1")
    reopened = dict(reopened_at="2026-10-01T10:00:00+00:00", reopen_covers=["S6-qa-runner-1"],
                    reopen_left_held=["S5-qa-automator-2"])
    after = next_for([other, never], stages=stages, pipeline=closed, **reopened)
    check_eq("after a reopen the covered dispatch is relaunched one at a time ...",
             (after["action"], after.get("closed_dispatch_id")), ("relaunch", "S6-qa-runner-1"))
    only_left = next_for([other], stages=done, pipeline=closed, **reopened)
    check("... and the one the word left out is NOT relaunched, though the story is open again (a word covers only what it named)",
          only_left["action"] != "relaunch", only_left)
    # B1 (critic t-1182): the one the word left out STAYS HELD - it is asked about again, on the story that is open. The
    # `closed` action carries it as `held` (with the reopening beside the original `closed_at`), and it comes BEFORE the stage
    # loop's `prepare_stage S9` / `complete`. The pin that was missing: the half "not relaunched" held, "stays held" did not.
    check_eq("B1: the dispatch the word left out is listed as `held` on the open story (it keeps a door)",
             (only_left["action"], [h["dispatch_id"] for h in only_left.get("held") or []], bool(only_left.get("reopened_at"))),
             ("closed", ["S5-qa-automator-2"], True))
    check_eq("B1: once the covered work is done (nothing relaunchable left) the held one is asked again, not `prepare_stage S9`",
             next_for([other, entry("S6-qa-runner-1", "accepted", stage="S6", role="qa-runner")],
                      stages=dict(stages, S9={"status": "pending"}), pipeline=closed, **reopened)["action"], "closed")
    check_eq("B1: a later word that covers it removes it from `held`: the covered dispatch is relaunched again",
             next_for([other], stages=done, pipeline=closed,
                      **dict(reopened, reopen_covers=["S6-qa-runner-1", "S5-qa-automator-2"]))["action"], "relaunch")
    check("B1: an open story whose reopen left nothing out holds nothing",
          "held" not in next_for([other], stages=done, pipeline=closed, reopened_at="2026-10-01T10:00:00+00:00"))
    check_eq("a dispatch the reopen never listed (new work of the reopened story) is relaunched as before",
             next_for([entry("S6-qa-runner-9", "never_started", stage="S6", role="qa-runner")], stages=stages, pipeline=closed,
                      **reopened)["action"], "relaunch")
    check("B1: ... and it is never `held` (only the dispatches the word left out are)",
          "held" not in next_for([entry("S6-qa-runner-9", "never_started", stage="S6", role="qa-runner")], stages=stages,
                                 pipeline=closed, **reopened))
    # a RELEASED dispatch left out of a reopen is not relaunched either, and is never listed (a release asks for nothing: Q1)
    freed_left = next_for([entry("S6-qa-runner-3", "released_by_person", stage="S6", role="qa-runner")], stages=stages,
                          pipeline=closed, reopened_at="2026-10-01T10:00:00+00:00", reopen_covers=["S5-qa-automator-2"],
                          reopen_left_held=["S6-qa-runner-3"])
    check("B1 sibling: a RELEASED dispatch the reopen did not name is not relaunched, and not listed as held",
          freed_left["action"] != "relaunch" and "held" not in freed_left, freed_left)

    # FB1 / edge 3: a never-started retro beside held work is NOT relaunched before the held question is asked
    retro_first = next_for([retro, never], stages=retro_open, pipeline=closed)
    check_eq("FB1: held work AND a never-started retro: the held question comes first, the retro is not relaunched",
             (retro_first["action"], [h["dispatch_id"] for h in retro_first.get("held") or []]),
             ("closed", ["S6-qa-runner-1"]))
    check_eq("FB1: ... and with nothing held the same retro is relaunched (the retro never needs a reopen)",
             next_for([retro], stages=retro_open, pipeline=closed)["action"], "relaunch")
    after_leave = next_for([retro, entry("S6-qa-runner-1", "superseded", stage="S6", role="qa-runner", left_by_person="w")],
                           stages=retro_open, pipeline=closed)
    check_eq("FB1: ... and after the held work is left, the retro runs (the question's answer unblocks it)",
             (after_leave["action"], after_leave.get("closed_dispatch_id")), ("relaunch", "S9-qa-retro-1"))
    open_retro = next_for([retro, other], stages=retro_open, pipeline=closed, **reopened)
    check_eq("FB1: the same on a story a partial reopen opened: the retro waits for the held question",
             (open_retro["action"], [h["dispatch_id"] for h in open_retro.get("held") or []]), ("closed", ["S5-qa-automator-2"]))


def a_later_dispatch_hides_only_what_next_will_act_on():
    """B-312 hid an older dispatch behind ANY later one of its stage. A later dispatch `next`
    does not act on (never started on an accepted stage, released there, superseded, stale)
    then took the older one with it and a return was dropped silently: `await_gate`."""
    done = {f"S{i}": {"status": "completed"} for i in range(6)}
    done["S6"] = {"status": "pending"}
    old = entry("S5-qa-automator-3", "returned_unaccepted", rework_of="S5-qa-automator-2")
    probe = next_for([old, entry("S5-qa-code-critic-2", "never_started", role="qa-code-critic")],
                     stages=done)
    check_eq("a later never-started dispatch with no rework_of on a completed stage hides nothing: "
             "the return is still settled", (probe["action"], probe.get("dispatch_id")),
             ("resolve_return", "S5-qa-automator-3"))
    probe = next_for([old, entry("S5-qa-code-critic-2", "released_by_person", role="qa-code-critic")],
                     stages=done)
    check_eq("nor does a released one on a completed stage",
             (probe["action"], probe.get("dispatch_id")), ("resolve_return", "S5-qa-automator-3"))
    probe = next_for([old, entry("S5-qa-code-critic-2", "never_started", role="qa-code-critic",
                                 rework_of="S5-qa-automator-3")], stages=done)
    check_eq("a later never-started REWORK does hide it, because it is relaunched",
             (probe["action"], probe.get("closed_dispatch_id")), ("relaunch", "S5-qa-code-critic-2"))
    probe = next_for([old, entry("S5-qa-code-critic-2", "never_started", role="qa-code-critic",
                                 rework_of="S5-qa-automator-3")], stages=done,
                     pipeline={"closed_at": "2026-09-30T10:00:00+00:00"})
    check_eq("on a closed story that rework is not relaunched, so it hides nothing either",
             (probe["action"], probe.get("dispatch_id")), ("resolve_return", "S5-qa-automator-3"))

    # The invariant, over every pair: an older return or stop is either acted on itself or hidden
    # by a later dispatch that is. Nothing is dropped silently (FR-40, FR-42).
    older = ("returned_unaccepted", "abandoned", "blocked", "paused", "incomplete")
    later = ("never_started", "released_by_person", "returned_unaccepted", "abandoned", "blocked",
             "paused", "incomplete", "superseded", "stale")
    dropped = []
    for stage_status in ("pending", "completed"):
        for closed in (None, {"closed_at": "2026-09-30T10:00:00+00:00"}):
            for rework in (False, True):
                for first in older:
                    for second in later:
                        extra = {"rework_of": "S5-qa-automator-0"} if rework else {}
                        action = next_for(
                            [entry("S5-qa-automator-1", first, checkpoint={"remaining": ["TC-081"]}),
                             entry("S5-qa-code-critic-2", second, role="qa-code-critic",
                                   checkpoint={"remaining": ["TC-081"]}, **extra)],
                            stages={"S5": {"status": stage_status}}, pipeline=closed)
                        named = {action.get("dispatch_id"), action.get("closed_dispatch_id")}
                        if not named & {"S5-qa-automator-1", "S5-qa-code-critic-2"}:
                            dropped.append((stage_status, bool(closed), rework, first, second,
                                            action["action"]))
    check_eq("no return or stop is dropped silently, whatever came after it", dropped, [])


def a_never_started_rework_comes_back_whole_and_is_accepted_as_it_stands():
    root = temp_project("qa-resume-rework-relaunch-")
    try:
        controller = REWORK.designer_story(root)
        # The designer's S4 accepted and closed - what the legacy run had when S8 sent S4 back.
        controller.store.commit("stage_transition", {"stage": "S4", "status": "done",
                                                     "digest": "accepted"}, "k-s4-done",
                                project=controller.project)
        check_eq("the stage is accepted", controller.state()["stages"]["S4"]["status"], "completed")
        request = controller.build_rework_request(
            "S4", "qa-case-designer", ["TC-082"], "repair against the current canonical CaseVersion",
            cause="mechanical")
        controller.apply("dispatch", dict(request))
        controller.store.commit("state_repair", {"fixes": [{
            "kind": "never_started", "dispatch_id": request["id"], "stage": "S4",
            "role": "qa-case-designer", "digest": "", "reason": "recover: never launched"}],
            "reason": "recover closed dispatches nobody is doing"}, "k-never", project=controller.project)
        state = controller.state()
        check_eq("the rework never started", state["dispatches"][request["id"]]["status"], "never_started")
        check_eq("and the accepted stage kept its acceptance", state["stages"]["S4"]["status"], "completed")

        action = controller.next_action()
        check_eq("`next` names the relaunch, not a story that has nothing left", action["action"], "relaunch")
        packet = action["dispatch_request"]
        for key in ("rework_of", "repair_cause", "reason", "case_version_links"):
            check_eq(f"the packet carries the request's {key}", packet.get(key), request.get(key))
        check_eq("the packet names the dispatch it relaunches", packet["relaunch_of"], request["id"])
        check_eq("and passes the full dispatch validator",
                 REWORK.refusal(lambda: controller.validate("dispatch", packet, controller.state())), "")
        controller.apply("dispatch", json.loads(json.dumps(packet)))
        check_eq("and is dispatched as it stands",
                 controller.state()["dispatches"][packet["id"]]["status"], "running")
    finally:
        cleanup(root)


def a_quota_exhaustion_carries_no_packet():
    root = temp_project("qa-resume-quota-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller)
        block(controller, reason="INFRA/BUDGET_EXHAUSTED")
        action = controller.next_action()
        check("a hard quota exhaustion is offered no packet", "packet" not in action)
        check_in("and the reason says why", "not automatically retried", action.get("reason") or "")
        check_eq("recover offers none either", controller.recover()["retry_packets"], [])
    finally:
        cleanup(root)


def recover_prints_the_packet():
    root = temp_project("qa-resume-recover-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller)
        block(controller)
        before = len(controller.store.read())
        result = controller.recover()
        packets = result["retry_packets"]
        check_eq("recover prints one packet for the stopped dispatch", len(packets), 1)
        check_eq("naming the dispatch it resumes", packets[0]["dispatch_id"], SCOUT)
        check_eq("and it is the same packet `next` carries",
                 packets[0]["packet"], controller.next_action()["packet"])
        check_eq("recover journals nothing for a retry — that is the orchestrator's decision",
                 len(controller.store.read()), before)
        controller.apply("dispatch", json.loads(json.dumps(packets[0]["packet"])))
        check_eq("and the packet it printed is accepted as it stands",
                 controller.state()["dispatches"]["S1-qa-scout-2"]["status"], "running")
    finally:
        cleanup(root)


# --- (c) `accept` on the stopped dispatch says which id finishes the work -------------------

def accepting_a_stopped_dispatch_names_the_way_on():
    root = temp_project("qa-resume-accept-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller)
        block(controller)
        ref = evidence(root, "manifest.json")

        before = refused(lambda: controller.apply("accept", {
            "id": SCOUT, "status": "accepted", "evidence_refs": [ref],
            "idempotency_key": "a-before"}))
        check_not_in("the bare refusal of 2553 is gone",
                     "only the active dispatch can finish", before)
        check_in("the first way out is the retry", "--operation recover", before)
        check_in("the second is recording what is left", "--status incomplete", before)

        controller.apply("dispatch", json.loads(json.dumps(controller.next_action()["packet"])))
        after = refused(lambda: controller.apply("accept", {
            "id": SCOUT, "status": "accepted", "evidence_refs": [ref],
            "idempotency_key": "a-after"}))
        check_in("once the retry exists, the refusal names its id", "S1-qa-scout-2", after)
        check_in("and says to accept that one", "accept S1-qa-scout-2", after)
    finally:
        cleanup(root)


# --- (d) the host's id of the agent reaches pipeline.json ----------------------------------

def the_agent_id_reaches_the_pipeline():
    root = temp_project("qa-resume-agent-id-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller, agent_id="a301712c46df18269")
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("the id the host returned is on the stage the resume rule reads",
                 pipeline["stages"]["S1"].get("agent_id"), "a301712c46df18269")

        # It is known only after the Agent call returns, so a completion may carry it too.
        controller.apply("checkpoint", {"id": SCOUT, "status": "blocked", "reason": "waiting",
                                        "agent_id": "a3bb0091b2c125ccd",
                                        "checkpoint": {"remaining": ["TC-1"]},
                                        "idempotency_key": "cp-agent"})
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("and the last one the story learned wins",
                 pipeline["stages"]["S1"].get("agent_id"), "a3bb0091b2c125ccd")

        empty = refused(lambda: controller.apply("dispatch", {
            "id": "S1-qa-scout-9", "stage": "S1", "role": "qa-scout", "scope": ["TC-1"],
            "input_hash": "sources-1", "budget": {}, "known_paths": {}, "agent_id": "  ",
            "idempotency_key": "d-empty"}))
        check_in("a blank id is refused rather than recorded", "nonempty string", empty)
    finally:
        cleanup(root)


def a_story_without_the_field_projects_unchanged():
    root = temp_project("qa-resume-legacy-")
    try:
        controller = at_s1(root)
        dispatch_scout(controller)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check("a dispatch that carried no id invents none", "agent_id" not in pipeline["stages"]["S1"])

        # What `stage_done.py --agent-id` wrote on 0.7.x stays: the two routes share the field.
        pipeline["stages"]["S1"]["agent_id"] = "written-by-stage-done"
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        block(controller)
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("and a later projection keeps it",
                 pipeline["stages"]["S1"].get("agent_id"), "written-by-stage-done")
    finally:
        cleanup(root)


# --- (e) B-224: a resumed S4 designer is credited exactly as the original would have been ----

DESIGNER = "S4-qa-case-designer-1"


def designer_at_s4(root: Path, **extra) -> Controller:
    """S0..S3 accepted and an S4 designer running with an empty scope (as `stage_S4` opens it)."""
    mark_project(root)
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(4):
        BASE.accept_stage(controller, root, f"S{number}")
    controller.apply("dispatch", {"id": DESIGNER, "stage": "S4", "role": "qa-case-designer",
                                  "scope": [], "input_hash": "plan-1", "budget": {},
                                  "known_paths": {}, "idempotency_key": "d-" + DESIGNER, **extra})
    return controller


def a_resumed_designer_keeps_its_plan_rows():
    for label, extra, expected in (("rows", {"plan_rows": ["TS-1", "TS-2"]}, ["TS-1", "TS-2"]),
                                   ("an empty list", {"plan_rows": []}, [])):
        root = temp_project("qa-resume-rows-")
        try:
            controller = designer_at_s4(root, **extra)
            block(controller, DESIGNER)
            packet = controller.next_action().get("packet") or {}
            check_eq(f"the retry packet keeps {label}: present means present", packet.get("plan_rows"), expected)
            check("and the key is there even when the list is empty", "plan_rows" in packet)
            controller.apply("dispatch", json.loads(json.dumps(packet)))
            check_eq(f"the resumed dispatch records {label}",
                     controller.state()["dispatches"]["S4-qa-case-designer-2"].get("plan_rows"), expected)
            check_eq("a relaunch keeps them too",
                     Controller._relaunch_packet(controller.state(),
                                                 controller.state()["dispatches"][DESIGNER]).get("plan_rows"),
                     expected)
        finally:
            cleanup(root)
    root = temp_project("qa-resume-rows-legacy-")
    try:
        controller = designer_at_s4(root)
        block(controller, DESIGNER)
        packet = controller.next_action().get("packet") or {}
        check_not_in("a receipt made before the field gets none invented (absent means pre-change)",
                     "plan_rows", json.dumps(packet))
        check_not_in("nor does its relaunch packet", "plan_rows", json.dumps(
            Controller._relaunch_packet(controller.state(), controller.state()["dispatches"][DESIGNER])))
    finally:
        cleanup(root)


def main():
    an_evidence_refusal_names_the_path()
    a_stopped_dispatch_carries_its_retry_packet()
    a_replaced_checkpoint_gets_no_second_retry()
    a_newer_unlaunched_dispatch_outranks_an_older_return()
    later_work_of_the_stage_hides_what_it_replaced()
    a_never_started_rework_of_an_accepted_stage_is_relaunched()
    a_closed_story_is_never_told_to_start_work()
    a_closed_story_holds_work_that_never_started()
    a_later_dispatch_hides_only_what_next_will_act_on()
    a_never_started_rework_comes_back_whole_and_is_accepted_as_it_stands()
    a_quota_exhaustion_carries_no_packet()
    recover_prints_the_packet()
    accepting_a_stopped_dispatch_names_the_way_on()
    the_agent_id_reaches_the_pipeline()
    a_story_without_the_field_projects_unchanged()
    a_resumed_designer_keeps_its_plan_rows()
    finish("resume packet")


if __name__ == "__main__":
    main()
