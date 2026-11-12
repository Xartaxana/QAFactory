#!/usr/bin/env python3
"""RH1-5 B5: the driver does not resume a role over a gate that could not run. K2 (`Driver.exit_errors` raises one
`Refusal(title="gate_unreadable")` with `known=False`; the role is NOT resumed; `route_known` answers None), the gate raising
is the same refusal, a record the named word passed (`passed`) raises nothing (E17), a mixed set keeps both lists (E2)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import exit_gate as EG  # noqa: E402
import hooklib  # noqa: E402
import story_run  # noqa: E402

ROLE = "qa-automator"


def make_driver(root: Path):
    driver = object.__new__(story_run.Driver)
    driver.task = "QA-D1"
    driver.task_root = root / "qa-factory" / "artifacts" / "QA-D1"
    driver.state_dir = driver.task_root / "state"
    driver.dry = False
    driver.calls = []
    return driver


def main() -> None:
    root = temp_project("qa-drv-unr-")
    real_all, real_signal = EG.all_errors, hooklib.person_signal
    signals = []
    hooklib.person_signal = lambda event, kind, text, **kw: signals.append((kind, text, kw.get("task"))) or True
    try:
        driver = make_driver(root)
        driver.task_root.mkdir(parents=True)
        resumed = []
        # the roads that would spend money over the role: none may run
        for name in ("run_claude", "assemble_digest", "shorten_form", "resume"):
            setattr(driver, name, lambda *a, **k: resumed.append(name))
        unreadable = EG.unreadable_record("s5_precheck.py", "boom")
        finding = DV.Record("s5_precheck.py: [c 1] bad", script="s5_precheck.py")

        EG.all_errors = lambda *a, **k: ([unreadable], [])
        try:
            driver.exit_errors(ROLE, "digest")
            refusal = None
        except story_run.Refusal as exc:
            refusal = exc
        check("K2: an unreadable record raises a Refusal", refusal is not None)
        check_eq("K2: title gate_unreadable, known False", (refusal.title, refusal.known), ("gate_unreadable", False))
        check_eq("K2: route_known(refusal) is None (the conductor takes it, not the table)", story_run.route_known(refusal), None)
        check_in("K2: the text names the check", "s5_precheck.py: unreadable - boom", refusal.text)
        check_in("K2: and says the role is not resumed", "the role is NOT resumed", refusal.text)
        check_eq("K2: nothing that spends money over the role ran", resumed, [])
        check_eq("K2: one gate_unreadable signal with the task", [(k, t) for k, _x, t in signals], [("gate_unreadable", "QA-D1")])

        # the gate itself raises: the same refusal
        EG.all_errors = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gate bug"))
        try:
            driver.exit_errors(ROLE, "digest")
            raised = None
        except story_run.Refusal as exc:
            raised = exc
        check("the gate raising is the same refusal", raised is not None and raised.title == "gate_unreadable" and raised.known is False)
        check_in("...with the exception named", "RuntimeError: gate bug", raised.text)

        # E2: a mixed set: both lists, unreadable first
        EG.all_errors = lambda *a, **k: ([finding, unreadable], [])
        try:
            driver.exit_errors(ROLE, "digest")
            mixed = None
        except story_run.Refusal as exc:
            mixed = exc
        check_eq("E2: the refusal carries the unreadable line first, then the author's finding",
                 [("unreadable" in f) for f in mixed.findings], [True, False])

        # E17: passed by the named word -> nothing raised; plain findings -> the list as before
        EG.all_errors = lambda *a, **k: ([], [{"error": unreadable, "decision": "go on", "at": "t"}])
        check_eq("E17: a record in `passed` raises nothing and the list is empty", driver.exit_errors(ROLE, "digest"), [])
        EG.all_errors = lambda *a, **k: ([finding], [])
        check_eq("control: plain findings come back as the list (the role is resumed over them, as before)",
                 driver.exit_errors(ROLE, "digest"), [finding])
    finally:
        EG.all_errors, hooklib.person_signal = real_all, real_signal
        cleanup(root)
    finish("test_driver_gate_unreadable")


if __name__ == "__main__":
    main()
