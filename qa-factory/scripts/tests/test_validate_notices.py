#!/usr/bin/env python3
"""RH1-5 B10: `validate_artifacts` (PostToolUse) says its advice through the host adapter and its own failures by exit 2.
H16 (NEXT_STEPS and notes: `additionalContext` of PostToolUse on Claude, no `permissionDecision`; Codex keeps its shape;
a "factory finding" is a `validate` signal for the person), H18 (the event does not parse: exit 2 feedback, was a silent exit 1),
H19 (the validator crashes: exit 2 feedback naming the file and the hand check, was a silent exit 1)."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import runtime_paths as RP  # noqa: E402


def hook(root: Path, event, raw=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(SCRIPTS))
    data = raw if raw is not None else json.dumps(event)
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "validate_artifacts.py")], input=data, text=True, capture_output=True,
                          encoding="utf-8", cwd=str(root), env=env, timeout=120)


def patched(root: Path, name: str, patch: str, event):
    """Run `validate_artifacts.main()` in a child with `patch` applied first (a crash cannot be made from outside)."""
    runner = root / name
    runner.write_text("import sys\nsys.path.insert(0, %r)\nimport validate_artifacts as V\n%s\nsys.argv = ['validate_artifacts.py']\nV.main()\n"
                      % (str(SCRIPTS), patch), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", str(runner)], input=json.dumps(event), text=True, capture_output=True,
                          encoding="utf-8", cwd=str(root), env=env, timeout=120)


def main() -> None:
    root = temp_project("qa-validate-notices-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-V1"
        art.mkdir(parents=True)
        target = art / "understanding.md"          # a name in NEXT_STEPS
        target.write_text("# understanding\n", encoding="utf-8")
        import validate_artifacts as VA
        check("the fixture file name has a next-step hint", target.name in VA.NEXT_STEPS, target.name)
        event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "v1", "cwd": str(root),
                 "tool_input": {"file_path": str(target), "content": "# understanding\n"}}
        done = patched(root, "run_clean.py", "V.collect_errors = lambda *a, **k: []", event)
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        check_eq("H16: exit 0 and exactly one JSON object on stdout (K7)", (done.returncode, len(lines)), (0, 1))
        body = json.loads(lines[0])["hookSpecificOutput"] if lines else {}
        check_eq("H16: Claude PostToolUse: hookEventName", body.get("hookEventName"), "PostToolUse")
        check_in("H16: ...additionalContext carries the next step", VA.NEXT_STEPS[target.name][:30], body.get("additionalContext", ""))
        check_not_in("H16: no permissionDecision in it", "permissionDecision", done.stdout)
        # H18: broken stdin -> exit 2 with a door
        done = hook(root, None, raw="not json at all")
        check_eq("H18: an event that does not parse is exit 2 (feedback), not the silent 1", done.returncode, 2)
        check_in("H18: ...naming the hand check", "validate_artifacts.py --check <file>", done.stderr)
        check_in("H18: ...and that it is the factory's own defect", "the factory's own defect", done.stderr)
        # H19: collect_errors crashes
        done = patched(root, "run_boom.py", "def boom(*a, **k):\n    raise RuntimeError('validator bug')\nV.collect_errors = boom", event)
        check_eq("H19: a crashing validator is exit 2 (feedback), not the silent 1", done.returncode, 2)
        check_in("H19: ...naming the file and the exception", "understanding.md was written but not validated (RuntimeError: validator bug)", done.stderr)
        check_in("H19: ...and the hand check", "validate_artifacts.py --check <file>", done.stderr)
        # a finding of the factory goes to the person
        done = patched(root, "run_finding.py", "V.collect_errors = lambda *a, **k: []\nV.collect_findings = lambda p: ['a finding of the factory']", event)
        check_not_in("H16: a 'factory finding' is NOT printed to the model channel", "a finding of the factory", done.stdout)
        journal = RP.record(root, "journal.jsonl")
        rows = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines()] if journal.is_file() else []
        check_eq("H16: ...it is a `validate` signal in the journal, naming the file",
                 [(r["kind"], "understanding.md: a finding of the factory" in r["notes"]) for r in rows if r.get("event") == "hook_signal"],
                 [("validate", True)])
    finally:
        cleanup(root)
    finish("test_validate_notices")


if __name__ == "__main__":
    main()
