#!/usr/bin/env python3
"""HF8-15 (2): `story_step.py finish --needs-author` - the S5 critic that cannot judge because its AUTHOR's work is defective.

Run 12586 (29.10.2026) and 14857 (30.10): the critic of a window ran, the author's fixture was the defect, and the controller had no
move: `rework` was refused ("active dispatch"), `finish --not-complete` and `checkpoint` too; the conductor went round the controller
with a message to the closed author. Here the move is exercised on a story at S5 (author accepted, critic running - the fixture of
`test_window_record.py`), from the refusal the conductor meets, through the real commands, to the critic's retry.

Keys (the spec's K1-n, docs/tasks/specs/r0107-s3b2-hf8-15-sc2-38.md section 3.3):
K1-1 the scenario of the finding; K1-2 the author's finish names the critic's retry, the retry goes through to the end;
K1-3 the refused inputs (E1, E2, E3, E4, E5, E11, E14) leave controller.json byte for byte; `finish` with neither digest nor
needs-author is a refusal with a form; K1-4 the veto of a worker not proved returned (E6) and its positive control;
K1-5 E7 and E8 before any record; K1-6 the critic's repair ledger does not grow, `accept` is never called;
K1-7 E9 / E10 and the cap (E12): the probe sees what `dispatch` will refuse; K1-8 the text of the old refusal and the data row;
K1-9 a receipt that carries a path (Codex shape).

KILLS (one narrow key each, never run here - the batch canon runs them): accept instead of checkpoint -> K1-6; the probe removed -> K1-5;
the scope check removed -> K1-3; the branch after `_halt_gate` -> K1-1; `_release_binding` removed -> K1-2; no E9 branch -> K1-7;
a probe that is only `build_rework_request` -> K1-7; the role not checked -> K1-3; the :4690 text without the critic condition -> K1-8.
"""
import argparse
import contextlib
import copy
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CTL  # noqa: E402
import host_dispatch as HD  # noqa: E402
import story_step  # noqa: E402
from controller import Controller, repair_ledger  # noqa: E402

import test_window_record as TW  # noqa: E402  (a story at S5: the author accepted, the critic running)

TICKET, AUTHOR, CRITIC = TW.TICKET, TW.AUTHOR, TW.CRITIC
AGENT = "agent-author-1"
SENTINEL = "SG-needs-author-probe"


# --- fixtures -------------------------------------------------------------------------------------------------------------

def story(prefix="qa-needs-author-", agent=AGENT):
    """(project, task, controller): the story of `test_window_record`, and the author's record knows its host agent (the fixture's
    dispatch carries none; S5 resumes the author, so the rework request carries the id and `_needs_author` must bind it)."""
    project = temp_project(prefix)
    use_project(project)
    real = Controller.apply

    def with_agent(self, operation, request):
        # The state is a projection of the journal: the id goes on the REQUEST of the author's dispatch, as `bind` / the host does.
        if agent and operation == "dispatch" and request.get("id") == AUTHOR:
            request = dict(request, agent_id=agent)
        return real(self, operation, request)
    with mock.patch.object(Controller, "apply", with_agent):
        task, controller = TW.a_story_at_s5(project)
    return project, task, Controller(task)


def args(**over):
    base = dict(task=TICKET, dispatch_id=CRITIC, digest=None, needs_author="TC-1", reason="the fixture races the page",
                cause=None, output=None, not_complete=False, complete=False, ignore_handoff=False, window=None,
                unresolved=None, wait_seconds=0.0)
    base.update(over)
    return argparse.Namespace(**base)


def run(**over):
    """`story_step.finish` in this process: (exit code, everything it printed)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = story_step.finish(args(**over))
    return code, out.getvalue()


def raw(task: Path) -> bytes:
    return (task / "state" / "controller.json").read_bytes()


def records(task: Path) -> dict:
    return Controller(task).state()["dispatches"]


def authors(task: Path) -> list:
    return [k for k, v in records(task).items() if v.get("role") == "qa-automator" and v.get("status") == "running"]


def current_critic(task: Path) -> str:
    """The running S5 critic (the first, then each retry the cycle dispatched)."""
    return [k for k, v in records(task).items() if v.get("role") == "qa-code-critic" and v.get("status") == "running"][0]


def retry_cycle(task: Path) -> None:
    """What happens after `--needs-author`: the author's work is accepted by the controller, then the critic's retry packet that
    `recover` prints is dispatched (the cycle the finding asks for, without the handover form)."""
    author = authors(task)[0]
    evidence = task / "work" / f"{author}.txt"
    evidence.write_text("mended", encoding="utf-8")
    controller = Controller(task)
    controller.apply("accept", {"id": author, "status": "accepted", "stage_complete": False, "idempotency_key": "ok-" + author,
                                "evidence_refs": [{"path": f"work/{author}.txt", "sha256": TW.digest(evidence)}]})
    packet = Controller(task).recover()["retry_packets"][0]["packet"]
    Controller(task).apply("dispatch", dict(packet))


def receipt(project: Path, agent=AGENT, **extra) -> Path:
    path = HD.binding_path(project, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict({"agent_id": agent, "agent_type": "qa-automator", "task_id": TICKET, "dispatch_id": CRITIC,
                                     "status": "running", "bound_by": "story_step"}, **extra)), encoding="utf-8")
    return path


# --- K1-1: the scenario of the finding ----------------------------------------------------------------------------------

def k1_1_the_scenario_of_the_finding():
    project, task, controller = story()
    try:
        refusal = ""
        try:
            controller.apply("dispatch", dict(controller.build_rework_request("S5", "qa-automator", ["TC-1"], "fix the fixture")))
        except Exception as exc:    # noqa: BLE001
            refusal = str(exc)
        check_in("K1-1: `rework` while the critic runs is still refused, with the old prefix",
                 "sequential task already has an active dispatch: " + CRITIC, refusal)
        check_in("K1-1: and the refusal names the move that sends the author back", "--needs-author <cases> --reason", refusal)
        check_in("K1-1: with this story's id and the critic's id in it", f"--task {TICKET} --dispatch-id {CRITIC}", refusal)
        code, out = run()
        check_eq("K1-1: `finish --needs-author` is accepted", code, 0)
        found = records(task)
        check_eq("K1-1: the critic is `incomplete`, not accepted", found[CRITIC]["status"], "incomplete")
        check_in("K1-1: with the reason on its record", "the fixture races the page", json.dumps(found[CRITIC]))
        new = authors(task)
        check_eq("K1-1: one author is running", len(new), 1)
        author = found[new[0]]
        check_eq("K1-1: it is the rework of the accepted author, over the cases named",
                 (author.get("rework_of"), author.get("scope")), (AUTHOR, ["TC-1"]))
        check_eq("K1-1: carrying the resumed agent's id (S5 resumes)", author.get("agent_id"), AGENT)
        bound = json.loads(HD.binding_path(project, AGENT).read_text(encoding="utf-8"))
        check_eq("K1-1: the host receipt of that agent is live and names the NEW dispatch",
                 (bound.get("status") != "terminal", bound.get("dispatch_id"), bound.get("bound_by")),
                 (True, new[0], "story_step"))
        check_in("K1-1: the answer says the critic is incomplete and why", f"critic {CRITIC} is incomplete: the fixture races", out)
        check_in("K1-1: names the author and the materialize door", f"story_step.py materialize --task {TICKET} --dispatch-id {new[0]}", out)
        check_in("K1-1: and the way back to the critic", "--operation recover prints the critic's retry packet", out)
        check_eq("K1-1: the stage is not closed by this move", Controller(task).state()["stages"]["S5"]["status"], "running")
    finally:
        cleanup(project)


# --- K1-2: the author's finish names the retry, the retry is accepted -----------------------------------------------------

def k1_2_through_to_the_critic_retry():
    project, task, controller = story()
    try:
        code, _ = run()
        check_eq("K1-2: the move is made", code, 0)
        author = authors(task)[0]
        (task / "work" / "author-fixed.txt").write_text("the fixture is mended", encoding="utf-8")
        # The S5 exit gate of the AUTHOR reads the whole automation manifest (run witness, rows): not this node's business and not
        # what the fixture models, so it is stood in for; everything else of `finish` (the accept, the tail, the printed lines) is real.
        with mock.patch.object(story_step, "_finish_gate", lambda *_a: (0, "", [])):
            code, said = run(needs_author=None, reason=None, dispatch_id=author, digest="qa-automator S5 done", ignore_handoff=True,
                             not_complete=True, output=["work/author-fixed.txt"])
        check_eq("K1-2: the author's `finish` is accepted", code, 0)
        check_in("K1-2: its answer names `recover` and the critic's packet", "--operation recover prints the critic's retry packet", said)
        check("K1-2: the line stands before `next:`", said.index("--- next: controller.py") < said.index("next: {"), said)
        retry = Controller(task).recover()["retry_packets"]
        check_eq("K1-2: `recover` prints the packet of the critic", [p["dispatch_id"] for p in retry], [CRITIC])
        packet = retry[0]["packet"]
        check_eq("K1-2: it retries the same critic over the same window (one chain)",
                 (packet["role"], packet["parent_retry"], packet["scope"]), ("qa-code-critic", CRITIC, ["TC-1", "TC-2"]))
        Controller(task).apply("dispatch", dict(packet))
        after = records(task)
        check_eq("K1-2: the retry runs and supersedes the first critic", (after[packet["id"]]["status"], after[CRITIC]["status"]),
                 ("running", "superseded"))
        run_script("window_record.py", "--task", TICKET, "--dispatch", packet["id"], "--review-receipt", cwd=project)
        findings = task / "work/test-code/critic-findings.md"
        findings.parent.mkdir(parents=True, exist_ok=True)
        findings.write_text("# findings\n\nnone blocking\n", encoding="utf-8")
        closed = subprocess.run([sys.executable, "-B", str(SCRIPTS / "story_step.py"), "finish", "--task", TICKET, "--dispatch-id",
                                 packet["id"], "--digest", "qa-code-critic S5 done", "--ignore-handoff", "--output",
                                 "work/test-code/critic-findings.md", "--output", f"work/windows/{packet['id']}.json"],
                                capture_output=True, text=True, encoding="utf-8", cwd=str(project))
        check_eq("K1-2: the retried critic closes the window with a real `finish` (the door is open to the end)",
                 (closed.returncode, Controller(task).state()["dispatches"][packet["id"]]["status"]), (0, "accepted"))
        check_eq("K1-2: and the stage closes only then", Controller(task).state()["stages"]["S5"]["status"], "completed")
    finally:
        cleanup(project)


# --- K1-3: refused inputs leave the store byte for byte -------------------------------------------------------------------

def k1_3_refusals_write_nothing():
    project, task, controller = story()
    try:
        cases = [
            ("E1 no reason", dict(reason=""), "needs"),
            ("E1 no cases", dict(needs_author=""), "needs"),
            ("E1 commas only", dict(needs_author=" , ,"), "needs"),
            ("E2 a case outside the window", dict(needs_author="TC-9"), "not in the window"),
            ("E3 not the critic", dict(dispatch_id=AUTHOR), "is the S5 code critic's move"),
            ("E5 a closed dispatch", dict(dispatch_id="S0-none"), "no dispatch"),
            ("E11 --complete", dict(complete=True), "drop one"),
            ("E11 --unresolved", dict(unresolved="could_not_judge"), "drop one"),
            ("E11 --ignore-handoff", dict(ignore_handoff=True), "drop one"),
            ("E11 --window", dict(window="w.json"), "drop one"),
            ("E11 --output", dict(output=["x"]), "drop one"),
            ("E14 a cause outside the vocabulary", dict(cause="because"), "must be one of"),
        ]
        before = raw(task)
        for label, over, needle in cases:
            code, out = run(**over)
            check(f"K1-3: {label}: exit 2 and the text names what is wrong ({needle})", code == 2 and needle in out, f"{code}: {out}")
            check_eq(f"K1-3: {label}: controller.json is the same bytes", raw(task), before)
        # E4: the critic of the PLAN has its own road
        with mock.patch.object(story_step, "s5_part_of", lambda _record: "plan"):
            code, out = run()
        check("K1-3: E4 the plan's critic: refused with the plan's door", code == 2 and "--purpose s5_plan" in out, out)
        check_eq("K1-3: E4 wrote nothing", raw(task), before)
        # E5: a critic that is not open (stopped for a person) holds no window to send back
        controller.apply("checkpoint", controller.build_checkpoint_request(CRITIC, "blocked", "waiting for the person"))
        snapshot = raw(task)
        code, out = run()
        check("K1-3: E5 a critic that is not open: refused, with `where` as the door", code == 2 and "where --task" in out, out)
        check_eq("K1-3: E5 wrote nothing", raw(task), snapshot)
        # no digest and no needs-author: the same refusal an absent required argument gave, now with the form
        bare = run_script("story_step.py", "finish", "--task", TICKET, "--dispatch-id", CRITIC, cwd=project)
        check("K1-3: `finish` with neither --digest nor --needs-author: exit 2 and the form",
              bare.returncode == 2 and "finish needs --digest" in bare.stdout and "--needs-author" in bare.stdout,
              f"{bare.returncode}: {bare.stdout}{bare.stderr}")
        check_not_in("K1-3: and it is not argparse's refusal any more", "the following arguments are required", bare.stdout + bare.stderr)
    finally:
        cleanup(project)


# --- K1-4: the veto of a worker that is not proved returned ---------------------------------------------------------------

def k1_4_a_live_worker_is_not_closed():
    project, task, controller = story()
    try:
        receipt(project, agent="agent-critic-1")
        before = raw(task)
        code, out = run()
        check_eq("K1-4: a live critic receipt: refused", code, 2)
        check_in("K1-4: the checkpoint's own refusal goes out whole", "host worker is still active", out)
        check_in("K1-4: with the door: wait for its stop, or release with the person's words", "--operation release --dispatch " + CRITIC, out)
        check_eq("K1-4: nothing recorded", raw(task), before)
        with mock.patch("worker_lifecycle._natively_returned", return_value=True):
            code, out = run()
        check_eq("K1-4 control: the host's record says the worker returned: the same call goes through", code, 0)
        check_eq("K1-4 control: and the critic is `incomplete`", records(task)[CRITIC]["status"], "incomplete")
    finally:
        cleanup(project)


# --- K1-5: E7 and E8 before any record ----------------------------------------------------------------------------------

def k1_5_before_the_first_record():
    project, task, controller = story()
    try:
        before = raw(task)
        with mock.patch.object(CTL, "closure_of", return_value={"state": "closed"}):
            code, out = run()
        check("K1-5 E7: a closed story: refused, the door is the person's words", code == 2 and "--words-file" in out, out)
        check_eq("K1-5 E7: nothing written", raw(task), before)
        # E8: the cases meet two written windows (`spans`): the controller's own refusal of `build_rework_request`, verbatim
        with mock.patch.object(Controller, "_s5_window_parent",
                               lambda self, state, prior, wanted: (prior[-1], False, ["window 1: TC-1", "window 2: TC-2"])):
            code, out = run(needs_author="TC-1,TC-2")
        check("K1-5 E8: cases of two windows: the probe refuses, verbatim", code == 2 and "meets 2 windows of S5" in out, out)
        check_eq("K1-5 E8: the critic stays `running`, nothing written", (raw(task), records(task)[CRITIC]["status"]),
                 (before, "running"))
    finally:
        cleanup(project)


# --- K1-6: the critic's round, and accept is never called -----------------------------------------------------------------

def k1_6_no_round_spent_and_no_accept():
    project, task, controller = story()
    try:
        ops = []
        real = Controller.apply

        def spy(self, operation, request):
            ops.append(operation)
            return real(self, operation, request)
        ledger = repair_ledger(Controller(task).state()["dispatches"], dict(records(task)[CRITIC]))
        with mock.patch.object(Controller, "apply", spy):
            code, _ = run()
        check_eq("K1-6: the move is made", code, 0)
        check_eq("K1-6: through checkpoint and dispatch, never accept", ops, ["checkpoint", "dispatch"])
        found = records(task)
        after = repair_ledger(found, dict(found[CRITIC]))
        check_eq("K1-6: the critic's chain counts the same rounds", after["counted"], ledger["counted"])
        author = authors(task)[0]
        check_eq("K1-6: the author's round counts as a test defect (+1)",
                 repair_ledger(found, dict(found[author]))["counted"] - repair_ledger({k: v for k, v in found.items() if k != author},
                                                                                       dict(found[author]))["counted"], 1)
    finally:
        cleanup(project)
    project, task, controller = story()
    try:
        code, _ = run(cause="mechanical", reason="the helper's import line is wrong")
        found = records(task)
        author = authors(task)[0]
        check_eq("K1-6: a mechanical cause is carried and spends nothing of the cap",
                 (code, found[author].get("repair_cause"),
                  repair_ledger(found, dict(found[author]))["counted"]),
                 (0, "mechanical", repair_ledger({k: v for k, v in found.items() if k != author}, dict(found[author]))["counted"]))
    finally:
        cleanup(project)


# --- K1-7: a failed step 3 and a repeat (E9, E10), the cap (E12) ------------------------------------------------------------

def k1_7_a_state_with_a_way_out():
    project, task, controller = story()
    try:
        real = Controller.apply
        calls = []

        def failing(self, operation, request):
            calls.append(operation)
            if operation == "dispatch":
                raise RuntimeError(SENTINEL)
            return real(self, operation, request)
        with mock.patch.object(Controller, "apply", failing):
            code, out = run()
        check("K1-7: step 3 fails: exit 2 and the text says the critic is recorded and the author is not started",
              code == 2 and SENTINEL in out and "repeat the same command" in out, out)
        check_eq("K1-7: the critic is `incomplete` and no author runs", (records(task)[CRITIC]["status"], authors(task)), ("incomplete", []))
        calls.clear()
        with mock.patch.object(Controller, "apply", lambda self, op, req: (calls.append(op), real(self, op, req))[1]):
            code, out = run()
        check_eq("K1-7 E9: the repeat skips the critic's record and opens the author (`dispatch` only)", (code, calls), (0, ["dispatch"]))
        check_eq("K1-7 E9: one author runs", len(authors(task)), 1)
        before = raw(task)
        code, out = run()
        check("K1-7 E10: a second repeat: the author runs already, refused with its id",
              code == 2 and "sequential task already has an active dispatch: " + authors(task)[0] in out, out)
        check_eq("K1-7 E10: nothing written", raw(task), before)
    finally:
        cleanup(project)
    # the cap: two real cycles (author sent back, accepted, critic retried) reach the ceiling; the third is refused by the PROBE
    project, task, controller = story()
    try:
        cap = CTL.DEFAULT_LIMITS["repair_cycles"]
        for number in range(cap):
            code, out = run(dispatch_id=current_critic(task))
            check_eq(f"K1-7 E12: cycle {number + 1} of the cap {cap} goes through", code, 0)
            retry_cycle(task)
        before = raw(task)
        code, out = run(dispatch_id=current_critic(task))
        check("K1-7 E12: the ceiling is reached: refused by the probe, in the controller's own words",
              code == 2 and "repair round(s) about the test" in out, out)
        check_eq("K1-7 E12: the critic is `running` and nothing is written (the probe stands before step 2)",
                 (raw(task), records(task)[current_critic(task)]["status"]), (before, "running"))
    finally:
        cleanup(project)


# --- K1-8: the readers of the old text, and the data row -----------------------------------------------------------------

def k1_8_the_old_prefix_and_the_row():
    project, task, controller = story()
    try:
        body = (SCRIPTS / "controller.py").read_text(encoding="utf-8")
        check("K1-8: the :4690 text starts with the prefix every reader matches",
              'f"sequential task already has an active dispatch: {' in body)
        import story_run
        check("K1-8: `story_run.KNOWN_REFUSALS` still knows it",
              any("sequential task already has an active dispatch" in row[1] for row in story_run.KNOWN_REFUSALS))
        # the critic condition: the second part only while an S5 critic runs
        other = ""
        data = json.loads((task / "state" / "controller.json").read_text(encoding="utf-8"))
        data["dispatches"][CRITIC]["role"] = "qa-case-critic"
        state = copy.deepcopy(Controller(task).state())
        state["dispatches"][CRITIC]["role"] = "qa-case-critic"
        try:
            Controller(task).validate("dispatch", Controller(task).build_rework_request("S5", "qa-automator", ["TC-1"], "x"), state)
        except Exception as exc:    # noqa: BLE001
            other = str(exc)
        check_in("K1-8: another role running: the prefix and the id", "sequential task already has an active dispatch: " + CRITIC, other)
        check_not_in("K1-8: but no `--needs-author` door (it is the S5 critic's move)", "--needs-author", other)
        actions = json.loads((SCRIPTS.parent / "references" / "conductor-actions.json").read_text(encoding="utf-8"))["actions"]
        check("K1-8: the data row of the conductor's moves carries the command",
              any("finish --task <T> --dispatch-id <the running critic> --needs-author" in row.get("run", "") for row in actions))
        check_in("K1-8: and the critic's launch card names the door", "finish --needs-author <cases> --reason",
                 story_step._finish_door("S5", "qa-code-critic"))
        check_eq("K1-8: another role's card does not", story_step._finish_door("S5", "qa-automator"), "")
    finally:
        cleanup(project)


# --- K1-9: a Codex receipt, which names a path -----------------------------------------------------------------------------

def k1_9_codex_receipt():
    agent = "/root/author_1"
    project, task, controller = story(agent=agent)
    try:
        receipt(project, agent="critic_1", agent_type="qa-code-critic", task_path="/root/critic_1", task_name="critic_1")
        before = raw(task)
        code, out = run()
        check("K1-9: a live Codex receipt: refused with the checkpoint's own words", code == 2 and "host worker is still active" in out, out)
        check_eq("K1-9: nothing recorded", raw(task), before)
        with mock.patch("worker_lifecycle._natively_returned", return_value=True):
            code, out = run()
        check_eq("K1-9: returned: the move goes through", code, 0)
        bound = json.loads(HD.binding_path(project, agent).read_text(encoding="utf-8"))
        check_eq("K1-9: the author's receipt names its path and the new dispatch",
                 (bound.get("task_path"), bound.get("dispatch_id"), bound.get("status")), (agent, authors(task)[0], "running"))
    finally:
        cleanup(project)


def main():
    k1_1_the_scenario_of_the_finding()
    k1_2_through_to_the_critic_retry()
    k1_3_refusals_write_nothing()
    k1_4_a_live_worker_is_not_closed()
    k1_5_before_the_first_record()
    k1_6_no_round_spent_and_no_accept()
    k1_7_a_state_with_a_way_out()
    k1_8_the_old_prefix_and_the_row()
    k1_9_codex_receipt()
    finish("test_needs_author")


if __name__ == "__main__":
    main()
