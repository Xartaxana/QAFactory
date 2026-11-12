#!/usr/bin/env python3
"""A retry names its cause, and the Factory tab counts it once.

TP1-15045 ran 53 dispatches, 10 of them second attempts. The 0.7.13 Factory tab said
"retry dispatches: 10 - parents (10)": ten repeats, one parent id each, no cause, although
every parent's checkpoint reason held the answer. The same tab drew F03/F05/F06/F07 twice --
once as a "Factory health" card and once as a "Quality and outcomes" widget one screen below.
This file holds the controller stamp, the projected split by cause, the banner threshold and
the absence of the duplicated section.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish, run_mode, temp_dir, cleanup  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import factory_dashboard as D  # noqa: E402
import metrics_projection as MP  # noqa: E402
from controller import Controller  # noqa: E402
from dashboard_widgets import render as render_widgets  # noqa: E402

import test_controller_rework_scope as SCOPE  # noqa: E402  (the gate-A task fixture)

# The wording of the real checkpoints of TP1-15045, as the run left them in
# state/controller.json, with the reason each one classifies to.
REAL_CHECKPOINTS = [
    ("source review awaiting the person", "awaiting_person"),
    ("understanding blocked: 1 blocking question (AC-6 oracle) awaiting the person", "awaiting_person"),
    ("test toolchain was not installed; now installed via poetry install", "environment"),
    ("window ran out of turn budget mid-diagnosis of TC-001 live load timeout", "turn_budget"),
    ("turn-budget guard fired at 780 to 810 calls mid red probe", "turn_budget"),
    ("window budget exhausted after TC-007 and TC-008 work", "turn_budget"),
    ("node_ids.py collect-only parser breaks under pytest.ini addopts=-v: run_suite.py "
     "--mine cannot launch any node-id-addressed test", "factory_defect"),
    ("11/11 real instances fresh-green under 0.7.8; all fixable smells fixed+reverified. "
     "Awaiting orchestrator disposition next window.", "checkpoint"),
]


def resume(controller, parent, child, reason, **extra):
    """Checkpoint the running dispatch with `reason`, then resume it from its checkpoint."""
    checkpoint = {"completed": ["TC-1"], "next": "finish"}
    controller.apply("checkpoint", {"id": parent, "status": "incomplete", "reason": reason,
                                    "checkpoint": checkpoint, "idempotency_key": parent + "-cp"})
    packet = {"id": child, "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
              "input_hash": "h", "budget": {}, "known_paths": {}, "parent_retry": parent,
              "checkpoint": checkpoint, "idempotency_key": child}
    packet.update(extra)
    controller.apply("dispatch", packet)
    return controller.state()["dispatches"][child]


def controller_stamps_the_cause_of_every_retry():
    root = temp_dir("qa-retry-stamp-")
    try:
        c = SCOPE.gate_a_task(root)
        # SC1-14 B1b: this test is about the retry cause, not the plan order; the fixture's case files have no Then, so it has no
        # plan to write and begins on the earlier form (the form is fixed by the first S5 record, `s5_plan.mode`).
        with run_mode("driver"):
            c.apply("dispatch", {"id": "a0", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                 "input_hash": "h", "budget": {}, "known_paths": {},
                                 "idempotency_key": "a0"})
        for index, (reason, expected) in enumerate(REAL_CHECKPOINTS):
            record = resume(c, f"a{index}", f"a{index + 1}", reason)
            check_eq(f"the retry names its cause: {expected}", record.get("retry_reason"), expected)
        state = c.state()
        check_eq("and the parent it resumed is superseded, as before",
                 state["dispatches"]["a0"]["status"], "superseded")
        check_not_in("a first attempt carries no reason at all",
                     "retry_reason", json.dumps(state["dispatches"]["a0"]))

        last = f"a{len(REAL_CHECKPOINTS)}"
        record = resume(c, last, "words", "anything at all", words="run it again, I want it")
        check_eq("a repeat a person asked for is theirs", record.get("retry_reason"), "person_word")
        check_eq("and their own words travel with it",
                 record.get("retry_words"), "run it again, I want it")

        record = resume(c, "words", "given", "window ran out of turn budget",
                        retry_reason="host_error:ENOTFOUND")
        check_eq("a caller that already knows the cause keeps it",
                 record.get("retry_reason"), "host_error:ENOTFOUND")
        record = resume(c, "given", "junk", "window ran out of turn budget",
                        retry_reason="because I said so")
        check_eq("an invented cause is replaced by the classified one",
                 record.get("retry_reason"), "turn_budget")
    finally:
        cleanup(root)


def a_relaunch_carries_the_reason_the_first_attempt_never_started():
    state = {"revision": 4, "dispatches": {
        "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                              "status": "never_started", "input_hash": "h", "scope": ["TC-1"],
                              "reason": "the host never launched the agent"}},
        "stages": {"S5": {"status": "pending"}}}
    packet = Controller._relaunch_packet(state, state["dispatches"]["S5-qa-automator-1"])
    check_eq("the relaunch packet says why the first attempt is being repeated",
             packet.get("retry_reason"), "subagent_silent")
    action = Controller._next_action_for_state(state)
    check_eq("and the action the orchestrator reads carries it too",
             action.get("retry_reason"), "subagent_silent")


def f05_is_a_split_by_cause_not_a_list_of_parent_ids():
    dispatches = [{"id": f"p{i}", "stage": "S5", "role": "qa-automator", "status": "superseded",
                   "reason": reason} for i, (reason, _) in enumerate(REAL_CHECKPOINTS)]
    dispatches += [{"id": f"r{i}", "stage": "S5", "role": "qa-automator", "status": "accepted",
                    "parent_retry": f"p{i}"} for i in range(len(REAL_CHECKPOINTS))]
    dispatches += [{"id": f"q{i}", "stage": "S4", "role": "qa-case-designer", "status": "accepted"}
                   for i in range(10)]
    value = MP.compute({"controller_known": True, "dispatches": dispatches})
    f05 = next(m for m in value if m["id"] == "F05")["value"]
    check_eq("the count and the denominator are both in the value",
             (f05["retries"], f05["dispatches"]), (8, 26))
    check_eq("the share is the share of all dispatches", round(f05["percent"]), 31)
    check_eq("and every repeat is counted under its cause", f05["by_reason"],
             {"awaiting_person": 2, "environment": 1, "turn_budget": 3,
              "factory_defect": 1, "checkpoint": 1})
    check_not_in("the list of parent ids is gone", "parents", json.dumps(f05))
    check_not_in("and so is the chain depth nobody could act on", "max_depth", json.dumps(f05))
    # A dispatch the controller already stamped is read from its own record, not re-classified.
    stamped = [{"id": "p", "status": "superseded", "reason": "anything"},
               {"id": "r", "parent_retry": "p", "retry_reason": "host_error:ECONNRESET"}]
    f05 = next(m for m in MP.compute({"controller_known": True, "dispatches": stamped})
               if m["id"] == "F05")["value"]
    check_eq("a stamped cause wins over classification",
             f05["by_reason"], {"host_error:ECONNRESET": 1})


def the_banner_names_the_cause_and_whose_it_is():
    fifteen_045 = {"retries": 10, "dispatches": 53, "percent": 100 * 10 / 53,
                   "by_reason": {"turn_budget": 4, "awaiting_person": 2, "checkpoint": 2,
                                 "environment": 1, "factory_defect": 1}}
    row = D.retry_signal(fifteen_045)
    check_in("10 of 53 dispatches fires the banner row", "the factory does work twice", row)
    check_in("naming the largest cause first", "turn_budget 4", row)
    check_in("with the count and the denominator", "10 of 53 dispatches", row)
    check_in("and the share as the tab shows it", "(19 %)", row)
    check_in("the cause belongs to the factory or the host", "finding about the factory", row)
    check_in("and never to the person", "none of it is the person's work", row)
    check_eq("a story with no repeats says nothing",
             D.retry_signal({"retries": 0, "dispatches": 40, "by_reason": {}}), "")
    check_eq("nor does one under both thresholds",
             D.retry_signal({"retries": 2, "dispatches": 40, "by_reason": {"turn_budget": 2}}), "")
    check("one cause three times is enough on its own",
          bool(D.retry_signal({"retries": 3, "dispatches": 90,
                               "by_reason": {"no_digest_at_exit": 3}})))


def the_factory_tab_draws_each_number_once():
    metrics = [{"id": "F05", "value": {"retries": 10, "dispatches": 53, "percent": 100 * 10 / 53,
                                       "by_reason": {"turn_budget": 4, "awaiting_person": 2}},
                "status": "available"},
               {"id": "F02", "value": {"rejected": 3, "accepted": 9, "rate": 25.0,
                                       "by_role": {"qa-automator": 3},
                                       "by_reason": {"no evidence": 3}}, "status": "available"},
               {"id": "F07", "value": [{"task": "TP1-15045", "issues": ["a", "b"]}],
                "status": "available"}]
    html = D.factory_health([], [], [], [], {"metrics": metrics})
    check_in("the retries card reads the count against the denominator",
             "10 of 53 dispatches (19 %)", html)
    check_in("with the split by cause under it", "turn_budget 4", html)
    check_in("rejected handoffs get a card only when there are any", "rejected handoffs", html)
    check_in("and the bookkeeping is one line that names its owner",
             "manifest bookkeeping: 2 issue(s) - owner: factory", html)
    check_in("pointing at the findings table", "href='#findings'", html)
    bare = D.factory_health([], [], [], [])
    check_not_in("a render with no projection invents no retries", "retries", bare)
    check_not_in("and no rejected handoffs either", "rejected handoffs", bare)

    now = "2026-09-24T00:00:00+00:00"
    snapshot = {"as_of": now, "metrics": MP.compute({
        "controller_known": True, "events_known": True, "bugs_known": True,
        "dispatches": [{"id": "p", "status": "incomplete", "reason": "turn budget exhausted",
                        "task": "T", "stage": "S5"},
                       {"id": "r", "parent_retry": "p", "status": "accepted"}],
        "events": [{"event_id": str(n), "type": "rejected", "role": "qa-automator",
                    "reason": "no evidence", "timestamp": now} for n in range(3)]
                  + [{"event_id": "g", "type": "gate_block", "timestamp": now}],
        "bugs": [{"id": "BUG-1", "severity": "major", "status": "Open", "area": "diff"}],
        "projection_issues": [{"task": "T", "issues": ["a stale case link"]}]})}
    factory = render_widgets(snapshot, "F", [])
    check_not_in("the Factory tab no longer repeats its cards as widgets",
                 "<h2>Quality and outcomes", factory)
    check_in("its trends and its catalogue stay", "<h2>Trends", factory)
    check_in("and every value is still inspectable", "All metric values, formulas", factory)
    testing = render_widgets(snapshot, "T", [])
    check_in("the Testing tab keeps its own widgets", "<h2>Quality and outcomes", testing)


def a_gate_block_is_counted_by_the_finding_it_names():
    notes = "block 1/1; broken artifacts: %d; first: s5_precheck.py: REAL exit 1 on the gate re-run"
    check_eq("the count of unrelated artifacts is not part of the finding",
             D.gate_block_finding(notes % 1), D.gate_block_finding(notes % 2))
    check_eq("a note without the marker is read whole",
             D.gate_block_finding("something else entirely"), "something else entirely")
    events = ([{"event": "gate_block", "notes": notes % 1}] * 7
              + [{"event": "gate_block", "notes": "block 1/1; broken artifacts: 1; first: "
                                                  "automation-manifest.json: required key 'tests' is missing"}]
              + [{"event": "gate_recheck_passed", "notes": "re-entry after a block"}] * 5)
    html = D.factory_health([], events, [], [])
    check_in("the card still reports every event", ">8</div><div class='lbl'>gate_block", html)
    check_in("but says how many findings they were", "unique 2", html)
    check_in("and that one of them was re-blocked", "7 of them are one finding re-blocked", html)


def main():
    controller_stamps_the_cause_of_every_retry()
    a_relaunch_carries_the_reason_the_first_attempt_never_started()
    f05_is_a_split_by_cause_not_a_list_of_parent_ids()
    the_banner_names_the_cause_and_whose_it_is()
    the_factory_tab_draws_each_number_once()
    a_gate_block_is_counted_by_the_finding_it_names()
    finish("test_retry_reason")


if __name__ == "__main__":
    main()
