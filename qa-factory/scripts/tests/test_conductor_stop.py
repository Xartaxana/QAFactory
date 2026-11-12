#!/usr/bin/env python3
"""HF8-15 (1b): the conductor's Stop hook wakes the conductor about a role that has already returned.

Run 12586 stopped on a conductor that ended its turn on "waiting" for a critic that had handed back. Keys: K3-7 the
wake (RETURNED -> exit 2 once, the second Stop 0; ALIVE and an unknown stay silent), K3-8 the cost and the scope (no
receipt -> no transcript read; every receipt of the dispatch must have returned; another session's receipt is never
woken for; one text for several), K3-9 E12-E15 (the host's re-entry, a crash, a broken or unwritable fuse file, the
driver's mode), K3-10 empty stdin through the literal script. The world builder (`world`) is shared with
`test_exit_text_end.py` (the same transcript form, the same receipt).
"""
import calendar
import io
import json
import os
import subprocess
import sys
import time
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import conductor_stop as CS  # noqa: E402
import dispatch_liveness as DL  # noqa: E402
import host_adapter as HA  # noqa: E402
import host_dispatch as HD  # noqa: E402
import launch_card  # noqa: E402

SESSION = f"conductor-session-{os.getpid()}"       # per run: `person_signal`'s once-per-session marker lives in the OS temp folder
TASK, DISPATCH, AGENT = "QA-WAKE", "S5-qa-code-critic-1", "a1b2c3d4e5f60708"
HANDBACK = "SubagentHandback"
ACK_TIME = "2026-10-30T08:00:00.000Z"          # long before now: the grace window is over and no stop line holds it
BOUND_AT = calendar.timegm(time.strptime("2026-10-30T07:00:00", "%Y-%m-%dT%H:%M:%S"))   # the receipt is older than its acknowledgement


def row(kind: str, blocks, stamp: str = ACK_TIME) -> str:
    return json.dumps({"type": kind, "timestamp": stamp, "message": {"role": kind, "content": blocks}})


def call(use_id: str = "toolu_h1", message: str = "qa-code-critic S5 done") -> str:
    return row("assistant", [{"type": "tool_use", "id": use_id, "name": HANDBACK, "input": {"message": message}}])


def ack(use_id: str = "toolu_h1", stamp: str = ACK_TIME) -> str:
    return row("user", [{"type": "tool_result", "tool_use_id": use_id,
                         "content": [{"type": "text", "text": "{\"success\":true,\"message\":\"Report delivered.\"}"}]}], stamp)


def prompt(text: str = "You are qa-code-critic. Ticket: QA-WAKE. Dispatch id: S5-qa-code-critic-1") -> str:
    return row("user", text)


def said(text: str) -> str:
    return row("assistant", [{"type": "text", "text": text}])


def world(prefix: str, rows=None, session: str = SESSION, task: str = TASK, dispatch: str = DISPATCH,
          agent: str = AGENT, status: str = "running", receipt_status: str = "running") -> dict:
    """A project with one story whose controller says `dispatch` is `status`, a bound receipt of `agent`, the
    conductor's transcript and the agent's own transcript under it (`rows`, a handback by default)."""
    root = temp_project(prefix)
    use_project(root)
    parent = root / "claude" / f"{session}.jsonl"
    child = parent.parent / session / "subagents" / f"agent-{agent}.jsonl"
    child.parent.mkdir(parents=True)
    parent.write_text("{}\n", encoding="utf-8")
    child.write_text("\n".join(rows if rows is not None else [prompt(), call(), ack()]) + "\n", encoding="utf-8")
    cost = root / "qa-factory" / "state" / "cost"
    cost.mkdir(parents=True, exist_ok=True)
    (cost / f"{session}.json").write_text(json.dumps({"transcript": str(parent)}), encoding="utf-8")
    state = root / "qa-factory" / "artifacts" / task / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "controller.json").write_text(json.dumps({"dispatches": {dispatch: {
        "id": dispatch, "stage": "S5", "role": "qa-code-critic", "status": status}}}), encoding="utf-8")
    receipt = {"agent_id": agent, "agent_type": "qa-code-critic", "task_id": task, "dispatch_id": dispatch,
               "status": receipt_status, "bound_by": "story_step", "task_name": agent, "bound_at": BOUND_AT}
    path = HD.binding_path(root, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return {"root": root, "parent": parent, "child": child, "session": session,
            "event": {"hook_event_name": "Stop", "session_id": session, "transcript_path": str(parent), "cwd": str(root)}}


def stop(w: dict, **extra):
    """`(code, text)` of the hook's decision for the world's Stop event."""
    return CS.decide(dict(w["event"], **extra))


def fuse(w: dict) -> dict:
    path = w["root"] / "qa-factory" / "state" / CS.FUSE_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def counting(module, name: str, counter: list):
    real = getattr(module, name)

    def spy(*args, **kwargs):
        counter.append(1)
        return real(*args, **kwargs)
    setattr(module, name, spy)
    return lambda: setattr(module, name, real)


def the_wake_is_once_and_only_for_a_return():
    """K3-7 (mutants: no fuse, a block on ALIVE)."""
    w = world("cs-k7-")
    try:
        code, text = stop(w)
        check_eq("K3-7: a returned role of this session: exit 2", code, 2)
        check_in("K3-7: the text names the dispatch", DISPATCH, text)
        check_in("K3-7: ...says it is not busy", "it is not busy", text)
        check_in("K3-7: ...and names the move and its flag", f"story_step.py finish --task {TASK} --dispatch-id {DISPATCH} --digest -", text)
        check_in("K3-7: ...and the other door", "--needs-author", text)
        check_in("K3-7: ...with the host's evidence line", "the host's own transcript ends with the handback call", text)
        check_eq("K3-7: the fuse holds one key", len(fuse(w)), 1)
        check_eq("K3-7: the SECOND Stop for the same return is released", stop(w), (0, ""))
        # the host's own re-entry flag, with a fresh fuse
        w["root"].joinpath("qa-factory", "state", CS.FUSE_FILE).unlink()
        check_eq("K3-7: the host's stop_hook_active is released without a read", stop(w, stop_hook_active=True), (0, ""))
        check_eq("K3-7: ...and writes no fuse", fuse(w), {})
    finally:
        cleanup(w["root"])
    # ALIVE: the handback is seconds old (the stop hooks' window is open) - the hook is silent
    recent = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 10))
    w = world("cs-k7-alive-", [prompt(), call(), ack(stamp=recent)])
    try:
        check_eq("K3-7: a handback inside the grace window is ALIVE: silence", stop(w), (0, ""))
        check_eq("K3-7: ...and writes no fuse", fuse(w), {})
    finally:
        cleanup(w["root"])
    # an unknown: the transcript does not end with the acknowledgement (the role works on after it)
    w = world("cs-k7-open-", [prompt(), call(), ack(), said("one more thing")])
    try:
        check_eq("K3-7: a transcript that goes on after the handback is not a return: silence", stop(w), (0, ""))
    finally:
        cleanup(w["root"])
    w = world("cs-k7-ctrl-", status="accepted")
    try:
        check_eq("K3-7: the controller does not call the dispatch running: silence", stop(w), (0, ""))
    finally:
        cleanup(w["root"])
    w = world("cs-k7-term-", receipt_status="terminal")
    try:
        check_eq("K3-7: a terminal receipt is not asked about: silence", stop(w), (0, ""))
    finally:
        cleanup(w["root"])


def the_wake_is_cheap_and_scoped():
    """K3-8: E9 (no receipt: no transcript is read), E10, E11, and the dispatch's other receipt."""
    w = world("cs-k8-none-")
    try:
        for receipt in (w["root"] / "qa-factory" / "state" / "host-dispatches").glob("*.json"):
            receipt.unlink()
        reads = []
        restore = [counting(HA, "subagent_transcript_of", reads), counting(DL, "_native_verdict", reads),
                   counting(DL, "transcripts", reads)]
        try:
            check_eq("K3-8 E9: no receipt: silence", stop(w), (0, ""))
        finally:
            for undo in restore:
                undo()
        check_eq("K3-8 E9: ...and no transcript, no verdict, no inventory was read", len(reads), 0)
    finally:
        cleanup(w["root"])
    # E11: the receipt's agent lives in another session's folder; the event is of a different conductor
    w = world("cs-k8-foreign-", session="other-session")
    try:
        mine = dict(w["event"], session_id="our-session", transcript_path=str(w["parent"].with_name("our-session.jsonl")))
        mine_parent = Path(mine["transcript_path"])
        mine_parent.write_text("{}\n", encoding="utf-8")
        check_eq("K3-8 E11: another session's receipt does not wake us", CS.decide(mine), (0, ""))
        check_eq("K3-8 E11 control: the session that owns it IS woken", stop(w)[0], 2)
    finally:
        cleanup(w["root"])
    # the dispatch has a second non-terminal receipt the host says nothing about: it is not returned
    w = world("cs-k8-second-")
    try:
        second = {"agent_id": "ffff0000ffff0000", "agent_type": "qa-code-critic", "task_id": TASK, "dispatch_id": DISPATCH,
                  "status": "running", "bound_by": "story_step", "task_name": "ffff0000ffff0000", "bound_at": BOUND_AT}
        HD.binding_path(w["root"], "ffff0000ffff0000").write_text(json.dumps(second), encoding="utf-8")
        # its transcript names the same dispatch and goes on after a handback: it is working, the dispatch is not returned
        (w["child"].parent / "agent-ffff0000ffff0000.jsonl").write_text(
            "\n".join([prompt(), call("toolu_h3"), ack("toolu_h3"), said("one more thing")]) + "\n", encoding="utf-8")
        check_eq("K3-8: a second receipt of the dispatch that has not returned keeps the conductor asleep", stop(w), (0, ""))
    finally:
        cleanup(w["root"])
    # E10: two returned dispatches of the session: one block, both ids
    w = world("cs-k8-two-")
    try:
        other = ("S5-qa-code-critic-2", "bbbb1111bbbb1111")
        (w["child"].parent / f"agent-{other[1]}.jsonl").write_text("\n".join([prompt(), call("toolu_h2"), ack("toolu_h2")]) + "\n", encoding="utf-8")
        controller = w["root"] / "qa-factory" / "artifacts" / TASK / "state" / "controller.json"
        data = json.loads(controller.read_text(encoding="utf-8"))
        data["dispatches"][other[0]] = {"id": other[0], "stage": "S5", "role": "qa-code-critic", "status": "running"}
        controller.write_text(json.dumps(data), encoding="utf-8")
        HD.binding_path(w["root"], other[1]).write_text(json.dumps({
            "agent_id": other[1], "agent_type": "qa-code-critic", "task_id": TASK, "dispatch_id": other[0], "status": "running",
            "bound_by": "story_step", "task_name": other[1], "bound_at": BOUND_AT}), encoding="utf-8")
        code, text = stop(w)
        check_eq("K3-8 E10: two returned dispatches: one block", code, 2)
        check("K3-8 E10: ...naming both", DISPATCH in text and other[0] in text, text)
        check_eq("K3-8 E10: ...and the next Stop is silent for both", stop(w), (0, ""))
    finally:
        cleanup(w["root"])


def the_failure_modes_do_not_lock_anyone():
    """K3-9: E12 (a question and a return: one refusal, then out), E13 a crash, E14 the fuse file, E15 the driver."""
    w = world("cs-k9-")
    try:
        check_eq("K3-9 E12: the first Stop is refused", stop(w)[0], 2)
        check_eq("K3-9 E12: the next, whatever the conductor says, is not", stop(w)[0], 0)
        # E14: a broken fuse file counts as empty: one block, and the file is whole afterwards
        path = w["root"] / "qa-factory" / "state" / CS.FUSE_FILE
        path.write_text("{ not json", encoding="utf-8")
        check_eq("K3-9 E14: a broken fuse file: one block", stop(w)[0], 2)
        check_eq("K3-9 E14: ...and the file now parses with one key", len(fuse(w)), 1)
        # E14: a fuse that cannot be written: no block (better no alarm than a loop)
        path.unlink()
        import event_store
        real = event_store.atomic_json
        event_store.atomic_json = lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
        try:
            check_eq("K3-9 E14: an unwritable fuse file: no block", stop(w), (0, ""))
        finally:
            event_store.atomic_json = real
        # E15: the driver's mode names itself in the environment
        path.unlink(missing_ok=True)
        os.environ[CS.RUN_MODE_ENV] = CS.DRIVER_MODE
        reads = []
        undo = counting(HA, "subagent_transcript_of", reads)
        try:
            check_eq("K3-9 E15: the driver's mode: silence", stop(w), (0, ""))
            check_eq("K3-9 E15: ...and nothing was read", len(reads), 0)
        finally:
            undo()
            os.environ.pop(CS.RUN_MODE_ENV, None)
        check_eq("K3-9 E15 control: the same Stop outside the driver is refused", stop(w)[0], 2)
        check_eq("K3-9: the name of the variable is the driver's own", CS.RUN_MODE_ENV, launch_card.RUN_MODE_ENV)
        check_eq("K3-9: a Codex event is not asked", CS.decide(dict(w["event"], turn_id="t-1")), (0, ""))
        check_eq("K3-9: an event with no transcript path is not asked", CS.decide({"session_id": SESSION}), (0, ""))
        import session_identity
        held = {name: os.environ.pop(name) for name in session_identity.load_rules()["env_vars"] if name in os.environ}
        try:
            check_eq("K3-9: an event with no session and none in the environment is not asked",
                     CS.decide({"transcript_path": str(w["parent"]), "cwd": str(w["root"])}), (0, ""))
        finally:
            os.environ.update(held)
        # E13: a crash of the check is exit 0 and one journal signal
        path.unlink(missing_ok=True)
        real_verdict = DL._native_verdict

        def crash(*_a, **_k):
            raise RuntimeError("the reader broke")
        DL._native_verdict = crash
        stdin, err = sys.stdin, io.StringIO()
        sys.stdin = io.StringIO(json.dumps(w["event"]))
        try:
            with redirect_stderr(err):
                try:
                    CS.main()
                    code = 0
                except SystemExit as exc:
                    code = int(exc.code or 0)
        finally:
            DL._native_verdict = real_verdict
            sys.stdin = stdin
        check_eq("K3-9 E13: a crash is exit 0", code, 0)
        check_eq("K3-9 E13: ...with nothing on stderr to block on", err.getvalue(), "")
        lines = [json.loads(line) for p in w["root"].rglob("journal.jsonl") for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        signals = [x for x in lines if x.get("event") == "hook_signal" and x.get("kind") == "gate_unreadable"]
        check("K3-9 E13: ...and ONE gate_unreadable signal names the hook", len(signals) == 1 and "conductor_stop: unreadable" in signals[0]["notes"], str(signals))
    finally:
        cleanup(w["root"])


def the_literal_script_ends_clean():
    """K3-10: the script as the launcher runs it, on an empty stdin and on garbage, outside any project."""
    for payload in ("", "   \n", "not json", "[]"):
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "conductor_stop.py")], input=payload, capture_output=True, text=True,
                           encoding="utf-8", timeout=60, env={k: v for k, v in os.environ.items() if k != CS.RUN_MODE_ENV})
        check_eq(f"K3-10: stdin {payload!r}: exit 0", p.returncode, 0)
        check_not_in(f"K3-10: stdin {payload!r}: nothing blocks", "has returned", p.stderr)
    w = world("cs-k10-")
    try:
        env = {k: v for k, v in os.environ.items() if k != CS.RUN_MODE_ENV}
        env["CLAUDE_PROJECT_DIR"] = str(w["root"])
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "conductor_stop.py")], input=json.dumps(w["event"]), capture_output=True,
                           text=True, encoding="utf-8", timeout=60, env=env, cwd=str(w["root"]))
        check_eq("K3-10: the literal script on a returned role: exit 2", p.returncode, 2)
        check_in("K3-10: ...with the wake text on stderr", DISPATCH, p.stderr)
    finally:
        cleanup(w["root"])


def main():
    os.environ.pop(CS.RUN_MODE_ENV, None)
    the_wake_is_once_and_only_for_a_return()
    the_wake_is_cheap_and_scoped()
    the_failure_modes_do_not_lock_anyone()
    the_literal_script_ends_clean()
    finish("conductor stop")


if __name__ == "__main__":
    main()
