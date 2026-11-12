#!/usr/bin/env python3
"""F10 (K-M3-29): the exit gate does not ask an S7 investigation dispatch for `work/triage.json`.

The newest S7 record of the role decides (the S5 plan twin, `test_s5_plan_controller.py` k10). An investigation record drops that ONE
output from the required list (a filter, not a blanket pass); a triage dispatch, an unreadable state and any other stage keep today's
check byte-for-byte.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import exit_gate  # noqa: E402
from test_s5_plan import put  # noqa: E402

ANALYST = "qa-failure-analyst"
TRIAGE = "work/triage.json"


def record(ident, purpose=None, stage="S7", role=ANALYST, top=None):
    rec = {"id": ident, "stage": stage, "role": role, "status": "running", "request_binding": {}}
    if purpose:
        rec["request_binding"]["purpose"] = purpose
    if top:
        rec["purpose"] = top
    return rec


def state_of(*records):
    return json.dumps({"dispatches": {r["id"]: r for r in records}})


def run(root, role=ANALYST):
    old = exit_gate.artifact_root
    exit_gate.artifact_root = lambda: Path(root).parent
    try:
        return exit_gate.required_outputs_errors(role, Path(root).name)
    finally:
        exit_gate.artifact_root = old


def k29a_investigation_needs_no_triage():
    root = temp_dir("qa-eg7-a-")
    try:
        put(root, "state/controller.json", state_of(record("t1"), record("i1", "investigation")))
        check("K-M3-29a premise: the triage is ABSENT right before the call (and no run-blocks)",
              not (Path(root) / TRIAGE).exists() and not (Path(root) / "work" / "run-blocks").exists())
        check_eq("K-M3-29a: the newest S7 record is an investigation, no triage -> nothing owed", run(root), [])
        put(root, "state/controller.json", state_of(record("t1"), record("i1", "investigation", top="triage")))
        check_eq("K-M3-29a: request_binding.purpose wins over a top-level purpose", run(root), [])
        old = exit_gate._s7_investigation_dispatch
        exit_gate._s7_investigation_dispatch = lambda art_dir, agent: None
        try:
            lines = run(root)
            check("K-M3-29a-neg: the same fixture without the S7 branch -> the required output is missing",
                  len(lines) == 1 and "missing required output" in lines[0] and TRIAGE in lines[0], str(lines))
        finally:
            exit_gate._s7_investigation_dispatch = old
    finally:
        cleanup(root)


def k29a_filter_not_blanket():
    root = temp_dir("qa-eg7-a2-")
    try:
        put(root, "state/controller.json", state_of(record("i1", "investigation")))
        model = {"stages": [{"id": "S7", "roles": [ANALYST], "required_outputs": [TRIAGE, "work/second.json"]}]}
        old = exit_gate.SG.stage_model
        exit_gate.SG.stage_model = lambda *a, **k: model
        try:
            lines = run(root)
        finally:
            exit_gate.SG.stage_model = old
        check("K-M3-29a filter: only the triage is dropped - a second required output is still asked",
              len(lines) == 1 and "work/second.json" in lines[0] and TRIAGE not in lines[0], str(lines))
    finally:
        cleanup(root)


def k29b_triage_dispatch_keeps_the_error():
    root = temp_dir("qa-eg7-b-")
    try:
        put(root, "state/controller.json", state_of(record("i1", "investigation"), record("t2")))
        lines = run(root)
        check("K-M3-29b: the newest record is a triage dispatch -> today's error (the newest one decides)",
              len(lines) == 1 and lines[0].startswith("S7 (qa-failure-analyst) is missing required output(s) named in references/stages.json for ")
              and lines[0].endswith(f"{TRIAGE} — write them before finishing, or hand the orchestrator a halt with the reason instead "
                                    "of an incomplete handoff."), str(lines))
        put(root, TRIAGE, "[]")
        check_eq("K-M3-29b control: with the triage present nothing is owed", run(root), [])
    finally:
        cleanup(root)


def k29c_unreadable_state_keeps_the_error():
    root = temp_dir("qa-eg7-c-")
    try:
        put(root, "state/controller.json", state_of(record("i1", "investigation")))
        want = exit_gate_error_without_state(root)
        put(root, "state/controller.json", "{broken")
        check_eq("K-M3-29c: an unreadable controller.json -> not an investigation, the full check", exit_gate._s7_investigation_dispatch(root, ANALYST), None)
        lines = run(root)
        check("K-M3-29c: the error is today's", len(lines) == 1 and TRIAGE in lines[0] and lines == want, str(lines))
    finally:
        cleanup(root)


def exit_gate_error_without_state(root):
    """Today's error for the same story, taken from a state with only a triage record."""
    put(root, "state/controller.json", state_of(record("t1")))
    return run(root)


def k29d_other_stage_untouched():
    root = temp_dir("qa-eg7-d-")
    try:
        put(root, "state/controller.json", state_of(record("i1", "investigation", stage="S5", role="qa-automator"),
                                                    record("i2", "investigation", role="qa-automator")))
        calls = []
        old = exit_gate._s7_investigation_dispatch
        exit_gate._s7_investigation_dispatch = lambda art_dir, agent: calls.append(agent)
        try:
            lines = run(root, "qa-automator")
        finally:
            exit_gate._s7_investigation_dispatch = old
        check("K-M3-29d: a non-S7 stage -> today's result (its own missing outputs)",
              len(lines) == 1 and lines[0].startswith("S5 (qa-automator) is missing required output(s)") and TRIAGE not in lines[0], str(lines))
        check_eq("K-M3-29d: the S7 reader is not even asked on another stage (the guard)", calls, [])
    finally:
        cleanup(root)


if __name__ == "__main__":
    k29a_investigation_needs_no_triage()
    k29a_filter_not_blanket()
    k29b_triage_dispatch_keeps_the_error()
    k29c_unreadable_state_keeps_the_error()
    k29d_other_stage_untouched()
    finish("test_exit_gate_s7_investigation")
