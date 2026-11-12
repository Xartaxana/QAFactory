#!/usr/bin/env python3
"""RH1-10 (spec t-1421 part B, B-AC5, DC1-13): the ticket rework never asks the controller for a stage above S3.

DC1-13 said the ticket road could send `rework` for S6 with no cases. It does not: `take_ticket_answer` owes only S2 and S3
(`owed = [s for s in ("S2", "S3") ...]`), and `ticket_rework_step` sends `rework(stage, role, [], ...)` for those stages only, then
reopens gate A, which invalidates S5-S8 (`ticket_reopen_gate_a`), so S6 is redone by the normal flow. This file PINS that, with the
driver stubbed to the methods the two functions touch (`Driver.__new__`, no controller, no adapter).

  B-K15  `take_ticket_answer("new text")` records stages == ["S2", "S3"] when S2..S8 are completed; every `rework` call of the
         step carries a stage of {S2, S3} and `cases == []`; gate A is reopened after S3.
KILLS (one mutation, this file): `owed` widened to ("S2", "S3", "S6") in `take_ticket_answer` -> B-K15 fails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_run  # noqa: E402

ROLES = {"S2": "qa-requirements-analyst", "S3": "qa-test-strategist", "S4": "qa-case-designer", "S5": "qa-automator",
         "S6": "qa-runner", "S7": "qa-triager", "S8": "qa-reporter"}


def accepted(stage, did, **extra):
    return {"id": did, "stage": stage, "role": ROLES[stage], "status": "accepted", "scope": ["TC-1"], **extra}


def ticket_rework_stays_at_s2_and_s3():
    """B-K15, B-E11. KILLS: `owed` widened past S3 in `take_ticket_answer`; a `rework` call with cases; a stage above S3 reworked."""
    root = temp_dir("qa-rh110-ticket-")
    try:
        (root / "controller.json").write_text("{}", encoding="utf-8")
        dispatches = {f"d{n}": accepted(f"S{n}", f"d{n}") for n in range(2, 9)}
        controller = {"stages": {f"S{n}": {"status": "completed"} for n in range(0, 9)}, "dispatches": dispatches}
        calls, notes = [], {"reopened": 0, "recorded": []}

        d = story_run.Driver.__new__(story_run.Driver)
        d.task, d.task_root, d.state_dir, d.state = "QA-1", root, root, {}
        d.controller_state = lambda: controller
        d.save_state = lambda: None
        d.py_stdout = lambda *a, **k: (0, "", "")                       # the adapter adopts the new text
        d.ticket_record_words = lambda stage, how, words, what="ticket changed": notes["recorded"].append((stage, how))
        d.s3_prepare = lambda: None
        d.s3_ticket_completion = lambda: True
        d.s3_strategist_lines = lambda extra: []

        def rework(stage, role, cases, words, **kw):
            calls.append((stage, role, list(cases), kw.get("cause")))
            # the controller accepts the re-run: a ticket_changed dispatch of the stage, not in `before`
            did = f"re-{stage}-{len(calls)}"
            dispatches[did] = accepted(stage, did, repair_cause="ticket_changed")

        d.rework = rework
        d.ticket_reopen_gate_a = lambda pending: notes.__setitem__("reopened", notes["reopened"] + 1)

        d.take_ticket_answer("new text", "the ticket changed", "S0", "")
        pending = d.state.get("ticket_rework") or {}
        check_eq("B-K15: `take_ticket_answer('new text')` with S2..S8 completed owes S2 and S3 only", pending.get("stages"), ["S2", "S3"])
        check_eq("B-K15: ...and the words were recorded as the new text", notes["recorded"], [("S0", "new text")])
        for _ in range(6):                                              # a bounded loop: the step moves one stage per turn
            if not d.ticket_rework_step():
                break
            if "ticket_rework" not in d.state:
                break
        check_eq("B-K15: the step reworked S2 then S3, one stage per move", [c[0] for c in calls], ["S2", "S3"])
        check_eq("B-K15: ...every call with cases == [] (the S1-S3 rule: rows or nothing, never a case list)", [c[2] for c in calls], [[], []])
        check_eq("B-K15: ...every call with the ticket_changed cause", {c[3] for c in calls}, {"ticket_changed"})
        check_eq("B-K15: ...no stage above S3 was asked of the controller", all(c[0] in ("S2", "S3") for c in calls), True)
        check_eq("B-K15: gate A is reopened once, after S3, and the record is dropped", (notes["reopened"], "ticket_rework" in d.state), (1, False))
        # B-E11: an S1-only story owes nothing above S1 either: with S2 and S3 not completed no rework is owed and none is made
        d2 = story_run.Driver.__new__(story_run.Driver)
        d2.task, d2.task_root, d2.state_dir, d2.state = "QA-1", root, root, {}
        d2.controller_state = lambda: {"stages": {"S0": {"status": "completed"}, "S1": {"status": "completed"}}, "dispatches": {}}
        d2.save_state = lambda: None
        d2.py_stdout = lambda *a, **k: (0, "", "")
        d2.ticket_record_words = lambda *a, **k: None
        d2.take_ticket_answer("new text", "the ticket changed", "S0", "")
        check_eq("B-E11: nothing completed at S2/S3 -> no rework is owed (an empty list is never read as 'all')", "ticket_rework" in d2.state, False)
    finally:
        cleanup(root)


def ticket_rework_of_s3_targets_the_strategist():
    """t-2277 small-1 A: an accepted first-look runner dispatch of S3 that comes AFTER the strategist's never becomes the rework's role.
    KILLS: `roles[-1]` of S3 taken over every accepted S3 dispatch (the runner is reworked instead of the plan's author)."""
    root = temp_dir("qa-small1-ticket-")
    try:
        (root / "controller.json").write_text("{}", encoding="utf-8")
        dispatches = {"d2": accepted("S2", "d2"), "d3": accepted("S3", "d3"),
                      "S3-qa-runner-2": {"id": "S3-qa-runner-2", "stage": "S3", "role": "qa-runner", "status": "accepted",
                                         "request_binding": {"purpose": "first_look"}}}
        controller = {"stages": {f"S{n}": {"status": "completed"} for n in range(0, 4)}, "dispatches": dispatches}
        calls = []
        d = story_run.Driver.__new__(story_run.Driver)
        d.task, d.task_root, d.state_dir, d.state = "QA-1", root, root, {}
        d.controller_state = lambda: controller
        d.save_state = lambda: None
        d.py_stdout = lambda *a, **k: (0, "", "")
        d.ticket_record_words = lambda *a, **k: None
        d.s3_prepare = lambda: None
        d.s3_ticket_completion = lambda: True
        d.s3_strategist_lines = lambda extra: []

        def rework(stage, role, cases, words, **kw):
            calls.append((stage, role))
            did = f"re-{stage}-{len(calls)}"
            dispatches[did] = accepted(stage, did, repair_cause="ticket_changed")

        d.rework = rework
        d.ticket_reopen_gate_a = lambda pending: None
        d.take_ticket_answer("new text", "the ticket changed", "S0", "")
        for _ in range(6):
            if not d.ticket_rework_step() or "ticket_rework" not in d.state:
                break
        check_eq("small-1 A: S3 is reworked by the strategist, not by the first look accepted after it",
                 calls, [("S2", "qa-requirements-analyst"), ("S3", "qa-test-strategist")])
    finally:
        cleanup(root)


def main():
    ticket_rework_stays_at_s2_and_s3()
    ticket_rework_of_s3_targets_the_strategist()
    finish("test_ticket_rework_stages")


if __name__ == "__main__":
    main()
