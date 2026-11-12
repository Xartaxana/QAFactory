#!/usr/bin/env python3
"""RH1-5 B2: the producers of the exit gate's detectors declare the third state. A detector that could not run prints
`UNREADABLE: <reason>` and exits 3 (never a silent 0); "nothing to check" stays exit 0 (the control); `stages.json`
declares only `sizing.py` an adviser (FR-13: data, not code)."""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import branch_accounting  # noqa: E402
import critic_rollcall  # noqa: E402
import detector_verdict as DV  # noqa: E402
import planning_contract  # noqa: E402
import s5_precheck  # noqa: E402
import sizing  # noqa: E402

PRODUCERS = (("s5_precheck", s5_precheck, lambda: s5_precheck.detector_main()),
             ("planning_contract", planning_contract, lambda: planning_contract.detector_main()),
             ("critic_rollcall", critic_rollcall, lambda: critic_rollcall.detector_main()),
             ("sizing", sizing, lambda: sizing.detector_main()),
             ("branch_accounting", branch_accounting, lambda: branch_accounting.detector_main()))      # K-N3-3 (t-1726)


def run(call):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = call()
    return code, out.getvalue()


def boom(*_a, **_k):
    raise OSError("disk gone")


def main() -> None:
    for name, module, call in PRODUCERS:
        real = planning_contract.running_story
        planning_contract.running_story = boom
        try:
            code, text = run(call)
        finally:
            planning_contract.running_story = real
        parsed = DV.parse(code, text, "")
        check_eq(f"{name}: running_story raising is exit 3", code, DV.EXIT_UNREADABLE)
        check(f"{name}: and one line `UNREADABLE: ` that names the exception", text.startswith(DV.UNREADABLE_PREFIX) and "OSError" in text, text)
        check_eq(f"{name}: parse reads it as unreadable, no finding", (bool(parsed["unreadable"]), parsed["findings"]), (True, []))
        planning_contract.running_story = lambda *a, **k: None
        try:
            code, text = run(call)
        finally:
            planning_contract.running_story = real
        if name == "branch_accounting":      # its own third state: a gate that finds no story judged nothing (exit 3, never a silent 0)
            check_eq(f"{name} (control): no running story is its own UNREADABLE, exit 3", (code, text.startswith(DV.UNREADABLE_PREFIX)), (3, True))
            continue
        check_eq(f"{name} (control): nothing to check (no running story) stays exit 0 and silent", (code, text), (0, ""))

    # an UNHANDLED exception inside the body is the same (planning_contract, critic_rollcall: the wrapper)
    real_story, real_path = planning_contract.running_story, planning_contract.story_plan_path
    planning_contract.running_story = lambda *a, **k: Path(".")
    planning_contract.story_plan_path = boom
    try:
        code, text = run(lambda: planning_contract.detector_main())
    finally:
        planning_contract.running_story, planning_contract.story_plan_path = real_story, real_path
    check_eq("planning_contract: an unhandled exception in the body is exit 3", (code, text.startswith(DV.UNREADABLE_PREFIX)), (3, True))
    real_files = critic_rollcall.findings_files
    planning_contract.running_story = lambda *a, **k: Path(".")
    critic_rollcall.findings_files = boom
    try:
        code, text = run(lambda: critic_rollcall.detector_main())
    finally:
        planning_contract.running_story, critic_rollcall.findings_files = real_story, real_files
    check_eq("critic_rollcall: an unhandled exception in the body is exit 3", (code, text.startswith(DV.UNREADABLE_PREFIX)), (3, True))

    # s5_precheck: the window check raising after a manifest exists
    real_run, real_dispatch = s5_precheck.run, s5_precheck.running_dispatch
    planning_contract.running_story = lambda *a, **k: Path(__file__).resolve().parent
    s5_precheck.running_dispatch = lambda *a, **k: None
    s5_precheck.is_plan_dispatch = lambda *a, **k: False
    real_art = s5_precheck.C.artifact
    s5_precheck.C.artifact = lambda *a, **k: Path(__file__)       # exists
    s5_precheck.run = boom
    try:
        code, text = run(lambda: s5_precheck.detector_main())
    finally:
        planning_contract.running_story = real_story
        s5_precheck.run, s5_precheck.running_dispatch, s5_precheck.C.artifact = real_run, real_dispatch, real_art
    check_in("s5_precheck: the window check raising is exit 3 and names the step", "checking the window", text)
    check_eq("s5_precheck: ...with the exit code of the third state", code, DV.EXIT_UNREADABLE)

    stages = json.loads((SCRIPTS.parent / "references" / "stages.json").read_text(encoding="utf-8"))["stages"]
    advice = [(s.get("id"), s["advice"]) for s in stages if s.get("advice")]
    check_eq("stages.json declares exactly one adviser: sizing.py on S2 (data, FR-13)", advice, [("S2", ["sizing.py"])])
    finish("test_detector_unreadable")


if __name__ == "__main__":
    main()
