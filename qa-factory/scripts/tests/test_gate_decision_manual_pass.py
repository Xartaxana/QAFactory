#!/usr/bin/env python3
"""HF4-14: gate A recorded through the controller (the conductor's road) makes `manual-agent` rows executable.

Run 12586 (0.10.3): the conductor recorded gate A with `controller.py --operation gate-decision`; the plan kept the
obligations of the manual-agent rows TS-10/TS-12 as `new` (no evidence policy), `manual_evidence.prepare_request`
refused them (`semantic_reopen`), and the owner had to reopen gate A. Only the driver road ran the pass
(`planning_contract.apply_gate_answers` -> `_manual_agent_pass`). The seam is the recorded plan between two real
functions: the controller's gate-decision operation and `manual_evidence.prepare_request`.

The fixture `fixtures/run-12586-manual/TP1-12586` is the recorded run's task root cut at the event before the
gate A decision (README.txt there: sources and what was changed).
"""
import contextlib
import io
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, finish, temp_project, cleanup  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CTL  # noqa: E402
import manual_evidence as M  # noqa: E402
import planning_contract as PC  # noqa: E402
from event_store import content_hash  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-manual" / "TP1-12586"
UI_CASES = {"TC-010": ["OB-13"], "TC-012": ["OB-15"]}


def story(root):
    """The recorded task root, copied into a throwaway project (the marker `log_append` needs is `temp_project`'s)."""
    task = root / "qa-factory" / "artifacts" / "TP1-12586"
    shutil.copytree(FIXTURE, task)
    return task


def plan_of(task):
    return json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8-sig"))


def obligations(task):
    return {o["obligation_id"]: o for row in plan_of(task)["rows"] for o in row.get("coverage_obligations") or []}


def decide(root, task, *extra):
    """`controller.py --operation gate-decision --gate A --as-is` in-process; (exit code, parsed stdout)."""
    argv = ["controller.py", "--task-root", str(task), "--operation", "gate-decision", "--gate", "A", "--as-is",
            "--words-file", str(task / "state" / "words" / "gate-a-decision.txt"), *extra]
    out, err, code = io.StringIO(), io.StringIO(), 0
    old_argv, old_env = sys.argv, os.environ.get("CLAUDE_PROJECT_DIR")
    sys.argv, os.environ["CLAUDE_PROJECT_DIR"] = argv, str(root)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CTL.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv = old_argv
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
    text = out.getvalue().strip()
    return code, (json.loads(text) if text.startswith("{") else {"stdout": text, "stderr": err.getvalue()})


def pass_alone(task) -> list:
    """The manual-agent pass ALONE through the one seam (`PC.apply_gate_answers` with no words and `blocked="skip"`): its lines."""
    lines = []
    PC.apply_gate_answers(task, "", pass_lines=lines, blocked="skip")
    return lines


def refusal_of(task, case, ids):
    try:
        M.prepare_request(task, case, ids)
    except M.Refused as exc:
        return exc
    return None


# --- the seam: gate-decision (real controller) -> the plan on disk -> prepare_request (real) -----------------------

def the_conductor_road_makes_manual_rows_executable():
    root = temp_project("qa-gate-manual-pass-")
    try:
        task = story(root)
        before = obligations(task)
        check_eq("fixture: OB-13 is `new` as the strategist authored it", before["OB-13"]["decision"], "new")
        check_eq("fixture: OB-15 is `new`, without an evidence policy", (before["OB-15"]["decision"], before["OB-15"].get("evidence_policy")),
                 ("new", None))
        check_eq("fixture: OB-17 is unresolved (Q7 not settled at the cut)",
                 (before["OB-17"]["decision"], before["OB-17"]["oracle_status"]), ("unresolved", "unresolved"))

        code, result = decide(root, task)
        check_eq("gate-decision exits 0 and records", (code, result.get("recorded")), (0, True))
        after = obligations(task)
        check_eq("OB-13 became manual-agent with the row's `ui` policy", (after["OB-13"]["decision"], after["OB-13"]["evidence_policy"]),
                 ("manual-agent", "ui"))
        check_eq("OB-15 became manual-agent with `ui`", (after["OB-15"]["decision"], after["OB-15"]["evidence_policy"]), ("manual-agent", "ui"))
        check_eq("OB-17 stays as planned: an unresolved oracle never becomes executable (P20, FR-59)",
                 (after["OB-17"]["decision"], after["OB-17"]["oracle_status"], after["OB-17"].get("evidence_policy")),
                 ("unresolved", "unresolved", None))
        check_eq("no other obligation changed", {k: v for k, v in after.items() if k not in ("OB-13", "OB-15")},
                 {k: v for k, v in before.items() if k not in ("OB-13", "OB-15")})
        said = result.get("manual_pass") or []
        check("the decision output says which rows were made executable", any("OB-13" in s for s in said) and any("OB-15" in s for s in said))
        check("Q-2: the unresolved OB-17 gets one reason line (FR-59)",
              sum("OB-17 stays as planned" in s and "has not been settled" in s for s in said) == 1)
        check_eq("the receipt stays last in the answer", list(result)[-1], "decision")
        # POSITION: the recorded hash is the hash of the converted plan (nothing changed after the decision)
        recorded = result["decision"]["payload"]["plan_content_hash"]
        check_eq("the recorded plan hash covers the converted rows", recorded, content_hash(plan_of(task)))
        for case, ids in UI_CASES.items():
            check(f"prepare_request({case}, {ids}) no longer raises", refusal_of(task, case, ids) is None)
        request = M.prepare_request(task, "TC-010", ["OB-13"])
        check_eq("the request carries the approved policy", (request["evidence_policy"], request["gate_a_decision_ref"]),
                 ("ui", "gateA-TP1-12586"))
    finally:
        cleanup(root)


def negative_control_without_the_pass():
    """The same decision with the pass removed raises as on the stand (the test can fail)."""
    root = temp_project("qa-gate-manual-pass-neg-")
    real = PC._manual_agent_pass
    try:
        task = story(root)
        PC._manual_agent_pass = lambda *a, **k: False
        code, result = decide(root, task)
        check_eq("control: the decision records without the pass", (code, result.get("recorded")), (0, True))
        check_eq("control: OB-13 stays `new`", obligations(task)["OB-13"]["decision"], "new")
        exc = refusal_of(task, "TC-010", ["OB-13"])
        check("control: prepare_request raises Refused", exc is not None)
        check_eq("control: with the door `semantic_reopen`, as on the stand", getattr(exc, "door_code", None), "semantic_reopen")
        check_in("control: the words the stand showed", "still has this check as `new`", str(exc))
    finally:
        PC._manual_agent_pass = real
        cleanup(root)


# --- edges ---------------------------------------------------------------------------------------------------------

def a_preview_runs_no_pass():
    root = temp_project("qa-gate-manual-pass-prev-")
    try:
        task = story(root)
        was = (task / "work" / "test-plan.json").read_bytes()
        code, result = decide(root, task, "--build-only")
        check_eq("--build-only does not record", (code, result.get("recorded")), (0, False))
        check_eq("--build-only leaves the plan byte for byte", (task / "work" / "test-plan.json").read_bytes(), was)
        check("--build-only has no recorded-pass line (`manual_pass` is for a recorded decision)", "manual_pass" not in result)
        check("--build-only says what recording WOULD do, as a conditional key",
              any("OB-13" in s for s in result.get("manual_pass_if_recorded") or []))
        # Q-3: the preview's hash is the hash the real record binds (the converted plan), not the unconverted one
        second = temp_project("qa-gate-manual-pass-prev2-")
        try:
            other = story(second)
            code2, real = decide(second, other)
            check_eq("Q-3: the preview shows the plan hash a real record binds",
                     result["request"]["plan_content_hash"], real["decision"]["payload"]["plan_content_hash"])
            check("Q-3: and that is not the hash of the plan as authored",
                  result["request"]["plan_content_hash"] != content_hash(json.loads(was.decode("utf-8-sig"))))
        finally:
            cleanup(second)
    finally:
        cleanup(root)


def gate_a_is_current(root, task):
    c = CTL.Controller(task, wait_seconds=0)
    try:
        c._validate_gate_a_content_current(c.state())
    except Exception as exc:
        return False, str(exc)
    return True, ""


def a_call_that_does_not_record_keeps_no_plan_byte():
    """F1/M4: a refused call (or one that raises) writes nothing; over an existing approval it must not void it."""
    root = temp_project("qa-gate-manual-pass-refuse-")
    real_pass, real_check = PC._manual_agent_pass, CTL.Controller.check_decision
    plan = None
    try:
        task = story(root)
        plan = task / "work" / "test-plan.json"
        # (a) a fresh gate A, refused: the plan stays as authored and the answer does not claim "made executable"
        was = plan.read_bytes()
        CTL.Controller.check_decision = lambda self, payload: ["synthetic factory problem"]
        code, refused = decide(root, task)
        CTL.Controller.check_decision = real_check
        check_eq("(a) the refused call exits 2", code, 2)
        check_eq("(a) a refusal with no decision leaves the plan byte for byte", plan.read_bytes(), was)
        said = json.loads(refused["stderr"].strip().splitlines()[-1])
        check("(a) the refusal carries no recorded-pass key, only the conditional one",
              "manual_pass" not in said and any("OB-13" in s for s in said.get("manual_pass_if_recorded") or []))
        # (b) gate A recorded dry (the 0.10.3 way), then a refused second call: the approval stands
        PC._manual_agent_pass = lambda *a, **k: False
        code, dry = decide(root, task)
        PC._manual_agent_pass = real_pass
        check_eq("(b) the dry record is made", (code, dry.get("recorded")), (0, True))
        check_eq("(b) the dry plan kept OB-13 `new`", obligations(task)["OB-13"]["decision"], "new")
        was = plan.read_bytes()
        check("(b) the dry approval is current", gate_a_is_current(root, task)[0])
        CTL.Controller.check_decision = lambda self, payload: ["synthetic factory problem"]
        code, refused = decide(root, task)
        CTL.Controller.check_decision = real_check
        check_eq("(b) the second call is refused", code, 2)
        check_eq("(b) the refused call leaves the plan byte for byte", plan.read_bytes(), was)
        ok, why = gate_a_is_current(root, task)
        check("(b) and the existing approval is not stale", ok, why)
        # (c) a call that raises after the pass: the same
        CTL.Controller.check_decision = lambda self, payload: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            decide(root, task)
        except RuntimeError:
            pass
        CTL.Controller.check_decision = real_check
        check_eq("(c) an exception after the pass leaves the plan byte for byte", plan.read_bytes(), was)
        check("(c) and the approval is not stale", gate_a_is_current(root, task)[0])
        # (d) the recording path still converts, and a repeat record (Q-1) leaves the converted bytes equal
        code, ok_run = decide(root, task)
        check_eq("(d) the next real call records", (code, ok_run.get("recorded")), (0, True))
        check_eq("(d) and converts", obligations(task)["OB-13"]["decision"], "manual-agent")
        converted = plan.read_bytes()
        code, again = decide(root, task)
        check_eq("Q-1: a second record over a current decision is still allowed", (code, again.get("recorded")), (0, True))
        check_eq("Q-1: the pass is idempotent - a repeat record leaves the plan bytes equal", plan.read_bytes(), converted)
        check("Q-1: and writes no pass line for rows already converted",
              not any("made executable" in s for s in again.get("manual_pass") or []))
    finally:
        PC._manual_agent_pass, CTL.Controller.check_decision = real_pass, real_check
        cleanup(root)


def a_row_the_pass_cannot_convert_stays_with_its_reason():
    root = temp_project("qa-gate-manual-pass-stays-")
    try:
        task = story(root)
        path = task / "work" / "test-plan.json"
        plan = plan_of(task)
        for row in plan["rows"]:
            for ob in row.get("coverage_obligations") or []:
                if ob["obligation_id"] == "OB-15":
                    # a valid plan (an unresolved oracle on a `new` obligation is refused by the plan's own check): the
                    # obligation is a recommendation for later, which the pass must not make executable
                    ob["execution_scope"] = "recommended_regression"
        path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
        code, result = decide(root, task)
        check_eq("the decision still records", (code, result.get("recorded")), (0, True))
        after = obligations(task)
        check_eq("OB-15, a recommendation for later, stays `new`", after["OB-15"]["decision"], "new")
        check_eq("OB-13 is converted all the same", after["OB-13"]["decision"], "manual-agent")
        said = " | ".join(result.get("manual_pass") or [])
        check("one line names OB-15 and why it stays", "OB-15 stays as planned" in said and "recommendation for later" in said)
        raised = refusal_of(task, "TC-012", ["OB-15"])
        check("prepare_request still refuses the unconverted row (error direction: not executable)", raised is not None)
    finally:
        cleanup(root)


def the_pass_is_idempotent_and_no_manual_rows_means_no_change():
    root = temp_project("qa-gate-manual-pass-idem-")
    try:
        task = story(root)
        decide(root, task)
        converted = (task / "work" / "test-plan.json").read_bytes()
        check_eq("a second pass changes nothing and says nothing (OB-17's line is for a run that converted)",
                 pass_alone(task), [])
        check_eq("and writes no byte", (task / "work" / "test-plan.json").read_bytes(), converted)
        plan = plan_of(task)
        for row in plan["rows"]:
            if row.get("disposition") == "manual-agent":
                row["disposition"] = "automate"
        (task / "work" / "test-plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
        was = (task / "work" / "test-plan.json").read_bytes()
        check_eq("a plan with no manual-agent row: no line", pass_alone(task), [])
        check_eq("and no byte written", (task / "work" / "test-plan.json").read_bytes(), was)
        (task / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")
        said = PC.apply_gate_answers(task, "", pass_lines=[], blocked="skip")
        check("an unreadable plan never raises: one line, plan untouched",
              len(said) == 1 and "could not all be applied" in said[0] and (task / "work" / "test-plan.json").read_text() == "{not json")
        check_eq("no plan at all: nothing to do", pass_alone(root / "no-such-story"), [])
    finally:
        cleanup(root)


def both_roads_leave_the_same_plan():
    """AR-15: the driver road (`apply_gate_answers`) and the controller road end with one and the same plan."""
    first, second = temp_project("qa-gate-manual-road-a-"), temp_project("qa-gate-manual-road-b-")
    try:
        a, b = story(first), story(second)
        decide(first, a)
        lines = PC.apply_gate_answers(b, "approve as is")
        check("the driver road converted the rows too", any("OB-13" in s for s in lines))
        check_eq("same plan from both roads", plan_of(a), plan_of(b))
        check("Q-2, AR-19: the driver road names the unresolved OB-17 too, once",
              sum("OB-17 stays as planned" in s for s in lines) == 1)
        check_eq("and the driver road's pass followed by the controller's changes nothing",
                 pass_alone(b), [])
    finally:
        cleanup(first)
        cleanup(second)


def the_fixture_names_no_machine_path():
    """Tail B4 (t-1564, AR-4): no file of the fixture carries a user's home or a checkout path - the scrub of the red-then fixture
    (`machine_free`, build_fixture.py) leaves every file as it is, and the event chain reads (its hashes follow the payloads).
    Negative control: a file with a path in it is changed by the same function."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "run-12586-red-then" / "controller"))
    from build_fixture import machine_free
    dirty = [str(p.relative_to(FIXTURE)) for p in sorted(FIXTURE.rglob("*")) if p.is_file()
             and machine_free(p.read_bytes().decode("utf-8")) != p.read_bytes().decode("utf-8")]
    check_eq("B4: no file of the manual fixture names a machine path", dirty, [])
    check("B4 control: the same function does change a text with a drive path in it",
          machine_free("C:\\Users\\dev1\\x") != "C:\\Users\\dev1\\x")
    previous = ""
    for line in (FIXTURE / "state" / "events.jsonl").read_bytes().decode("utf-8").splitlines():
        event = json.loads(line)
        stored = event.pop("event_hash")
        check_eq(f"B4: event {event.get('sequence', '?')} chains to the one before and hashes its payload",
                 (event.get("previous_hash"), content_hash(event)), (previous, stored))
        previous = stored


if __name__ == "__main__":
    the_fixture_names_no_machine_path()
    the_conductor_road_makes_manual_rows_executable()
    negative_control_without_the_pass()
    a_preview_runs_no_pass()
    a_call_that_does_not_record_keeps_no_plan_byte()
    a_row_the_pass_cannot_convert_stays_with_its_reason()
    the_pass_is_idempotent_and_no_manual_rows_means_no_change()
    both_roads_leave_the_same_plan()
    finish("test_gate_decision_manual_pass")
