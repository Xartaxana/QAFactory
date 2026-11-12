"""Stop/SubagentStop lifecycle: bounded checks, scoped fuse, and honest handoff status."""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, temp_dir,  # noqa: E402
                     use_project)

sys.path.insert(0, str(SCRIPTS))
import exit_gate as gate  # noqa: E402
import subagent_journal as handoff_journal  # noqa: E402


def invoke(event: dict) -> int:
    gate.read_event = lambda: dict(event)
    try:
        gate.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def records(root: Path) -> list[dict]:
    journal = root / "qa-factory" / "records" / "journal.jsonl"
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line]


def part_record_return(root: Path, base: dict) -> None:
    """the hook tells the controller the role came back.

    On TP1-15045 a role started, stopped on a refusal, and nobody recorded the return:
    the dispatch stayed `running`, `next` answered `wait_existing_job` for the rest of the
    story, and the person's "it's dead, go on" freed nothing. The fact was in the journal the
    whole time. Tested against a stub because `Controller.record_return` belongs to another
    package; the contract checked here is that the hook CALLS it, with the dispatch and a
    digest, and survives a build that has no such method."""
    seen: list = []

    class Stub:
        def __init__(self, task_root, wait_seconds=0.0):
            seen.append(("root", Path(task_root).name))

        def record_return(self, dispatch_id, digest, agent=""):
            seen.append((dispatch_id, digest[:20], agent))
            return True

    import controller as real
    saved = real.Controller
    transcript = root / "role.jsonl"
    transcript.write_text(json.dumps({"message": {"role": "assistant", "content": [
        {"type": "text", "text": "S5 halted: the guard refused the run request."}]}}) + "\n",
        encoding="utf-8")
    try:
        real.Controller = Stub
        event = {**base, "task_id": "QA-1", "dispatch_id": "S5-qa-automator-1",
                 "transcript_path": str(transcript)}
        handoff_journal.read_event = lambda: dict(event)
        try:
            handoff_journal.main()
        except SystemExit:
            pass
        check("the return is recorded with the controller", any(s[0] == "QA-1" for s in seen)
              or any(s[0] == "S5-qa-automator-1" for s in seen))
        recorded = next((s for s in seen if s[0] == "S5-qa-automator-1"), None)
        check("with the dispatch the role was running", recorded is not None, f"saw {seen}")
        if recorded:
            check_eq("and the role's closing words as the digest", recorded[1], "S5 halted: the guard")
            check_eq("and the agent that stopped", recorded[2], "qa-scout")

        # A build whose controller has no record_return behaves exactly as before.
        class Old:
            def __init__(self, task_root, wait_seconds=0.0):
                pass

        real.Controller = Old
        seen.clear()
        try:
            handoff_journal.main()
        except SystemExit:
            pass
        check("a controller without record_return is not an error", not seen)

        # And a controller that raises never keeps the role from stopping.
        class Angry:
            def __init__(self, task_root, wait_seconds=0.0):
                raise RuntimeError("state is unreadable")

        real.Controller = Angry
        code = 0
        try:
            handoff_journal.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
        check_eq("a controller that raises never blocks the stop", code, 0)
    finally:
        real.Controller = saved


def part_record_return_live(base: dict) -> None:
    """The same hook against the REAL controller: a running dispatch stops being running.

    The stub above proves the call is made; this proves the two ends fit, which is the whole
    defect — the journal held the fact and the controller was never told."""
    import controller as real
    import hooklib
    import test_controller_state as BASE
    story = temp_dir("qa-return-live-")
    cached, hooklib._PROJECT_ROOT_CACHE = hooklib._PROJECT_ROOT_CACHE, None
    try:
        use_project(story)
        (story / "qa-factory").mkdir(parents=True, exist_ok=True)
        (story / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        task = story / "qa-factory" / "artifacts" / "QA-RET"
        task.mkdir(parents=True)
        controller = real.Controller(task)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                        "known_paths": {"root": str(task)},
                                        "idempotency_key": "init"})
        BASE.accept_stage(controller, task, "S0")
        controller.apply("dispatch", {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout",
                                      "scope": [], "input_hash": "ctx", "budget": {"requests": 5},
                                      "known_paths": {"root": str(task)},
                                      "idempotency_key": "d-1"})
        event = {**base, "task_id": "QA-RET", "dispatch_id": "S1-qa-scout-1",
                 "cwd": str(story), "digest": "S1 halted: the source repository is missing."}
        handoff_journal.read_event = lambda: dict(event)
        try:
            handoff_journal.main()
        except SystemExit:
            pass
        after = (controller.state().get("dispatches") or {}).get("S1-qa-scout-1") or {}
        check("the real controller stops calling the dispatch running",
              after.get("status") != "running", f"status={after.get('status')!r}")
    finally:
        hooklib._PROJECT_ROOT_CACHE = cached
        cleanup(story)


def main() -> None:
    root = temp_dir("qa-hook-life-")
    (root / "qa-factory" / "state").mkdir(parents=True)
    (root / "tests").mkdir()
    template = PLUGIN_ROOT / "references" / "templates" / "config.json"
    (root / "qa-factory" / "config.json").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    original = (gate.scoped_errors, gate.detector_errors, gate.witness_errors,
                gate.required_outputs_errors, gate.next_hint)
    try:
        use_project(root)
        calls = {"detector": 0}
        gate.scoped_errors = lambda _agent, _task="", _facts="": []
        gate.witness_errors = lambda _agent, _task="": []
        gate.required_outputs_errors = lambda _agent, _task="": []
        gate.next_hint = lambda _agent: ""

        def env_failure(_agent: str, _task: str = "") -> list[str]:
            calls["detector"] += 1
            return ["ENV_TOOL_MISSING: poetry is unavailable; configure the hook-local tool path"]

        gate.detector_errors = env_failure
        base = {"hook_event_name": "SubagentStop", "agent_type": "qa-scout",
                "session_id": "host-session", "task_id": "QA-1", "dispatch_id": "dispatch-1",
                "completion_attempt": "attempt-1", "input_fingerprint": "tree-a"}
        exits = [invoke(base) for _ in range(9)]
        check_eq("nine unchanged events run the quality detector once", calls["detector"], 1)
        check_eq("only the first event forces a return", exits, [2] + [0] * 8)
        journal = records(root)
        check_eq("nine events create exactly one blocker", sum(r["event"] == "gate_block" for r in journal), 1)
        state = json.loads(gate._state_path().read_text(encoding="utf-8"))
        receipt = next(iter(state.values()))
        check_eq("fuse receipt remains incomplete rather than accepted", receipt["status"], "incomplete")
        check("error receipt preserves actionable classification",
              receipt["errors"][0].startswith("ENV_TOOL_MISSING:"))

        active = {**base, "task_id": "QA-active", "dispatch_id": "dispatch-active",
                  "stop_hook_active": True}
        before = calls["detector"]
        check_eq("active Stop is released, never blocked a second time", invoke(active), 0)
        check_eq("active Stop re-checks the handoff exactly once", calls["detector"], before + 1)
        state = json.loads((root / "qa-factory/state/.exit_gate_blocks.json").read_text(encoding="utf-8"))
        check("a still-broken re-entry is recorded incomplete, not accepted",
              any(r.get("dispatch") == "dispatch-active" and r.get("status") == "incomplete"
                  for r in state.values()))

        gate.detector_errors = lambda _agent, _task="": []
        mended = {**base, "task_id": "QA-mended", "dispatch_id": "dispatch-mended",
                  "stop_hook_active": True}
        check_eq("a repaired re-entry is released", invoke(mended), 0)
        state = json.loads((root / "qa-factory/state/.exit_gate_blocks.json").read_text(encoding="utf-8"))
        check("and recorded as passed — the repair is seen, not thrown away",
              any(r.get("dispatch") == "dispatch-mended" and r.get("status") == "check_passed"
                  for r in state.values()))
        gate.detector_errors = env_failure

        before = calls["detector"]
        repaired = {**base, "input_fingerprint": "tree-b"}
        check_eq("changed input performs one explicit revalidation", invoke(repaired), 2)
        check_eq("changed input increments detector calls once", calls["detector"], before + 1)

        # A clean story must not erase another story's incomplete receipt.
        gate.detector_errors = lambda _agent, _task="": []
        clean = {**base, "task_id": "QA-2", "dispatch_id": "dispatch-2",
                 "input_fingerprint": "tree-clean"}
        check_eq("parallel clean task passes", invoke(clean), 0)
        persisted = json.loads(gate._state_path().read_text(encoding="utf-8"))
        check("clean task does not delete the failed task receipt",
              any(r.get("task") == "QA-1" and r.get("status") == "incomplete" for r in persisted.values()))

        handoff_journal.read_event = lambda: dict(base)
        try:
            handoff_journal.main()
        except SystemExit:
            pass
        check_eq("subagent handoff journal does not convert a fused failure to completion",
                 records(root)[-1]["status"], "incomplete")

        part_record_return(root, base)
        part_record_return_live(base)

        # Concurrent state writes retain both task keys.
        scopes = []
        for task in ("QA-C1", "QA-C2"):
            key, scope = gate._identity({**base, "task_id": task, "dispatch_id": task,
                                         "input_fingerprint": "same"}, "qa-scout")
            scopes.append((key, scope))
        threads = [threading.Thread(target=gate._record, args=(key, scope, "incomplete", ["crash receipt"]))
                   for key, scope in scopes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        persisted = json.loads(gate._state_path().read_text(encoding="utf-8"))
        check("concurrent task receipts are both durable", all(key in persisted for key, _ in scopes))

        # Explicit task selection must beat mtime/latest-story heuristics.
        good_dir = root / "qa-factory" / "artifacts" / "QA-GOOD" / "work"
        bad_dir = root / "qa-factory" / "artifacts" / "QA-NEWER" / "work"
        good_dir.mkdir(parents=True)
        bad_dir.mkdir(parents=True)
        (good_dir / "context-manifest.json").write_text(
            json.dumps({"ticket": "QA-GOOD", "acceptance_criteria": [], "implementation": {}}),
            encoding="utf-8")
        (bad_dir / "context-manifest.json").write_text("{}", encoding="utf-8")
        gate.scoped_errors = original[0]
        check_eq("selected task ignores another story's newer broken artifact",
                 gate.scoped_errors("qa-scout", "QA-GOOD"), [])
        check("broken artifact remains visible to its own task",
              bool(gate.scoped_errors("qa-scout", "QA-NEWER")))
    finally:
        (gate.scoped_errors, gate.detector_errors, gate.witness_errors,
         gate.required_outputs_errors, gate.next_hint) = original
        cleanup(root)
    finish("test_hook_lifecycle")


if __name__ == "__main__":
    main()
