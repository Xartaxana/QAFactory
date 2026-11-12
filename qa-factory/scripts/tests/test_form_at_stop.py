#!/usr/bin/env python3
"""X2-3 (spec t-1765): the stop no longer refuses the role's handover form; `story_step finish` does, with its own code.

The SC2-38 (1) check `exit_gate.form_stop_errors` read the form at the first stop and sent the role back with the form's
problems: a second refusal of the same fact `finish` refuses with `--fix` (21 of 26 blocks of run 14857 were the digest and
form blocks), and a judgment of the form's CONTENT by a gate (AR-29). It is removed together with its A24 record
(`EG-form-at-stop`) and its joint row (`exit:form_stop_errors`). What stays is one case:

  X2-3 a stop of a role whose form still has a blank field is NOT refused (exit 0, nothing run on the form); the same form is
       refused by `finish`'s own check (`story_step._handoff_check`: status `untouched` or `problems`, never `green`)
  X2-3 the function, its constant and its call in `main` are gone

Mutant (test file: this one): `main` calls a form check again -> the stop of the red form exits 2.
"""
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, run_script, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import exit_gate as gate  # noqa: E402
import story_step  # noqa: E402

TASK, ROLE, STAGE, DISPATCH = "QA-FS", "qa-scout", "S1", "S1-qa-scout-1"
real_all = gate.all_errors
real_awaiting = gate.awaiting_source_review


def story(prefix):
    """A project whose controller holds one running dispatch of the scout and the real untouched handover form `handoff_init.py`
    writes for it."""
    root = temp_project(prefix)
    use_project(root)
    state = root / "qa-factory" / "artifacts" / TASK / "state"
    state.mkdir(parents=True)
    rows = {DISPATCH: {"id": DISPATCH, "stage": STAGE, "role": ROLE, "status": "running"}}
    (state / "controller.json").write_text(json.dumps({"dispatches": rows}), encoding="utf-8")
    done = run_script("handoff_init.py", "--task", TASK, "--stage", STAGE, "--role", ROLE, "--dispatch", DISPATCH, cwd=root,
                      env=dict(__import__("os").environ, CLAUDE_PROJECT_DIR=str(root)))
    check_eq("setup: handoff_init wrote the form", done.returncode, 0)
    return root


def invoke_main(digest=""):
    """`(exit code, stderr)` of the SubagentStop hook for the scout, the gate's other checks answering clean."""
    gate.all_errors = lambda *a, **k: ([], [])
    gate.awaiting_source_review = lambda agent, task: False
    gate.handoff_digest = lambda event: digest
    gate.read_event = lambda: {"hook_event_name": "SubagentStop", "agent_type": "qa-factory:" + ROLE, "session_id": "s-fs",
                               "task_id": TASK, "dispatch_id": DISPATCH, "completion_attempt": "a1", "input_fingerprint": "f1"}
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            try:
                gate.main()
                code = 0
            except SystemExit as exc:
                code = int(exc.code or 0)
    finally:
        gate.all_errors = real_all
        gate.awaiting_source_review = real_awaiting
    return code, err.getvalue()


def x2_3_a_red_form_is_not_a_block_at_the_stop():
    root = story("fs-x23-")
    try:
        form = root / "qa-factory" / "artifacts" / TASK / story_step.FORM_REL.format(dispatch_id=DISPATCH)
        before = form.read_bytes()
        code, text = invoke_main()
        check_eq("X2-3 the stop of a role whose form is still blank is released: exit 0, nothing said", (code, text), (0, ""))
        check_eq("X2-3 the form file is byte for byte what it was (a gate writes nothing)", form.read_bytes(), before)
        status, _note, rel = story_step._handoff_check(TASK, DISPATCH, root / "qa-factory" / "artifacts" / TASK)
        check("X2-3 `finish` refuses the same form with its own code (status is not green)", status in ("untouched", "problems"),
              f"{status} {rel}")
    finally:
        cleanup(root)


def x2_3_the_check_is_gone():
    check("X2-3 `form_stop_errors` is no function of the gate", not hasattr(gate, "form_stop_errors"))
    check("X2-3 ... nor its path constant", not hasattr(gate, "FORM_REL"))


def main():
    x2_3_a_red_form_is_not_a_block_at_the_stop()
    x2_3_the_check_is_gone()
    finish("test_form_at_stop")


if __name__ == "__main__":
    main()
