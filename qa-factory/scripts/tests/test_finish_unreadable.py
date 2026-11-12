#!/usr/bin/env python3
"""RH1-5 B4: `story_step finish` refuses by exit 2 when a check of the exit gate could not run. K1 (a precheck that crashes
inside: exit 2, nothing recorded, the text names `s5_precheck.py` and the reason), E1-E3 (the texts), E13 (the named word is
in the door), E14 (a decided dispatch is not re-read), E17 (a record the word passed does not refuse)."""
import contextlib
import io
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import exit_gate as EG  # noqa: E402
import hooklib  # noqa: E402
import s5_precheck  # noqa: E402
import story_step  # noqa: E402

ROLE = "qa-automator"


class Done:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def in_process_precheck(cmd, **kw):
    """The gate re-runs the detector as a subprocess; here the same script runs in this process so its `run` can be made to crash."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = s5_precheck.detector_main()
    return Done(code, out.getvalue())


def snapshot(root: Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def gate_answer(answer):
    EG.all_errors = lambda *a, **k: answer


def main() -> None:
    root = temp_project("qa-finish-unr-")
    use_project(root)       # GW1-10: the gate names the story to its detector through the project's own rule, so the project is this one
    signals = []
    real = {k: getattr(EG, k) for k in ("all_errors", "detector_gates", "scoped_errors", "witness_errors", "grounding_errors",
                                        "case_identity_errors", "digest_errors", "required_outputs_errors", "advice_detectors")}
    real_signal, real_run, real_sp_run = hooklib.person_signal, EG.subprocess.run, s5_precheck.run
    hooklib.person_signal = lambda event, kind, text, **kw: signals.append((kind, text)) or True
    try:
        task_root = root / "qa-factory" / "artifacts" / "QA-U1"
        task_root.mkdir(parents=True)
        args = Namespace(task="QA-U1", dispatch_id="s5-author-1")
        dispatch = {"role": ROLE, "stage": "S5", "id": "s5-author-1"}
        before = snapshot(task_root)

        # K1: the S5 precheck crashes inside, through the REAL all_errors path (only the other readers are silenced)
        EG.detector_gates = lambda stage="": {ROLE: ["s5_precheck.py"]}
        EG.advice_detectors = lambda agent="", stage="": set()
        for name in ("scoped_errors", "witness_errors", "grounding_errors", "case_identity_errors", "digest_errors", "required_outputs_errors"):
            setattr(EG, name, lambda *a, **k: [])
        EG.subprocess.run = in_process_precheck

        def crash(*_a, **_kw):
            raise RuntimeError("the check broke")
        s5_precheck.run = crash
        import planning_contract
        real_rs, real_art = planning_contract.running_story, s5_precheck.C.artifact
        planning_contract.running_story = lambda *a, **k: task_root
        s5_precheck.running_dispatch = lambda *a, **k: None
        s5_precheck.is_plan_dispatch = lambda *a, **k: False
        s5_precheck.C.artifact = lambda *a, **k: Path(__file__)
        try:
            code, text, notes = story_step._finish_gate(args, task_root, dispatch, {})
        finally:
            planning_contract.running_story, s5_precheck.C.artifact, s5_precheck.run = real_rs, real_art, real_sp_run
        check_eq("K1: a precheck that crashes inside is exit 2 under finish (not the old 0)", code, 2)
        check_in("K1: the text names the script", "s5_precheck.py: unreadable", text)
        check_in("K1: ...and the reason (the exception)", "RuntimeError: the check broke", text)
        check_not_in("K1: no repair marker (the factory's defect, not the author's)", "REPAIR", text.upper().replace("FACTORY'S OWN DEFECT", ""))
        check_eq("K1: nothing was written under the story", snapshot(task_root), before)
        check_eq("K1: one gate_unreadable signal was left for the report", [k for k, _t in signals], ["gate_unreadable"])
        check_in("E13: the door names the person's word for THIS script", '--block "s5_precheck.py: unreadable"', text)
        check_in("E13: and says the star and the bare word do not pass it", "`*` and the bare word `unreadable` do not pass it", text)
        check_in("the road of a halted role is still named", "story_step.py pause", text)

        # E1 / E2: both scripts named; a mixed set keeps the author's findings AFTER the unreadable ones
        a = EG.unreadable_record("s5_precheck.py", "boom")
        b = EG.unreadable_record("check_witness.py", "timed out after 120 s")
        gate_answer(([a, b], []))
        code, text, _n = story_step._finish_gate(args, task_root, dispatch, {})
        check_eq("E1: all unreadable: exit 2", code, 2)
        check("E1: both scripts are named", "s5_precheck.py: unreadable" in text and "check_witness.py: unreadable" in text, text)
        finding = DV.Record("s5_precheck.py: [c 1] a real finding", script="s5_precheck.py")
        gate_answer(([finding, a], []))
        code, text, _n = story_step._finish_gate(args, task_root, dispatch, {})
        check_eq("E2: mixed set: exit 2, never 3", code, 2)
        check("E2: the unreadable record comes first, the author's finding after it",
              0 <= text.index("could not run") < text.index("a real finding"), text)
        # E3: one unreadable among nothing else
        gate_answer(([a], []))
        check_eq("E3: one unreadable alone is still exit 2", story_step._finish_gate(args, task_root, dispatch, {})[0], 2)
        # the control: a plain finding is still exit 3, and clean is 0
        gate_answer(([finding], []))
        check_eq("control: a plain finding is exit 3 as before", story_step._finish_gate(args, task_root, dispatch, {})[0], 3)
        gate_answer(([], []))
        check_eq("control: clean is exit 0", story_step._finish_gate(args, task_root, dispatch, {})[0], 0)
        # E17: the record is in `passed` (the named word passed it): no refusal
        gate_answer(([], [{"error": a, "decision": "go on", "at": "t"}]))
        code, _t, notes = story_step._finish_gate(args, task_root, dispatch, {})
        check_eq("E17: an unreadable record the word passed does not refuse", code, 0)
        check_eq("E17: ...and the pass is noted", len(notes), 1)
        # E14: a dispatch the person decided is not re-read
        gate_answer(([a], []))
        code, _t, notes = story_step._finish_gate(args, task_root, dispatch, {"close": {"at": "t"}})
        check_eq("E14: a decided dispatch is not asked a second time (exit 0)", code, 0)
        check_in("E14: and says why", "was not re-read", notes[0])
        # the three older callers keep their text
        old = story_step._gate_unreadable(args, task_root, dispatch, "ValueError")
        check_in("the old text of a gate that could not be read is kept", "the exit gate could not be read (ValueError)", old)
    finally:
        for key, value in real.items():
            setattr(EG, key, value)
        EG.subprocess.run, hooklib.person_signal, s5_precheck.run = real_run, real_signal, real_sp_run
        cleanup(root)
    finish("test_finish_unreadable")


if __name__ == "__main__":
    main()
