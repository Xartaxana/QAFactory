#!/usr/bin/env python3
"""RH1-5 B9: an unknown is not a pass at dispatch time (`inject_context.py`).

H10/H11 a rules file that is missing or cannot be read: a line in the role's prompt + a `hook_signal` of kind `inject`;
H12 the task packet carries no paths: the same; H13 an event that cannot be parsed: ALLOW + signal; H14 any exception of
the hook: ALLOW + signal, EXCEPT an existing controller.json that cannot be read (E24): the receipt refusal, text, a
`dispatch-denials.jsonl` line, exit 2; H15 `host_adapter.rewrite_output`: with no advice the output is byte for byte what
the hook always printed (the golden below was recorded from the old inline `print` BEFORE the edit); an advice never goes
into `additionalContext` beside `updatedInput` (B0 a: it does not arrive) but into a signal.
"""
import contextlib
import io
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import host_adapter  # noqa: E402
import inject_context as IC  # noqa: E402
import runtime_paths as RP  # noqa: E402

TASK = "QA-1"
# the once-per-session markers live in the OS temp folder: a session id that repeats between runs would find them set (FR-31)
SESSION = "sess-b9-" + uuid.uuid4().hex
ROLE = "qa-scout"
RULES = "project:qa-factory/strategy/framework-rules.md"
# recorded from the old inline `print(json.dumps({...}, ensure_ascii=False))` before the edit: the key order, the separators
# and the non-ASCII text are part of the contract
TEXT = "Privet " + chr(0xFC) + " " + chr(0x416)          # non-ASCII built from code points: the package is English (FR-30)
GOLDEN = ('{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": '
          '{"prompt": "' + TEXT + '", "model": "sonnet"}}}\n')
UPDATED = {"prompt": TEXT, "model": "sonnet"}


def journal_rows(root: Path) -> list:
    path = RP.record(root, "journal.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


def kinds(root: Path, kind: str) -> list:
    return [r for r in journal_rows(root) if r.get("event") == "hook_signal" and r.get("kind") == kind]


def make_story(root: Path, controller: str | None) -> Path:
    task = root / "qa-factory" / "artifacts" / TASK
    (task / "state").mkdir(parents=True)
    (task / "pipeline.json").write_text("{}", encoding="utf-8")
    if controller is not None:
        (task / "state" / "controller.json").write_text(controller, encoding="utf-8")
    return task


def run_hook(root: Path, event: dict | None, *, patch: dict | None = None) -> tuple:
    """inject_context.main() in this process as the PreToolUse hook of an Agent dispatch; the stage guard is stood in for
    by a function that allows (its refusals have their own tests). `patch`: attributes of the module to replace."""
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    hooklib._PROJECT_ROOT_CACHE = None
    saved = {name: getattr(IC, name) for name in ("read_event", "run_stage_guard", *(patch or {}))}
    IC.read_event, IC.run_stage_guard = (lambda: event), (lambda _e: None)
    for name, value in (patch or {}).items():
        setattr(IC, name, value)
    real_argv, sys.argv = sys.argv, ["inject_context.py"]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                IC.main()
            except SystemExit as stop:
                code = stop.code or 0
    finally:
        for name, value in saved.items():
            setattr(IC, name, value)
        sys.argv = real_argv
    return code, out.getvalue(), err.getvalue()


def agent_event(root: Path, prompt: str = f"Dispatch id: S0-{ROLE}-1\nTask {TASK}") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION, "cwd": str(root),
            "tool_input": {"subagent_type": ROLE, "prompt": prompt}}


def prompt_of(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"]["updatedInput"]["prompt"] if out.strip() else ""


def rules_file(root: Path, text: str = "FW rules\n") -> Path:
    path = root / "qa-factory" / "strategy" / "framework-rules.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def h15_golden() -> None:
    root = temp_project("qa-inject-h15-")
    try:
        use_project(root)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            host_adapter.rewrite_output({"hook_event_name": "PreToolUse"}, UPDATED)
        check_eq("H15: an empty advice prints byte for byte the golden recorded from the old inline print", buf.getvalue(), GOLDEN)
        check_eq("H15: ...and no signal was written", journal_rows(root), [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            host_adapter.rewrite_output({"hook_event_name": "PreToolUse", "session_id": "s"}, UPDATED, "advice for the conductor")
        check_eq("H15: an advice leaves the object the golden says - never additionalContext beside updatedInput (B0 a)",
                 buf.getvalue(), GOLDEN)
        check_not_in("H15: no additionalContext anywhere in it", "additionalContext", buf.getvalue())
        rows = kinds(root, "inject")
        check("H15: the advice went to the person as a hook_signal of kind inject",
              len(rows) == 1 and rows[0]["notes"] == "advice for the conductor", str(rows))
    finally:
        cleanup(root)


def end_to_end() -> None:
    root = temp_project("qa-inject-e2e-")
    try:
        use_project(root)
        rules_file(root)
        code, out, err = run_hook(root, agent_event(root, "Privet ü"))
        data = json.loads(out)
        check_eq("e2e: exit 0, exactly one JSON object whose keys are the golden's", (code, list(data), list(data["hookSpecificOutput"])),
                 (0, ["hookSpecificOutput"], ["hookEventName", "permissionDecision", "updatedInput"]))
        check_eq("e2e: the verdict is allow", data["hookSpecificOutput"]["permissionDecision"], "allow")
        check("e2e: the prompt is the original plus the injected blocks, the rules file among them",
              prompt_of(out).startswith("Privet ü") and "FW rules" in prompt_of(out), prompt_of(out)[:80])
        check_not_in("e2e: nothing missing, so no unavailable line", "Factory context unavailable", prompt_of(out))
        check_eq("e2e: and no signal in the journal", journal_rows(root), [])
        check_eq("e2e: the stdout is the object and its newline, nothing after it", out, json.dumps(data, ensure_ascii=False) + "\n")
    finally:
        cleanup(root)


def h10_h11() -> None:
    root = temp_project("qa-inject-h10-")
    try:
        use_project(root)
        code, out, _err = run_hook(root, agent_event(root))
        line = f"your factory rules file {RULES} is missing; work from the prompt and name it under blocked"
        check_eq("H10: a missing rules file does not stop the dispatch", code, 0)
        check_in("H10: the role's prompt carries the line", line, prompt_of(out))
        rows = kinds(root, "inject")
        check("H10: and one signal of kind inject names it", len(rows) == 1 and line in rows[0]["notes"], str(rows))
        # H11: the entry exists and cannot be read (a folder where the file belongs)
        (root / "qa-factory" / "strategy" / "framework-rules.md").mkdir(parents=True)
        code, out, _err = run_hook(root, agent_event(root))
        check_eq("H11: an unreadable rules file does not stop the dispatch", code, 0)
        check("H11: the role's prompt says it could not be read",
              f"your factory rules file {RULES} could not be read (" in prompt_of(out)
              and "name it under blocked" in prompt_of(out), prompt_of(out)[-300:])
        check("H11: the signal says so too (the same session and kind: said once, the line is in the prompt every time)",
              len(kinds(root, "inject")) >= 1)
    finally:
        cleanup(root)


def h12() -> None:
    root = temp_project("qa-inject-h12-")
    try:
        use_project(root)
        rules_file(root)
        make_story(root, json.dumps({"revision": 1, "known_paths": {"project_root": "x"}}))

        def boom(*_a, **_k):
            raise OSError("no such volume")
        import runtime_paths
        real = runtime_paths.state_paths
        runtime_paths.state_paths = boom
        try:
            code, out, _err = run_hook(root, agent_event(root))
        finally:
            runtime_paths.state_paths = real
        check_eq("H12: paths that cannot be resolved do not stop the dispatch", code, 0)
        check("H12: the role's prompt carries 'the task packet carries no paths: <reason>' and the instruction",
              "the task packet carries no paths: the stored paths could not be resolved (OSError: no such volume)" in prompt_of(out)
              and "name it under blocked" in prompt_of(out), prompt_of(out)[-400:])
        check("H12: and a signal of kind inject", len(kinds(root, "inject")) == 1, str(journal_rows(root)))
        code, out, _err = run_hook(root, agent_event(root))
        check_not_in("H12 control: with the paths resolvable there is no such line", "carries no paths", prompt_of(out))
    finally:
        cleanup(root)


def h12_driver_twin() -> None:
    """Answer 4 (t-1458): the driver's `system_file` gives the headless role the same line the hook gives and leaves ONE
    signal per dispatch; it no longer prints a note on stdout that tells the role nothing."""
    import types
    import story_run
    root = temp_project("qa-inject-h12d-")
    try:
        use_project(root)
        rules_file(root)
        state_dir = root / "qa-factory" / "artifacts" / TASK / "state"
        state_dir.mkdir(parents=True)
        ns = types.SimpleNamespace(task_root=state_dir.parent, state_dir=state_dir, project=root, plugin=SCRIPTS.parent, task=TASK,
                                   controller_state=lambda: {"revision": 1, "known_paths": {"project_root": "x"}})

        def boom(*_a, **_k):
            raise OSError("no such volume")
        real = RP.state_paths
        RP.state_paths = boom
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                path = story_run.Driver.system_file(ns, ROLE, "dsys", [])
        finally:
            RP.state_paths = real
        text = path.read_text(encoding="utf-8")
        check("H12 twin: the role's system prompt carries the same line as the hook gives",
              "the task packet carries no paths: the stored paths could not be resolved (OSError: no such volume); "
              "work from the prompt and name it under blocked" in text, text[-400:])
        check_eq("H12 twin: exactly one signal of kind inject", len(kinds(root, "inject")), 1)
        check_not_in("H12 twin: and no stdout note that tells the role nothing", "note:", out.getvalue())
    finally:
        cleanup(root)


def h13_h14() -> None:
    root = temp_project("qa-inject-h13-")
    try:
        use_project(root)
        code, out, _err = run_hook(root, None)
        check_eq("H13: an event that cannot be parsed: ALLOW (exit 0, nothing on stdout)", (code, out), (0, ""))
        rows = kinds(root, "inject")
        check("H13: and one signal of kind inject, written into the project named by the host's environment",
              len(rows) == 1 and "could not parse" in rows[0]["notes"], str(rows))
        # H14: any exception of the hook
        def explode(*_a, **_k):
            raise RuntimeError("boom")
        code, out, _err = run_hook(root, agent_event(root), patch={"collect_blocks": explode})
        check_eq("H14: a crash of the hook: ALLOW (exit 0, nothing on stdout)", (code, out), (0, ""))
        rows = kinds(root, "inject")
        check("H14: and a signal of kind inject naming the exception type",
              len(rows) == 2 and "RuntimeError: boom" in rows[-1]["notes"], str(rows))
        # F2: every DISTINCT crash of a session leaves its signal; the same crash repeated stays one
        def other_boom(*_a, **_k):
            raise KeyError("another cause")
        run_hook(root, agent_event(root), patch={"collect_blocks": other_boom})
        check_eq("F2: a second crash, of another cause, in the same session leaves its own signal", len(kinds(root, "inject")), 3)
        run_hook(root, agent_event(root), patch={"collect_blocks": other_boom})
        run_hook(root, agent_event(root), patch={"collect_blocks": explode})
        check_eq("F2: ...and the same crash repeated stays one", len(kinds(root, "inject")), 3)
        # K7: an advice queued on the way never rides beside the rewrite object; it goes to the person
        def with_notice(role, imap, event=None, kind="first"):        # the hook passes the dispatch kind (RC1-14 part 2, N1)
            hooklib.notice(event, "queued by the way", reader="orchestrator")
            return ["\n\nBLOCK"]
        code, out, _err = run_hook(root, agent_event(root), patch={"collect_blocks": with_notice})
        check("K7: the stdout is exactly the one rewrite object", code == 0 and out.count("\n") == 1 and "additionalContext" not in out, out[:120])
        check("K7: the queued advice went to the journal as a signal of kind inject, through rewrite_output (M1: no event hack)",
              any("queued by the way" in r["notes"] for r in kinds(root, "inject")))
        check_eq("K7: ...and the queue is empty when main ends", hooklib._NOTICES, [])
    finally:
        cleanup(root)


def e24() -> None:
    root = temp_project("qa-inject-e24-")
    try:
        use_project(root)
        rules_file(root)
        denials = root / "qa-factory" / "artifacts" / TASK / "state" / "dispatch-denials.jsonl"
        for label, content in (("not JSON", "{not json"), ("an empty file", ""), ("a JSON list", "[]")):
            if (root / "qa-factory" / "artifacts" / TASK).exists():
                (root / "qa-factory" / "artifacts" / TASK / "state" / "controller.json").write_text(content, encoding="utf-8")
            else:
                make_story(root, content)
            if denials.exists():
                denials.unlink()
            code, out, err = run_hook(root, agent_event(root))
            check_eq(f"E24 ({label}): an existing controller.json that cannot be read refuses: exit 2, no ALLOW on stdout", (code, out), (2, ""))
            check_in(f"E24 ({label}): the receipt refusal text", IC.RECEIPT_REASON, err)
            rows = [json.loads(line) for line in denials.read_text(encoding="utf-8").splitlines()] if denials.exists() else []
            check(f"E24 ({label}): and the note_denial line is written", len(rows) == 1 and rows[0]["reason"] == IC.RECEIPT_REASON
                  and rows[0]["role"] == ROLE and rows[0]["dispatch_id"] == f"S0-{ROLE}-1", str(rows))
        # B1 (t-1458): a controller.json that PARSES but whose receipt cannot be read refuses the same way
        state_file = root / "qa-factory" / "artifacts" / TASK / "state" / "controller.json"
        for label, doc in (("dispatches a list", {"revision": 1, "source_revision": "src", "dispatches": []}),
                           ("a dispatch entry not an object", {"revision": 1, "source_revision": "src", "dispatches": {"d1": "x"}}),
                           ("resolved_model a string", {"revision": 1, "dispatches": {
                               "d1": {"role": ROLE, "status": "running", "resolved_model": "opus"}}})):
            state_file.write_text(json.dumps(doc), encoding="utf-8")
            if denials.exists():
                denials.unlink()
            code, out, err = run_hook(root, agent_event(root))
            check_eq(f"E24/B1 ({label}): an unreadable receipt refuses: exit 2, no ALLOW on stdout", (code, out), (2, ""))
            check_in(f"E24/B1 ({label}): the receipt refusal text", IC.RECEIPT_REASON, err)
            rows = [json.loads(line) for line in denials.read_text(encoding="utf-8").splitlines()] if denials.exists() else []
            check(f"E24/B1 ({label}): and the note_denial line is written", len(rows) == 1 and rows[0]["reason"] == IC.RECEIPT_REASON, str(rows))
        # the receipt is read BEFORE the fail-open injection: a crash there cannot skip the refusal
        def explode(*_a, **_k):
            raise RuntimeError("boom")
        state_file.write_text("{not json", encoding="utf-8")
        code, out, err = run_hook(root, agent_event(root), patch={"collect_blocks": explode})
        check_eq("E24/B1: a crash in the injection does not skip the receipt refusal", (code, out, IC.RECEIPT_REASON in err), (2, "", True))
        # F1: a BOM'd controller.json is readable, as everywhere else
        state_file.write_text(chr(0xFEFF) + json.dumps({"revision": 1}), encoding="utf-8")
        code, out, _err = run_hook(root, agent_event(root))
        check("F1: a BOM'd readable controller.json: ALLOW with the packet", code == 0 and "Resolved task packet" in prompt_of(out), f"{code} {out[:80]}")
        check_eq("E24: a refusal is not a signal of kind inject", kinds(root, "inject"), [])
        # the control: a readable controller.json with no source revision still lets the dispatch through
        (root / "qa-factory" / "artifacts" / TASK / "state" / "controller.json").write_text(json.dumps({"revision": 1}), encoding="utf-8")
        code, out, _err = run_hook(root, agent_event(root))
        check("E24 control: a readable controller.json: ALLOW with the packet", code == 0 and "Resolved task packet" in prompt_of(out))
        # the old refusal stays: a source revision and no running dispatch of the role
        (root / "qa-factory" / "artifacts" / TASK / "state" / "controller.json").write_text(
            json.dumps({"revision": 1, "source_revision": "src", "dispatches": {}}), encoding="utf-8")
        code, out, err = run_hook(root, agent_event(root))
        check("E24 control: the missing-receipt refusal is unchanged", code == 2 and IC.RECEIPT_REASON in err and out == "", f"{code} {err}")
    finally:
        cleanup(root)


def main() -> None:
    h15_golden()
    end_to_end()
    h10_h11()
    h12()
    h12_driver_twin()
    h13_h14()
    e24()
    finish("test_inject_notices")


if __name__ == "__main__":
    main()
