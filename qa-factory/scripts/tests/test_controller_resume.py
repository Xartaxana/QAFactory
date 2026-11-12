#!/usr/bin/env python3
"""FB-4: a dispatch stopped for a person and continued by its own agent is running again (`resume`).

Keys of the spec t-1351: K-R1..K-R16 (the transition, the refusals, the replay, the lease), K-L1..K-L5 (`dispatch_life_key`),
K-B (the adversarial battery of the two CLIs), K-D1 (the docs name the command, with a negative control), K-N (`next`).
Controller in-process on a temp project; the CLIs through `harness.run_script`.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller as CTRL  # noqa: E402
from controller import Controller, dispatch_life_key  # noqa: E402

TICKET, D, AGENT = "QA-R1", "S0-qa-scout-1", "agent-A"
REASON = "source review awaiting the person"


def story(bind=True, pipeline=True):
    root = temp_project("qa-resume-")
    art = root / "qa-factory/artifacts" / TICKET
    art.mkdir(parents=True)
    if pipeline:
        (art / "pipeline.json").write_text(json.dumps({"task": TICKET, "stages": {"S0": {"status": "running"}}}), encoding="utf-8")
    c = Controller(art)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(art)}, "idempotency_key": "init"})
    c.apply("dispatch", {"id": D, "stage": "S0", "role": "qa-scout", "scope": ["TC-1"], "input_hash": "x", "budget": {},
                         "known_paths": {}, "idempotency_key": "d1"})
    if bind:
        c.store.commit("stage_transition", {"stage": "S0", "status": "running", "digest": "", "dispatch_id": D,
                                            "agent_id": AGENT}, "bind-1")
    return root, art, c


def stop(c, reason=REASON, status="blocked", remaining=None):
    req = c.build_checkpoint_request(D, status, reason, remaining)
    c.apply("checkpoint", req)
    return req


def refusal(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return ""


def rec(c, dispatch=D):
    return c.state()["dispatches"][dispatch]


def cli(root, *args):
    return harness.run_script("story_step.py", *args, cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def more_keys():
    """The keys of the critic's fix round t-1394 (F1-F8) that sit beside the spec's own."""
    # ---- F2 / K-R11: the rerun of `story_step resume` after the agent returned between the resume and the stage record
    root, art, c = story()
    try:
        stop(c)
        (art / "pipeline.json").write_text(json.dumps({"task": TICKET, "stages": {"S0": {"status": "halted"}}}), encoding="utf-8")
        c.apply("resume", c.build_resume_request(D))                  # the controller event landed; the stage record did not
        c.record_return(D, "second digest", AGENT)                    # ... and the agent returned before the rerun
        check_eq("F2: the record is returned_unaccepted before the rerun", rec(c)["status"], "returned_unaccepted")
        r = cli(root, "resume", "--task", TICKET, "--dispatch-id", D)
        stages = json.loads((art / "pipeline.json").read_text(encoding="utf-8")).get("stages") or {}
        check_eq("F2/K-R11: the rerun exits 0 and the stage is running (pipeline S0), not a loop of 'run again'",
                 (r.returncode, (stages.get("S0") or {}).get("status")), (0, "running"))
        check_not_in("F2: and it never says the stop changed", "changed since this request", r.stdout)
        again = cli(root, "resume", "--task", TICKET, "--dispatch-id", D)
        check_eq("F2/K-R11: a third run replays too", again.returncode, 0)
    finally:
        cleanup(root)

    # ---- F2 loop: the stage record cannot be written -> the refusal names a door that exists, once, with the exit code
    root, art, c = story()
    try:
        stop(c)
        c.apply("resume", c.build_resume_request(D))
        c.record_return(D, "second digest", AGENT)
        import argparse
        import contextlib
        import io
        import story_step
        real_run, real_env = story_step._run, os.environ.get("CLAUDE_PROJECT_DIR")
        story_step._run = lambda script, *a: (1, "stage_done: simulated refusal")     # the stage record cannot be written
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = story_step.resume(argparse.Namespace(task=TICKET, dispatch_id=D, agent_id=None))
        finally:
            story_step._run = real_run
            if real_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = real_env
        text = out.getvalue()
        check("F2: a failing stage record on a returned record names `finish`, never 'run this command again'",
              code == 1 and "story_step.py finish" in text and "run this command again" not in text, text[-400:])
    finally:
        cleanup(root)

    # ---- F3 / K-N: `where` carries the command too (one decorator for next and where)
    root, art, c = story()
    try:
        stop(c)
        r = cli(root, "where", "--task", TICKET)
        check_in("F3/K-N: where carries resume_command", f'"resume_command": "story_step.py resume --task {TICKET} --dispatch-id {D}"', r.stdout)
    finally:
        cleanup(root)
    root, art, c = story(bind=False)
    try:
        stop(c)
        check_not_in("F3/K-N: where, no agent recorded: no resume_command", "resume_command", cli(root, "where", "--task", TICKET).stdout)
    finally:
        cleanup(root)

    # ---- F5: the resume BINDS an id the record never had; a record that had one keeps it as it was
    root, art, c = story(bind=False)
    try:
        stop(c)
        c.apply("resume", c.build_resume_request(D, "agent-X"))
        d = rec(c)
        check_eq("F5: an id the record never had is a bind (stamped)", (d["agent_id"], d.get("agent_bound_seq") is not None), ("agent-X", True))
        import contract
        check_eq("F5: request_agent_id reads it as a bind, not as the parent's agent", contract.request_agent_id(d), "")
    finally:
        cleanup(root)
    root, art, c = story()
    try:
        stop(c)
        before = rec(c).get("agent_bound_seq")
        c.apply("resume", c.build_resume_request(D))
        check_eq("F5: a record that had the id keeps its stamp", rec(c).get("agent_bound_seq"), before)
    finally:
        cleanup(root)

    # ---- F6: one head for the two refusals of a superseded dispatch
    root, art, c = story()
    try:
        stop(c)
        retry = Controller._retry_packet(c.state(), rec(c))
        c.apply("dispatch", dict(retry, idempotency_key="dispatch:retry"))
        head = f"{D} is superseded: {retry['id']} is its retry and holds this work now; "
        check_in("F6: accept on the parent: the shared head, its own door", head + f"accept {retry['id']}",
                 refusal(lambda: c.apply("accept", {"id": D, "status": "accepted", "evidence_refs": [], "idempotency_key": "a9"})))
        check_in("F6: resume on the parent: the shared head, its own door", head + f"finish or pause {retry['id']}",
                 refusal(lambda: c.apply("resume", c.build_resume_request(D))))
    finally:
        cleanup(root)

    # ---- K-R5: each status its door, revision unchanged (records imported with the status; no event is written by a refusal)
    root = temp_project("qa-resume-")
    art = root / "qa-factory/artifacts" / TICKET
    art.mkdir(parents=True)
    (art / "pipeline.json").write_text(json.dumps({"task": TICKET}), encoding="utf-8")
    c = Controller(art)
    try:
        legacy = {f"S0-{s}": {"id": f"S0-{s}", "stage": "S0", "role": "qa-scout", "status": s, "agent_id": AGENT, "imported": True}
                  for s in ("superseded", "never_started", "released_by_person", "accepted", "stale")}
        c.store.commit("initialize", {"scope": ["TC-1"], "source_revision": "s", "known_paths": {"root": str(art)},
                                      "coverage_contract_version": 2, "plan_contract_mode": "new", "host_capabilities": [],
                                      "legacy_import": {"stages": {}, "dispatches": legacy, "decisions": {}}}, "init-legacy")
        rev = c.state()["revision"]
        for status, door in (("superseded", "prints what holds the stage now"), ("never_started", "relaunch packet"),
                             ("released_by_person", "relaunch packet"), ("accepted", "--operation rework"), ("stale", "--operation rework")):
            text = refusal(lambda: c.build_resume_request(f"S0-{status}"))
            check_in(f"K-R5: {status}: its own door", door, text)
        check_eq("K-R5: the five refusals wrote nothing", c.state()["revision"], rev)
    finally:
        cleanup(root)

    # ---- K-R7 / E26: resume is refused while the independent code critic runs, and allowed after it returned
    root, art, c = story()
    try:
        stop(c)
        c.apply("dispatch", {"id": "S0-critic-1", "stage": "S0", "role": "qa-code-critic", "scope": ["TC-1"], "input_hash": "y",
                             "budget": {}, "known_paths": {}, "idempotency_key": "d-crit"})
        check_in("K-R7/E26: the critic runs: resume refused naming it", "S0-critic-1", refusal(lambda: c.apply("resume", c.build_resume_request(D))))
        c.record_return("S0-critic-1", "verdict", "agent-C")
        c.apply("resume", c.build_resume_request(D))
        check_eq("K-R7/E26: after the critic returned, the author resumes", rec(c)["status"], "running")
    finally:
        cleanup(root)

    # ---- K-L5: a life-1 fix's state_repair key differs from the life-0 fix's
    root, art, c = story()
    try:
        import dispatch_liveness
        real = dispatch_liveness.state
        dispatch_liveness.state = lambda *a, **k: {"state": "abandoned", "evidence": ["e"]}
        try:
            zero = c.liveness_fixes()
            c.apply("checkpoint", c.build_checkpoint_request(D, "blocked", REASON))
            c.apply("resume", c.build_resume_request(D))
            one = c.liveness_fixes()
        finally:
            dispatch_liveness.state = real
        check_eq("K-L5: a life-0 fix has no `life` (today's bytes)", [("life" in f) for f in zero], [False])
        check("K-L5: the state_repair keys differ", CTRL.content_hash(zero) != CTRL.content_hash(one), (zero, one))
    finally:
        cleanup(root)

    # ---- K-R14: the clause is FIRST and the old text follows it byte-equal; incomplete and no agent: today's text
    def texts(bind, status):
        root, art, c = story(bind=bind)
        try:
            stop(c, status=status)
            accept = refusal(lambda: c.apply("accept", {"id": D, "status": "accepted", "evidence_refs": [], "idempotency_key": "a3"}))
            ckpt = refusal(lambda: c.apply("checkpoint", c.build_checkpoint_request(D, "blocked", "again")))
            return accept.replace(str(art), "<R>"), ckpt.replace(str(art), "<R>")
        finally:
            cleanup(root)
    with_acc, with_ckpt = texts(True, "blocked")
    without_acc, without_ckpt = texts(False, "blocked")
    clause = f"if the same agent continued it: `story_step.py resume --task {TICKET} --dispatch-id {D}`, then run this again; else "
    check("K-R14: accept: the clause first, the old text byte-equal after it", with_acc == "StateConflict: " + clause + without_acc[len("StateConflict: "):], (with_acc, without_acc))
    check("K-R14: the checkpoint op: the clause first, the old text byte-equal after it", with_ckpt == "StateConflict: " + clause + without_ckpt[len("StateConflict: "):], (with_ckpt, without_ckpt))
    inc_acc, inc_ckpt = texts(True, "incomplete")
    no_clause_acc, no_clause_ckpt = texts(False, "incomplete")
    check_eq("K-R14: incomplete with an agent: byte-equal to today (no clause)", (inc_acc, inc_ckpt), (no_clause_acc, no_clause_ckpt))

    # ---- K-B: the rest of the CLI battery
    root, art, c = story()
    try:
        stop(c)
        for label, value in (("blank", "   "),):
            r = cli(root, "resume", "--task", TICKET, "--dispatch-id", D, "--agent-id", value)
            check_eq(f"K-B: story_step resume --agent-id {label}: exit 2, the shape refusal, nothing written",
                     (r.returncode, "agent_id is the host's own id" in r.stdout + r.stderr, rec(c)["status"]), (2, True, "blocked"))
        r = cli(root, "resume", "--task", TICKET, "--dispatch-id", D, "--agent-id", " " + AGENT)
        check_eq("K-B: story_step resume --agent-id ' A' with the recorded A: accepted (stripped)", (r.returncode, rec(c)["status"]), (0, "running"))
        stop(c, "again")
        run = harness.run_script("controller.py", "--task-root", str(art), "--operation", "resume", "--dispatch", "",
                                 cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        check_eq("K-B: controller.py --operation resume --dispatch '': exit 2, names the field, nothing written",
                 (run.returncode, "--dispatch-id names the dispatch" in run.stdout + run.stderr, rec(c)["status"]), (2, True, "blocked"))
    finally:
        cleanup(root)


def main():
    # ---- K-R1 / K-R2 / K-R3 / K-R4 / K-L1 / K-L2
    root, art, c = story()
    try:
        c.record_return(D, "review digest", "agent-A")
        first = stop(c, remaining="decide the stand; decide the video")
        d = rec(c)
        check_eq("K-R1 pre: blocked, the first life's return is on the record", (d["status"], d.get("returned_digest")), ("blocked", "review digest"))
        check_in("K-R2 pre: accept refused with the resume FIRST", "story_step.py resume --task QA-R1 --dispatch-id " + D,
                 refusal(lambda: c.apply("accept", {"id": D, "status": "accepted", "evidence_refs": [], "idempotency_key": "a0"})))
        check_in("K-R14: the old text follows the clause", "a stopped dispatch is not accepted where it stands",
                 refusal(lambda: c.apply("accept", {"id": D, "status": "accepted", "evidence_refs": [], "idempotency_key": "a0b"})))
        req = c.build_resume_request(D)
        check_eq("K-R1: the request is flags-built from the journal", sorted(req), sorted(
            ["id", "stop_sequence", "agent_id", "stage", "role", "expected_revision", "idempotency_key"]))
        c.apply("resume", req)
        d, stage = rec(c), c.state()["stages"]["S0"]
        check_eq("K-R1: the SAME dispatch is running", (d["status"], d["id"]), ("running", D))
        check_eq("K-R1: the stop and the first return moved into resumes[0]",
                 {k: d["resumes"][0].get(k) for k in ("from_status", "reason", "returned_digest")},
                 {"from_status": "blocked", "reason": REASON, "returned_digest": "review digest"})
        check_eq("K-R1: the live record has no checkpoint/reason/returned_*", [k for k in ("checkpoint", "reason", "returned_digest", "returned_at", "returned_by") if k in d], [])
        check_eq("K-R1: the stage is running", stage["status"], "running")
        check_eq("K-L1/L2: one resume, suffix :r1", dispatch_life_key(d), ":r1")
        # E11 / K-R3: a second pause with the SAME reason is a new event
        before = c.state()["revision"]
        second = stop(c)
        check("K-R3: the second key ends :r1 and differs", second["idempotency_key"] != first["idempotency_key"] and ":r1:" in second["idempotency_key"], second["idempotency_key"])
        check_eq("K-R3: blocked again, recorded (not replayed)", (rec(c)["status"], c.state()["revision"] > before), ("blocked", True))
        check_eq("K-R4: the second checkpoint carries only its own remaining", rec(c)["checkpoint"]["remaining"], [REASON])
        # K-R9c: the first resume's exact request replays its stored receipt; the record stays blocked
        c.apply("resume", dict(req))
        check_eq("K-R9c: a replay of the first resume leaves the record blocked", rec(c)["status"], "blocked")
        r = cli(root, "resume", "--task", TICKET, "--dispatch-id", D)
        check_eq("K-R9c: story_step resume resumes the NEW stop", (r.returncode, rec(c)["status"], dispatch_life_key(rec(c))), (0, "running", ":r2"))
        check_in("K-R11: says what it did", f"resumed {D} (blocked)", r.stdout)
        check_in("K-R11: and where to go on", "story_step.py finish --task " + TICKET, r.stdout)
        again = cli(root, "resume", "--task", TICKET, "--dispatch-id", D)
        check_eq("K-R11/E9: a rerun after success replays the event and exits 0, still running", (again.returncode, rec(c)["status"], len(rec(c)["resumes"])), (0, "running", 2))
        # K-R2: accept after the resume is taken (no evidence needed to pass validation of the status check: it reaches the evidence check)
        text = refusal(lambda: c.apply("accept", {"id": D, "status": "accepted", "evidence_refs": [], "idempotency_key": "a1"}))
        check_not_in("K-R2: accept on the resumed dispatch no longer says stopped", "stopped dispatch", text)
        # K-L4: a second return is journaled
        check_eq("K-L4: second return journaled", (c.record_return(D, "second digest", "agent-A"), rec(c)["status"], rec(c)["returned_digest"]),
                 (True, "returned_unaccepted", "second digest"))
    finally:
        cleanup(root)

    # ---- K-L1 AT: no resume, byte-equal keys
    root, art, c = story()
    try:
        req = c.build_checkpoint_request(D, "blocked", REASON)
        check("K-L1: key at zero resumes is today's (no suffix)", re.fullmatch(r"checkpoint:S0-qa-scout-1:[0-9a-f]{64}", req["idempotency_key"]) is not None, req["idempotency_key"])
        check_eq("K-L1: no life suffix", ":r" in req["idempotency_key"], False)
        for crooked in ({}, "x", [], None, "str", 5, {"resumes": {}}, {"resumes": "x"}, {"resumes": []}):
            check_eq(f"K-L3: dispatch_life_key({crooked!r}) never raises, is empty", dispatch_life_key(crooked), "")
        check_eq("K-L2: BEYOND (two resumes)", dispatch_life_key({"resumes": [1, 2]}), ":r2")
        fixes_off = c.liveness_fixes()
        check_eq("K-L5: a never-resumed dispatch gets no life field", [f for f in fixes_off if "life" in f], [])
        import dispatch_liveness
        real = dispatch_liveness.state
        dispatch_liveness.state = lambda *a, **k: {"state": "abandoned", "evidence": ["e"]}
        try:
            c.apply("checkpoint", c.build_checkpoint_request(D, "blocked", REASON))
            c.apply("resume", c.build_resume_request(D, AGENT))
            fixes_on = c.liveness_fixes()
        finally:
            dispatch_liveness.state = real
        check_eq("K-L5: a life-1 fix carries life :r1", [f.get("life") for f in fixes_on], [":r1"])
    finally:
        cleanup(root)

    # ---- K-R5 per status, K-R6 agents, K-R7 other running, K-R8 budget, K-R9 stale, K-R9b, K-R10
    root, art, c = story()
    try:
        r5 = refusal(lambda: c.build_resume_request(D))
        check_in("K-R5: running: it is not stopped, door finish/pause", "it is not stopped", r5)
        stop(c, status="incomplete")
        rev5 = c.state()["revision"]
        check_in("K-R5: incomplete: the retry packet", "--operation recover", refusal(lambda: c.apply("resume", c.build_resume_request(D))))
        check_in("K-B: empty id names the field and the ids", "--dispatch-id names the dispatch", refusal(lambda: c.build_resume_request("")) )
        check_in("K-B: unknown id with escapes", "unknown dispatch", refusal(lambda: c.build_resume_request("S1-" + "".join(map(chr, (0x441, 0x43a, 0x430, 0x443, 0x442))) + "-1")))
        check_in("K-B: unknown id with an astral char", "unknown dispatch", refusal(lambda: c.build_resume_request("S1-\U0001F600")))
        check_eq("K-R5: nothing written by the refusals", c.state()["revision"], rev5)
    finally:
        cleanup(root)

    root, art, c = story()
    try:
        stop(c)
        rev = c.state()["revision"]
        check_in("K-B: blank --agent-id: the shape refusal", "agent_id is the host's own id",
                 refusal(lambda: c.apply("resume", c.build_resume_request(D, "   "))))
        check_in("K-R6: another agent is a new dispatch", "a different agent is a new dispatch",
                 refusal(lambda: c.apply("resume", c.build_resume_request(D, "agent-B"))))
        check_eq("K-R6: refusals wrote nothing", c.state()["revision"], rev)
        # a wide agent id equal to the recorded one, padded: the SAME agent
        c.apply("resume", c.build_resume_request(D, "  " + AGENT + " "))
        check_eq("K-R6/M20: a padded agent is the same agent", rec(c)["status"], "running")
        check_eq("K-R6: the recorded agent is kept stripped", rec(c)["agent_id"], AGENT)
    finally:
        cleanup(root)

    root, art, c = story(bind=False)
    try:
        stop(c)
        text = refusal(lambda: c.apply("resume", c.build_resume_request(D)))
        check_in("K-R6: no agent recorded nor given: refused with the door", "has no recorded agent", text)
        c.apply("resume", c.build_resume_request(D, "x" * 4096))
        check_eq("K-B: a 4096-char agent id is accepted (no limit introduced)", len(rec(c)["agent_id"]), 4096)
    finally:
        cleanup(root)

    root, art, c = story()
    try:
        stop(c)
        c.apply("dispatch", {"id": "S0-other-1", "stage": "S0", "role": "qa-other", "scope": ["TC-1"], "input_hash": "y", "budget": {},
                             "known_paths": {}, "idempotency_key": "d2"})
        text = refusal(lambda: c.apply("resume", c.build_resume_request(D)))
        check_in("K-R7: another dispatch runs: refused", "sequential task already has an active dispatch: S0-other-1", text)
        check_eq("K-R7: the record is still blocked", rec(c)["status"], "blocked")
        # K-R9: a hand-made stale request with its own fresh key
        good = c.build_resume_request(D)
        stale = dict(good, stop_sequence=1, idempotency_key="resume:" + D + ":stale-test")
        check_in("K-R9: a stale stop_sequence is refused", "stale stop", refusal(lambda: c.validate("resume", stale, c.state())))
        none = {k: v for k, v in good.items() if k != "stop_sequence"}
        check_in("K-R9: a request with no stop_sequence is refused", "stale stop", refusal(lambda: c.validate("resume", none, c.state())))
        check_in("K-R7: both problems at once (numbered)", "2)", refusal(lambda: c.validate("resume", stale, c.state())))
    finally:
        cleanup(root)

    root, art, c = story()
    try:
        c.apply("checkpoint", dict(c.build_checkpoint_request(D, "blocked", "q"), reason="INFRA/BUDGET_EXHAUSTED"))
        check_in("K-R8: budget exhaustion is not resumed", "hard quota exhaustion", refusal(lambda: c.apply("resume", c.build_resume_request(D))))
    finally:
        cleanup(root)

    # K-R9b: a STOPPED record with no checkpoint event (state_repair-set legacy shape)
    root, art, c = story()
    try:
        c.store.commit("state_repair", {"fixes": [{"kind": "abandoned", "dispatch_id": D, "stage": "S0", "digest": "", "reason": "r"}]}, "rep-1")
        rev = c.state()["revision"]
        text = refusal(lambda: c.build_resume_request(D))
        check("K-R9b: abandoned: refused with the door of its status, no event", "pause" in text and c.state()["revision"] == rev, text)
    finally:
        cleanup(root)
    root = temp_project("qa-resume-")
    art = root / "qa-factory/artifacts" / TICKET
    art.mkdir(parents=True)
    (art / "pipeline.json").write_text(json.dumps({"task": TICKET}), encoding="utf-8")
    c = Controller(art)
    try:
        legacy = {"id": "S0-legacy", "stage": "S0", "role": "qa-scout", "status": "blocked", "agent_id": AGENT, "imported": True}
        c.store.commit("initialize", {"scope": ["TC-1"], "source_revision": "s", "known_paths": {"root": str(art)},
                                      "coverage_contract_version": 2, "plan_contract_mode": "new", "host_capabilities": [],
                                      "legacy_import": {"stages": {}, "dispatches": {"S0-legacy": legacy}, "decisions": {}}}, "init-legacy")
        rev = c.state()["revision"]
        text = refusal(lambda: c.build_resume_request("S0-legacy"))
        check("K-R9b: a STOPPED record with no checkpoint event: 'no recorded stop', retry door, no event",
              "no recorded stop to resume" in text and "--operation recover" in text and c.state()["revision"] == rev, text)
    finally:
        cleanup(root)

    # K-R10: a closed story (closure is read by the ONE test `_closed_dispatch_refusal`; the state alone decides, ruling 1)
    root, art, c = story(pipeline=False)
    try:
        stop(c)
        (art / "pipeline.json").write_text(json.dumps({"task": TICKET, "closed_at": "2026-10-01T00:00:00"}), encoding="utf-8")
        text = refusal(lambda: c.apply("resume", c.build_resume_request(D)))
        # A paused dispatch is neither held (reopen_story refuses it: "not held back") nor accepted (rework refuses it), so
        # no door opens for it and the refusal names none (FR-2: only doors that open, executed on this state).
        check_in("K-R10: a closed story: refused, and the refusal says no door opens", "No door opens", text)
        check_not_in("K-R10: and names neither reopen_story nor rework (both are refused on a paused dispatch)", "reopen_story", text)
        check_not_in("K-R10: not rework", "--operation rework", text)
        check_eq("K-R10: nothing written, still blocked", rec(c)["status"], "blocked")
    finally:
        cleanup(root)

    # F1: the retro S9 is exempt (as for a dispatch); a file nobody can read is read by the state alone
    def stopped_in(stage, role, pipeline_text, closed_state=False):
        root = temp_project("qa-resume-")
        art = root / "qa-factory/artifacts" / TICKET
        art.mkdir(parents=True)
        (art / "pipeline.json").write_text(json.dumps({"task": TICKET}), encoding="utf-8")
        c = Controller(art)
        did = f"{stage}-{role}-1"
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(art)}, "idempotency_key": "init"})
        # committed without `validate`: the prior-stage guard is not what this key is about
        c.store.commit("dispatch", {"id": did, "stage": stage, "role": role, "scope": ["TC-1"], "input_hash": "x", "budget": {},
                                    "known_paths": {}}, "d1")
        c.store.commit("stage_transition", {"stage": stage, "status": "running", "digest": "", "dispatch_id": did, "agent_id": AGENT}, "bind-1")
        c.apply("checkpoint", c.build_checkpoint_request(did, "paused", REASON))
        if closed_state:    # gate B decided and S8 done, in the controller's own state
            c.store.commit("decision", {"id": "gate-B-1", "gate": "B", "status": "approved"}, "gate-b")
            c.store.commit("stage_transition", {"stage": "S8", "status": "completed", "digest": ""}, "s8-done")
        (art / "pipeline.json").write_text(pipeline_text, encoding="utf-8")    # the file as the case wants it, after the setup read it
        return root, c, did
    closed_json = json.dumps({"task": TICKET, "closed_at": "2026-10-01T00:00:00"})
    root, c, did = stopped_in("S9", "qa-retro", closed_json)
    try:
        c.apply("resume", c.build_resume_request(did))
        check_eq("F1/K-R10: a paused S9 retro on a closed story RESUMES", rec(c, did)["status"], "running")
    finally:
        cleanup(root)
    root, c, did = stopped_in("S5", "qa-automator", closed_json)
    try:
        text = refusal(lambda: c.apply("resume", c.build_resume_request(did)))
        check("F1/K-R10: a paused S5 dispatch on a closed story: refused, no door named that would be refused, record untouched",
              "No door opens" in text and "reopen_story" not in text and "--operation rework" not in text
              and rec(c, did)["status"] == "paused", text)
    finally:
        cleanup(root)
    root, c, did = stopped_in("S5", "qa-automator", "{not json", closed_state=True)
    try:
        text = refusal(lambda: c.apply("resume", c.build_resume_request(did)))
        check("F1/E21: unreadable pipeline.json + CLOSED state: refused (the state alone decides)",
              "No door opens" in text and rec(c, did)["status"] == "paused", text)
    finally:
        cleanup(root)
    root, c, did = stopped_in("S5", "qa-automator", "{not json")
    try:
        c.apply("resume", c.build_resume_request(did))
        check_eq("F1/E21: unreadable pipeline.json + OPEN state: resumed (no dead end)", rec(c, did)["status"], "running")
    finally:
        cleanup(root)

    # K-R13: retry after resume refused; resume after retry names the retry
    root, art, c = story()
    try:
        stop(c)
        c.apply("resume", c.build_resume_request(D))
        packet = Controller._retry_packet(c.state(), dict(rec(c), checkpoint=rec(c).get("checkpoint")))
        check_in("K-R13: a retry packet after a resume is refused (the dispatch runs)", "sequential task already has an active dispatch",
                 refusal(lambda: c.apply("dispatch", dict(packet or {"id": "S1-qa-scout-2", "stage": "S0", "role": "qa-scout"}, parent_retry=D, idempotency_key="r1"))))
    finally:
        cleanup(root)
    root, art, c = story()
    try:
        stop(c)
        retry = Controller._retry_packet(c.state(), rec(c))
        c.apply("dispatch", dict(retry, idempotency_key="dispatch:retry"))
        text = refusal(lambda: c.apply("resume", c.build_resume_request(D)))
        check_in("K-R13/E3: resume after a retry names the retry", f"{retry['id']} is its retry", text)
    finally:
        cleanup(root)

    # K-R14: without an agent, the old text is byte-equal to today's (no clause); K-R15 lease; K-R16 reuse door
    root, art, c = story(bind=False)
    try:
        stop(c)
        text = refusal(lambda: c.apply("accept", {"id": D, "status": "accepted", "evidence_refs": [], "idempotency_key": "a2"}))
        check_not_in("K-R14: no agent recorded: no clause", "story_step.py resume", text)
    finally:
        cleanup(root)
    root, art, c = story()
    try:
        stop(c)
        c.store.commit("handoff", {"lease": {"owner_session_id": "s-2"}}, "h1")
        check_in("K-R15: a hand request without the owner is refused by apply", "orchestrator lease",
                 refusal(lambda: c.apply("resume", {k: v for k, v in c.build_resume_request(D).items() if k != "owner_session_id"})))
        check_eq("K-R15: the built request carries the owner", c.build_resume_request(D).get("owner_session_id"), "s-2")
        r = cli(root, "resume", "--task", TICKET, "--dispatch-id", D)
        check_eq("K-R15: story_step resume under a lease is accepted", (r.returncode, rec(c)["status"]), (0, "running"))
        # K-R16: the same key with another agent is the reuse refusal and story_step appends the retry door
        stop(c, "second")
        c.apply("resume", c.build_resume_request(D))
        r = cli(root, "resume", "--task", TICKET, "--dispatch-id", D, "--agent-id", "agent-B")
        check_eq("K-R16: a rerun with another agent: exit 2", r.returncode, 2)
        check_in("K-R16: and the retry door is appended", "a different agent is a new dispatch: the retry packet", r.stdout)
        # K-R12: stage_done --status running alone leaves the dispatch STOPPED (E23)
        stop(c, "third")
        sd = harness.run_script("stage_done.py", "--task", TICKET, "--stage", "S0", "--status", "running", "--role", "qa-scout",
                                cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        check_eq("K-R12: stage_done running alone does not move the dispatch", (sd.returncode, rec(c)["status"]), (0, "blocked"))
    finally:
        cleanup(root)

    # ---- K-N: next carries resume_command (F-9)
    root, art, c = story()
    try:
        stop(c)
        action = c.next_action()
        check_eq("K-N: next is resume_checkpoint with the command",
                 (action.get("action"), action.get("resume_command")), ("resume_checkpoint", f"story_step.py resume --task {TICKET} --dispatch-id {D}"))
        check("K-N: the retry packet is still offered beside it", bool(action.get("packet")))
    finally:
        cleanup(root)
    root, art, c = story(bind=False)
    try:
        stop(c)
        check_not_in("K-N: no agent recorded: no resume_command", "resume_command", json.dumps(c.next_action()))
    finally:
        cleanup(root)

    # ---- K-B: the CLIs
    root, art, c = story()
    try:
        stop(c)
        f = art / "x.json"
        f.write_text("{}", encoding="utf-8")
        run = harness.run_script("controller.py", "--task-root", str(art), "--operation", "resume", "--input", str(f), "--dispatch", D,
                                 cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        check_eq("K-B: --input is refused", run.returncode, 2)
        check_in("K-B: and names story_step.py resume", "story_step.py resume", run.stderr + run.stdout)
        check_eq("K-B: nothing written", rec(c)["status"], "blocked")
        run = harness.run_script("controller.py", "--task-root", str(art), "--operation", "resume", "--dispatch", D,
                                 cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        out = json.loads(run.stdout.strip().splitlines()[-1]) if run.stdout.strip() else {}
        check_eq("K-R1/FR-14: the CLI answer has the flag-built shape", (run.returncode, sorted(out)), (0, ["next_action", "receipt", "recorded", "request"]))
        check_eq("K-B: the CLI resumed it", rec(c)["status"], "running")
        r = cli(root, "resume", "--task", TICKET, "--dispatch-id", "")
        check_eq("K-B: story_step resume with an empty id: exit 2", r.returncode, 2)
        r = cli(root, "resume", "--task", TICKET, "--dispatch-id", "S1-\U0001F600")
        check_eq("K-B: story_step resume with an astral id: exit 2, no traceback", (r.returncode, "Traceback" in r.stderr), (2, False))
    finally:
        cleanup(root)

    more_keys()

    # ---- K-D1: the walk of design/state-exits.md names `resume` and this test (the AR-25 exit proof); the role texts
    # that name the command are rows of design/role-rules.json
    walk = (harness.PLUGIN_ROOT / "design/state-exits.md").read_text(encoding="utf-8")
    check("K-D1: design/state-exits.md names `resume` and this test", "`resume`" in walk and "test_controller_resume.py" in walk)
    finish("test_controller_resume")


if __name__ == "__main__":
    main()
