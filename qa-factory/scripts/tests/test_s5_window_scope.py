#!/usr/bin/env python3
"""RN1-26 (t-1699 N3-1, t-1721): the scope of the S5 exit gate when the window has RETURNED.

`branch_accounting.s5_scope` read only the RUNNING automator dispatch; a repair round that is `returned_unaccepted` (a stop with no
bind receipt - the finisher's window) read as "no scope", and the gate judged EVERY case of the manifest (LOCAL-1 run 3). Now:
(a) the running dispatch; only when none, (b) the ONE returned one; else `UNKNOWN_SCOPE`, which `s5_check` raises as `Unreadable`
(`UNREADABLE:` and exit 3, the conductor's seam) - an unknown window is never a pass and never "every case".

Keys: K-N3-1a, K-N3-1b, K-N3-1c, K-N3-2, K-N3-2b, E14 (scope [] -> unknown), E15 (running beats returned).
The dispatch record below carries the keys of `S5-qa-automator-2` of the LOCAL-1 run-3 `state/controller.json` (values shortened).

Mutations (named, NOT run here; one killing file each - this one):
  m1  s5_scope: the returned dispatch is not read at all                      -> K-N3-1a
  m2  s5_scope: the returned dispatch is read BEFORE the running one          -> K-N3-1c
  m3  s5_scope: two returned dispatches take the first                        -> K-N3-2
  m4  s5_scope: an empty scope returns [] instead of UNKNOWN_SCOPE            -> E14
  m5  s5_check: UNKNOWN_SCOPE passed on to s5_problems (None = every case)    -> K-N3-2b
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import branch_accounting as BA  # noqa: E402
import test_branch_accounting as T  # noqa: E402  (its story builders; its checks run only under its own `main`)

BRANCHES = T.branches_table(["| BN-1 | R-1 | qualifier | description | the first branch |",
                             "| BN-2 | R-4 | qualifier | description | the second branch |",
                             "| BN-3 | R-11 | qualifier | description | the third branch |"])
CASES = ("TC-001", "TC-007", "TC-010")


def dispatch(did, scope, status, role="qa-automator", stage="S5") -> dict:
    """One record with the keys of the real `S5-qa-automator-2` (LOCAL-1 run 3), values shortened."""
    return {"id": did, "stage": stage, "role": role, "scope": scope, "input_hash": "8acf0700a6105cf9", "known_paths": {"task_root": "t"},
            "budget": {}, "config_sha256_at_start": "8f70548827367b29", "resolved_model": {"model": "inherit", "effort": "inherit"},
            "status": status, "request_binding": {}, "dispatched_seq": 57, "agent_id": "a2bc815b246668db5", "agent_bound_seq": 59,
            "no_progress_warning": False, "stage_complete": False, "evidence_refs": [{"path": "work/automation-manifest.json"}]}


def world(root, bound, records):
    """An S5 story: three cases (TC-001, TC-007, TC-010) each carrying one branch's Then 1; `bound` are the cases whose Then 1 is
    bound in the manifest; `records` the controller's dispatches (None: no state file)."""
    rows = [T.plan_row(f"TS-{n}", [f"BN-{n}"]) for n in (1, 2, 3)]
    cases = [(case, f"TS-{n}", f'branches: [{{"id": "BN-{n}", "then": 1}}]', T.THEN) for n, case in enumerate(CASES, 1)]
    task = _story(root, cases, rows, bound)
    state = task / "state" / "controller.json"
    state.unlink(missing_ok=True)
    if records is not None:
        state.write_text(json.dumps({"dispatches": {r["id"]: r for r in records}}), encoding="utf-8")
    return task


def _story(root, cases, rows, bound):
    task = T.stage_story(root, "S5", {"rows": rows}, cases, reg=T.register(branches=BRANCHES, obligations=None))
    (task / "work" / "automation-manifest.json").write_text(json.dumps(
        {"tests": [{"case": c} for c in bound], "then_bindings": [T.v_bind(c, 1) for c in bound], "unresolved": []}), encoding="utf-8")
    return task


def judged(task):
    """`(problems, notes)` of `s5_check`'s own path: the scope read by `s5_scope`, then `s5_problems`."""
    text = BA._read_register(task)
    return BA.s5_problems(task, text, BA.branch_state(task, text)["branches"], BA.s5_scope(task))


def main() -> None:
    root = temp_project("qa-s5-window-")
    try:
        returned = dispatch("S5-qa-automator-2", ["TC-001", "TC-007"], "returned_unaccepted")
        # K-N3-1a: the returned window is the scope; TC-010 (outside it, unbound) is a note, not a refusal
        task = world(root, ["TC-001", "TC-007"], [returned, dispatch("S5-qa-automator-1", ["TC-010"], "accepted")])
        check_eq("premise (today's reader): the running reader finds nothing for a returned dispatch",
                 __import__("s5_precheck").running_dispatch(task, "qa-automator", "S5"), None)
        check_eq("K-N3-1a s5_scope reads the returned window's cases", BA.s5_scope(task), ["TC-001", "TC-007"])
        problems, notes = judged(task)
        check("K-N3-1a no problem for the window, a TC-010 note", problems == [] and any("TC-010" in n for n in notes), str((problems, notes)))
        check_eq("K-N3-1a the exit gate is green", BA.s5_check(task)["blocks"], [])
        # K-N3-1b: TC-001 Then 1 unbound inside the window: one problem
        task = world(root, ["TC-007"], [returned])
        problems, notes = judged(task)
        check("K-N3-1b TC-001 Then 1 unbound: ONE problem, the case named", len(problems) == 1 and "TC-001" in problems[0], str(problems))
        check_eq("K-N3-1b the exit gate refuses with one block", len(BA.s5_check(task)["blocks"]), 1)
        # K-N3-1c / E15: a running and a returned dispatch: the running one's scope
        running = dispatch("S5-qa-automator-4", ["TC-010"], "running")
        task = world(root, ["TC-001", "TC-007"], [returned, running])
        check_eq("K-N3-1c E15 both live: the running window's scope", BA.s5_scope(task), ["TC-010"])
        problems, notes = judged(task)
        check("K-N3-1c TC-010 unbound in the running window: refused (never judged by the returned one)",
              len(problems) == 1 and "TC-010" in problems[0], str(problems))
        task = world(root, ["TC-010"], [returned, running])
        check_eq("K-N3-1c pair: the running window's case bound, the returned window's cases unbound: green", judged(task)[0], [])
        # K-N3-2: two returned dispatches -> UNKNOWN_SCOPE, UNREADABLE, exit 3
        second = dispatch("S5-qa-automator-3", ["TC-010"], "returned_unaccepted")
        task = world(root, ["TC-001", "TC-007"], [returned, second])
        check_eq("K-N3-2 two returned: UNKNOWN_SCOPE", BA.s5_scope(task), BA.UNKNOWN_SCOPE)
        result, verdict = T.detector(root)
        check_eq("K-N3-2 the exit gate: exit 3 and `UNREADABLE:` read by the contract", (result.returncode, bool(verdict["unreadable"])), (3, True))
        check_in("K-N3-2 the line names the scope and the count", "2 returned unaccepted", result.stdout)
        check_in("K-N3-2 the line is the detector's own third state", DV_PREFIX(), result.stdout)
        # K-N3-2b: no dispatch at all: the same; the premise line pins today's "every case" for an explicit caller
        task = world(root, ["TC-001", "TC-007"], None)
        check_eq("K-N3-2b no state file: UNKNOWN_SCOPE", BA.s5_scope(task), BA.UNKNOWN_SCOPE)
        result, verdict = T.detector(root)
        check_eq("K-N3-2b the exit gate: exit 3", result.returncode, 3)
        check_in("K-N3-2b ... naming none returned", "none returned unaccepted", result.stdout)
        text = BA._read_register(task)
        every = BA.s5_problems(task, text, BA.branch_state(task, text)["branches"], None)[0]
        check("premise (explicit caller, scope None) keeps meaning every case: TC-010 refused", len(every) == 1 and "TC-010" in every[0], str(every))
        task = world(root, ["TC-001", "TC-007"], [dispatch("S5-qa-automator-1", ["TC-010"], "accepted"), dispatch("S5-qa-code-critic-2", ["TC-001"], "returned_unaccepted", role="qa-code-critic")])
        check_eq("K-N3-2b only qa-automator S5 dispatches count: accepted and critic ones are no window", BA.s5_scope(task), BA.UNKNOWN_SCOPE)
        # E14: a dispatch found with an empty scope is unknown, never "no cases"
        for label, records in (("a returned dispatch with scope []", [dispatch("S5-qa-automator-2", [], "returned_unaccepted")]),
                               ("a running dispatch with scope []", [dispatch("S5-qa-automator-2", [], "running")])):
            task = world(root, ["TC-001"], records)
            check_eq(f"E14 {label}: UNKNOWN_SCOPE", BA.s5_scope(task), BA.UNKNOWN_SCOPE)
            result = T.detector(root)[0]
            check_eq(f"E14 {label}: the exit gate is exit 3", result.returncode, 3)
            check_in(f"E14 {label}: the line names the dispatch with the empty scope", "dispatch S5-qa-automator-2 has an empty scope", result.stdout)
        # a 0.7.4 state view (a list of records) is read as before
        task = world(root, ["TC-001", "TC-007"], None)
        (task / "state" / "controller.json").write_text(json.dumps({"dispatches": [returned]}), encoding="utf-8")
        check_eq("a list-shaped state view is read through the one reader", BA.s5_scope(task), ["TC-001", "TC-007"])
        # t-1748 F2: the twin detector `s5_precheck` takes the same window (running, else the ONE returned), not "every case"
        S5 = __import__("s5_precheck")
        task = world(root, list(CASES), [returned, dispatch("S5-qa-automator-1", ["TC-010"], "accepted")])
        manifest = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("F2 window_dispatch: the ONE returned dispatch is the window (running finds none)",
                 (S5.running_dispatch(task), S5.window_dispatch(task)), (None, "S5-qa-automator-2"))
        check_eq("F2 the scope is the returned window's cases, not the three the manifest names",
                 S5.scope_cases(task, manifest, S5.window_dispatch(task)), ["TC-001", "TC-007"])
        check_eq("F2 control: with no window the scope is every case of the manifest (the explicit-caller reading)",
                 S5.scope_cases(task, manifest, None), list(CASES))
        task = world(root, list(CASES), [returned, running])
        check_eq("F2 running beats returned", S5.window_dispatch(task), "S5-qa-automator-4")
        task = world(root, list(CASES), [returned, second])
        check_eq("F2 two returned: no window (None, as the running rule with two)", S5.window_dispatch(task), None)
        task = world(root, list(CASES), [dispatch("S5-qa-code-critic-2", ["TC-001"], "returned_unaccepted", role="qa-code-critic")])
        check_eq("F2 only qa-automator S5 dispatches count", S5.window_dispatch(task), None)
        # ... and the zero-argument entry `detector_main` hands `run` that window (the line that was `running_dispatch` alone)
        task = world(root, list(CASES), [returned])
        seen = []
        real_run, real_report = S5.run, S5.report
        S5.run = lambda task_root, dispatch_id: seen.append(dispatch_id) or {"ok": True}
        S5.report = lambda result: 0
        try:
            code = S5.detector_main(root)
        finally:
            S5.run, S5.report = real_run, real_report
        check_eq("F2 detector_main judges the returned window's dispatch, not every case", (code, seen), (0, ["S5-qa-automator-2"]))
        # t-1748 Q2: a state that cannot be read is named as that, not as "none returned"
        task = world(root, ["TC-001"], [returned])
        real = S5.window_dispatch
        S5.window_dispatch = lambda *a, **k: (_ for _ in ()).throw(OSError("state locked"))
        try:
            check_eq("Q2 s5_scope over an unreadable state: UNKNOWN_SCOPE", BA.s5_scope(task), BA.UNKNOWN_SCOPE)
            cause = ""
            try:
                BA.s5_check(task)
            except Exception as exc:
                cause = str(exc)
            check_in("Q2 the cause says the state could not be read", "the dispatch state could not be read (OSError: state locked)", cause)
        finally:
            S5.window_dispatch = real
        # no manifest yet: nothing to check stays exit 0 even with no window
        task = world(root, [], None)
        (task / "work" / "automation-manifest.json").unlink()
        result, verdict = T.detector(root)
        check_eq("no manifest yet and no window: still nothing to check (exit 0)", result.returncode, 0)
    finally:
        cleanup(root)
    finish("test_s5_window_scope")


def DV_PREFIX() -> str:
    import detector_verdict
    return detector_verdict.UNREADABLE_PREFIX


if __name__ == "__main__":
    main()
