#!/usr/bin/env python3
"""`story_step pause` after a critic's reject needs no person's word (OH3-16, HF1-7).

The critic handed its report back, so its transcript ends with the host's acknowledgement of the handback, and its
`story_step` receipt stays `running` until `finish`. The controller's checkpoint veto asked only the receipt, so
`pause` was refused ("host worker is still active") and only the person's `release` was left. Now the veto asks the
host's own record (`worker_lifecycle.active_binding` -> `dispatch_liveness.host_verdict`).

Keys: K-P1 a returned critic: `pause --status incomplete` exits 0 with no words file, and the receipt is untouched;
K-P2 a critic still at work: exit 2, the controller's refusal, then ONE line with the liveness state (`alive`) and its
door (`where`); K-P3 a receipt nothing speaks about: exit 2, then the line with `unknown` and the person's release.
Run as a subprocess in a temp project, like the conductor runs it; times are real because the command reads the clock.
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
from controller import Controller  # noqa: E402

TICKET, DISPATCH, AGENT = "QA-P1", "S0-qa-scout-1", "a5b4b2e19d35048ea"
HANDBACK = json.loads((harness.PLUGIN_ROOT / "references" / "host-report-forms.json").read_text(encoding="utf-8"))[
    "claude"]["handback_tool"]


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def story(handed_back_ago=None, last_ago=None, bound_ago=500, journal_stop=True):
    """A temp project with story QA-P1, one RUNNING dispatch (a scout), its story_step receipt (bare Claude id) and the
    child's transcript: it handed back `handed_back_ago` seconds ago, or - with `last_ago` - ends with plain text."""
    root = temp_project("qa-pause-")
    art = root / "qa-factory/artifacts" / TICKET
    art.mkdir(parents=True)
    controller = Controller(art)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(art)},
                                    "idempotency_key": "init"})
    controller.apply("dispatch", {"id": DISPATCH, "stage": "S0", "role": "qa-scout", "scope": ["TC-1"], "input_hash": "x",
                                  "budget": {}, "known_paths": {}, "idempotency_key": "d0"})
    now = time.time()
    receipt = root / "qa-factory/state/host-dispatches" / (hashlib.sha256(AGENT.encode()).hexdigest() + ".json")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"agent_id": AGENT, "agent_type": "qa-scout", "task_id": TICKET, "dispatch_id": DISPATCH,
                                   "status": "running", "bound_by": "story_step", "bound_at": now - bound_ago}), encoding="utf-8")
    first = {"timestamp": stamp(now - 3000), "type": "user", "message": {"role": "user", "content":
             f"You are qa-scout. Ticket: {TICKET}\nDispatch id: {DISPATCH}\n"}}
    if handed_back_ago is not None:
        at = now - handed_back_ago
        rows = [first,
                {"timestamp": stamp(at - 1), "type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": HANDBACK, "input": {"message": "report"}}]}},
                {"timestamp": stamp(at), "type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                        {"type": "text", "text": '{"success":true,"message":"Report delivered to your caller."}'}]}]}}]
    else:
        rows = [first, {"timestamp": stamp(now - last_ago), "type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "working"}]}}]
    path = root / "sessions/s1/subagents" / f"agent-{AGENT}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    path.with_name(f"agent-{AGENT}.meta.json").write_text(json.dumps({"agentType": "scout", "finished": True}), encoding="utf-8")
    cost = root / "qa-factory/state/cost"
    cost.mkdir(parents=True, exist_ok=True)
    (cost / "s1.json").write_text(json.dumps({"transcript": str(root / "sessions/s1.jsonl")}), encoding="utf-8")
    if handed_back_ago is not None and journal_stop:
        journal = root / "qa-factory/records/journal.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({
            "ts": datetime.fromtimestamp(now - handed_back_ago + 3, timezone.utc).isoformat(timespec="seconds"),
            "event": "subagent_stop", "agent": "qa-factory:qa-scout", "task": TICKET, "dispatch": DISPATCH,
            "status": "completed", "dispatch_receipt": receipt.name, "return_owner": "story_step"}) + "\n", encoding="utf-8")
    return root, receipt


def pause(root):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return harness.run_script("story_step.py", "pause", "--task", TICKET, "--dispatch-id", DISPATCH, "--reason",
                              "the critic rejected the work: case TC-1 has no oracle", "--status", "incomplete", cwd=root, env=env)


def status_of(root):
    return Controller(root / "qa-factory/artifacts" / TICKET).state()["dispatches"][DISPATCH]["status"]


def main():
    # K-P1: handed back 650 s ago (past the stop hooks' grace), the hook let it go: no word, no waiver, no release
    root, receipt = story(handed_back_ago=650)
    try:
        before = receipt.read_bytes()
        done = pause(root)
        check_eq("K-P1: pause of a critic that handed back exits 0, with no --words-file", done.returncode, 0)
        check_in("K-P1: and says what it recorded", f"checkpointed {DISPATCH} as incomplete", done.stdout)
        check_eq("K-P1: the dispatch is checkpointed in the controller", status_of(root), "incomplete")
        check_eq("K-P1: the receipt is byte for byte as it was", receipt.read_bytes(), before)
        check_not_in("K-P1: no refusal was printed", "refused", done.stdout)
    finally:
        cleanup(root)

    # K-P2: still at work (a row 5 s ago): refused, the controller's text, then the liveness state and its door
    root, receipt = story(last_ago=5)
    try:
        refused = pause(root)
        check_eq("K-P2: a critic at work: exit 2", refused.returncode, 2)
        check_in("K-P2: the controller's refusal, unchanged", "host worker is still active", refused.stdout)
        lines = [line for line in refused.stdout.splitlines() if "the host worker of" in line]
        check_eq("K-P2: exactly ONE more line follows it", len(lines), 1)
        check("K-P2: it names the state alive and the door `where`", bool(lines) and "is alive" in lines[0]
              and f"story_step.py where --task {TICKET}" in lines[0], str(lines))
        check_eq("K-P2: the line comes AFTER the refusal", refused.stdout.index("host worker is still active")
                 < refused.stdout.index("the host worker of"), True)
        check_eq("K-P2: the dispatch is still running", status_of(root), "running")
    finally:
        cleanup(root)

    # K-P3: a receipt nothing speaks about (old, a silent transcript): unknown, and the door is the person's release
    root, receipt = story(last_ago=2500, bound_ago=2000)
    try:
        refused = pause(root)
        check_eq("K-P3: nothing proves the worker gone: exit 2", refused.returncode, 2)
        lines = [line for line in refused.stdout.splitlines() if "the host worker of" in line]
        check("K-P3: the line says unknown and names the person's release with the words file",
              len(lines) == 1 and "is unknown" in lines[0] and "--operation release" in lines[0] and "--words-file" in lines[0],
              str(lines))
    finally:
        cleanup(root)

    # a refusal that is not about a host worker prints no hint: a dispatch the controller does not know
    root, receipt = story(handed_back_ago=650)
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        other = harness.run_script("story_step.py", "pause", "--task", TICKET, "--dispatch-id", "S0-qa-scout-9", "--reason", "x",
                                   "--status", "incomplete", cwd=root, env=env)
        check_eq("an unknown dispatch is refused", other.returncode, 2)
        check_not_in("and no liveness line is added to a refusal that is not about a host worker", "the host worker of", other.stdout)
    finally:
        cleanup(root)
    finish("test_story_step_pause")


if __name__ == "__main__":
    main()
