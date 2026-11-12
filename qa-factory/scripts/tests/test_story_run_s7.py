#!/usr/bin/env python3
"""The driver's S7 by code (t-305 N1: keys K5, K6, K8, K9, K10 of the node spec; the Lead's edges (iv) and (v)).

What is proved here, in-process, with the roles recorded and never run (the rig of `test_story_run_s6.py`):
  * K5  `stage_S7` calls `s7_pretriage` before it decides (Q23): every failure a code row -> the S7 code-only receipt, S7 done,
        no role dispatched, the digest words; NEG: one more failure the analyst must judge -> the analyst is dispatched and
        `Failures to triage:` names ONLY that failure, with one line naming the rows code wrote;
  * K6  nothing failed: the close is byte-identical to the one before this change (the same three calls, the same words), and
        the pre-triage is not even called;
  * K8  `s7_repairs` reads the verdicts to repair from the S7 contract's `null_outcome.scope.params.repair_verdicts`, not
        from a literal pair; NEG: a declaration without FLAKY repairs no FLAKY row; one that cannot be read is a refusal;
  * RL8 (C1-5b2, t-698 §4.4) the S7 repair limit through the one seam: the take-back of a person's owed round the controller refused to
        START (t-760 row 3), the question once per (test, count) - two tests at the cap are two questions, a later turn at the same count asks
        nothing - and a closed story never enters S7 (edge 6); the question itself is pinned in test_story_run_repair_limit.py (RL8);
  * K9  `finalize_task.refresh` keeps a code row bound to a current failure and archives it when the failure is gone, as it
        does an analyst row; `analyst_preserved` is true only when an ANALYST row was kept;
  * K10 the S6 null close reduces first (`finalize_task`, then the receipt, then `stage_done`), and `failures_to_triage`
        accepts a `not_executed` run report only after an S6 code-only receipt (the controller's own record, read through
        the real controller here); NEG: without the receipt the refusal stands word for word.

THE INTEGRATOR'S HUNK. `NOT_EXECUTED` is a real word of `contract.TRIAGE_VERDICTS` now (t-350); `test_s7_pretriage.Verdict(True)`
patches nothing, and `Verdict(False)` patches the word OUT for the temporal scenario (the world before the hunk).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish  # noqa: E402
from story_run_common import awaits, driver_for, seed  # noqa: E402
from test_s7_pretriage import Verdict, check_row, report, result  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import s7_pretriage as S  # noqa: E402
import story_run  # noqa: E402

TASK = "QA-9"
NO_FAILURES = "no failures — nothing to triage"
# t-1991 U3b: the place lines (and "Places to settle: none in this run", Q4/AR-23) are appended by `run_role`, not by `stage_S7`: `told` is the driver's own words


def write(task_root: Path, rep=None, man=None, triage=None) -> None:
    work = task_root / "work"
    work.mkdir(parents=True, exist_ok=True)
    for name, doc in (("run-report.json", rep), ("automation-manifest.json", man), ("triage.json", triage)):
        if doc is not None:
            (work / name).write_text(json.dumps(doc), encoding="utf-8")


def rig(root, env, dispatches=None):
    """An in-process driver whose roles, code-only receipts and scripts are recorded: (driver, moves, launched)."""
    driver = driver_for(root, env, TASK)
    moves, launched = [], []
    driver.controller_state = lambda: {"dispatches": dict(dispatches or {})}
    driver.code_only = lambda stage, reason, evidence: moves.append(("code_only", stage, reason, list(evidence)))

    def py(script, *args, **kwargs):
        moves.append((script, [str(a) for a in args]))
        return 0, ""

    def run_role(stage, role, **kwargs):
        launched.append(dict(kwargs, stage=stage, role=role))
        return "", None

    driver.py, driver.run_role = py, run_role
    driver.role_lines = lambda stage, role: []
    # the repairs have their own tests (`s7_repairs_run`, `LimitRig`); here `stage_S7` is judged up to the point it hands over to them
    driver.s7_repairs = lambda: moves.append(("s7_repairs", []))
    return driver, moves, launched


def told(launched) -> list:
    return [line for entry in launched for line in entry.get("extra") or []]


def rows_of(task_root: Path) -> list:
    path = task_root / "work" / "triage.json"
    return json.loads(path.read_text(encoding="utf-8"))["triage"] if path.exists() else []


def quietly(call):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        value = call()
    return value, out.getvalue()


# ------------------------------------------------------------------------------------------------------ K5
def k5_stage_s7_asks_code_before_the_analyst() -> None:
    root, task_root, env = seed(TASK)
    try:
        # (a) every failure is a manual inconclusive with a limitation of the role's own: S7 closes by code
        rep = report(manual=[check_row("TC-9"), check_row("TC-8", limitations=["the capture could not read the page"])])
        write(task_root, rep, {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            _v, printed = quietly(driver.stage_S7)
        said = "every failure has a state the run already recorded: 2 written by code"
        check_eq("K5: no role is dispatched", launched, [])
        check_eq("K5: the S7 code-only receipt, the stage close and the skip, in that order, with the words",
                 moves, [("code_only", "S7", said, ["work/run-report.json", "work/triage.json"]),
                         ("stage_done.py", ["--task", TASK, "--stage", "S7", "--status", "done", "--digest", said, "--no-journal"]),
                         ("log_append.py", ["--event", "dispatch_skipped", "--task", TASK, "--reason",
                                            "S7: every failure has a state the run already recorded"])])
        check_eq("K5: the two code rows are in triage.json", [(r["instance_id"], r["verdict"], r["source"]) for r in rows_of(task_root)],
                 [("TC-9", S.VERDICT, "code"), ("TC-8", S.VERDICT, "code")])
        check_in("K5: the driver says what it wrote", "pre-triage: 2 manual check(s) written by code as NOT_EXECUTED: TC-9, TC-8", printed)
        # S7 entered again (a re-entry after the close): idempotent, the same close, no third row
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("K5 re-entry: the rows are not written twice", len(rows_of(task_root)), 2)
        check_eq("K5 re-entry: and S7 closes the same way (R9 answers every failure)", (launched, moves[0][2] if moves else None), ([], said))

        # (b) NEG: one more failure the analyst must judge: the analyst is dispatched, told about THAT failure only
        rep = report(manual=[check_row("TC-9"), check_row("TC-4", "fail")])
        write(task_root, rep, {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("K5 NEG: the analyst IS dispatched, S7 is not closed by code", ([(e["stage"], e["role"]) for e in launched],
                 [m for m in moves if m[0] == "code_only"]), ([("S7", "qa-failure-analyst")], []))
        lines = told(launched)
        check_eq("K5 NEG: `Failures to triage:` names only the failure code left to it", lines[0], "Failures to triage: manual TC-4")
        check_eq("K5 NEG: and one line names the row code wrote, and says the analyst keeps or replaces it",
                 lines[1], "Rows already written by code (keep them; you may replace one with your own): TC-9")
        check_eq("K5 NEG: the code row is in triage.json, the analyst's failure has none", [r["instance_id"] for r in rows_of(task_root)], ["TC-9"])

        # (c) the man1 shape: red results plus one code row - the red tests are the analyst's, named by their ids
        rep = report([result("t_a[json]"), result("t_ui", attempt_id="u1")], [check_row("TC-9")])
        write(task_root, rep, {"tests": [], "unresolved": [{"case": "TC-4", "reason": "blocked_by_env"}]}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            quietly(driver.stage_S7)
        lines = told(launched)
        check_eq("K5: red results stay with the analyst, named", lines[0], "Failures to triage: failed results t_a[json], t_ui")
        check_in("K5: and the kept-rows line names the code row", "TC-9", lines[1])

        # (d) no code row at all (a red result only): the old words, byte for byte, and no line about code rows
        write(task_root, report([result("t_a")]), {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("K5: with nothing written by code the brief is today's, the driver's own words for the whole run", told(launched),
                 [f"Failures to triage: {driver.failures_to_triage()}"])
        check_eq("K5: ...which for this report is the count", told(launched), ["Failures to triage: failed=1"])

        # (e) E20: an S7 dispatch in flight - code writes nothing, and says why
        write(task_root, report(manual=[check_row("TC-9")]), {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env, dispatches={"S7-qa-failure-analyst-1": {"stage": "S7", "status": "running"}})
        with Verdict(True):
            _v, printed = quietly(driver.stage_S7)
        check_eq("E20: a dispatch in flight: no row is written", rows_of(task_root), [])
        check_in("E20: ...and it is said", "a triage dispatch is in flight", printed)
        check_eq("E20: ...the analyst path is today's", told(launched), ["Failures to triage: manual TC-9"])

        # (f) the world before the integrator's hunk: nothing is written, the analyst triages as before, the refusal is printed
        write(task_root, report(manual=[check_row("TC-9")]), {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(False):
            _v, printed = quietly(driver.stage_S7)
        check_eq("(vi) before the hunk: no row, the analyst is asked, as before", (rows_of(task_root), told(launched)),
                 ([], ["Failures to triage: manual TC-9"]))
        check_in("(vi) ...and the refusal naming the constant is in the driver's log", "contract.TRIAGE_VERDICTS", printed)

        # (g) a pre-triage that cannot run is one printed line, and the analyst triages everything (P1)
        saved = S.pretriage
        try:
            def boom(_task):
                raise RuntimeError("disk")
            S.pretriage = boom
            driver, moves, launched = rig(root, env)
            _v, printed = quietly(driver.stage_S7)
        finally:
            S.pretriage = saved
        check_in("P1: the crash is said, once", "pre-triage could not run (RuntimeError: disk)", printed)
        check_eq("P1: ...and the analyst is asked as before", told(launched), ["Failures to triage: manual TC-9"])

        # (i) t-352 F1: a contradicts_requirement row for a case that is NOT failing keeps the analyst (CASE_DEFECT is
        # its alone) and the dispatch text keeps the reason; NEG: the same story without the row closes by code
        rep = report(manual=[check_row("TC-9")])
        write(task_root, rep, {"tests": [], "unresolved": [{"case": "TC-2", "reason": "contradicts_requirement", "detail": "R-17"}]},
              {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("F1: a contradicts row of a case that is not failing: the analyst IS dispatched, no code close",
                 ([(e["stage"], e["role"]) for e in launched], [m for m in moves if m[0] == "code_only"]),
                 ([("S7", "qa-failure-analyst")], []))
        check_in("F1: ...and its text names the contradicts_requirement rows", "contradicts_requirement rows", " ".join(told(launched)))
        check_eq("F1: ...the code row for TC-9 is written all the same", [r["instance_id"] for r in rows_of(task_root)], ["TC-9"])
        write(task_root, rep, {"tests": [], "unresolved": [{"case": "TC-2", "reason": "blocked_by_env"}]}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("F1 NEG: the same without the contradicts row closes by code, no analyst", (launched, [m[0] for m in moves]),
                 ([], ["code_only", "stage_done.py", "log_append.py"]))
        # ...and with a red result left over beside a contradicts row, the rebuilt brief keeps the reason
        write(task_root, report([result("t_a")], [check_row("TC-9")]),
              {"tests": [], "unresolved": [{"case": "TC-2", "reason": "contradicts_requirement"}]}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env)
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("F1: failures left over beside a contradicts row: the brief names both", told(launched)[0],
                 "Failures to triage: failed results t_a; contradicts_requirement rows")

        # (h) the analyst already answered (an accepted S7 dispatch): code is not asked at all, only the repairs run
        row = {"case": "TC-9", "verdict": "NOT_EXECUTED", "fix_result": "not_fixed"}
        write(task_root, report(manual=[check_row("TC-9")]), {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": [row]})
        driver, moves, launched = rig(root, env, dispatches={"S7-qa-failure-analyst-1": {"stage": "S7", "role": "qa-failure-analyst", "status": "accepted"}})
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("an accepted S7 dispatch over a FRESH triage: no pre-triage, no role, no close - S7 goes to its repairs",
                 (rows_of(task_root), launched, moves), ([row], [], [("s7_repairs", [])]))
        write(task_root, report(manual=[check_row("TC-9")]), {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": []})
        driver, moves, launched = rig(root, env, dispatches={"S7-qa-failure-analyst-1": {"stage": "S7", "role": "qa-failure-analyst", "status": "accepted"}})
        with Verdict(True):
            quietly(driver.stage_S7)
        check_eq("N1: an accepted analyst over a failure with NO row is not trusted: code answers what it can and S7 is not closed over the rest",
                 (moves[0][0], bool(launched) or moves[0][0] == "code_only"), ("code_only", True))
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K6
def k6_nothing_failed_is_byte_identical() -> None:
    root, task_root, env = seed(TASK)
    try:
        write(task_root, report(), {"tests": [], "unresolved": []})
        driver, moves, launched = rig(root, env)
        calls = []
        saved = S.pretriage
        try:
            S.pretriage = lambda task: calls.append(task) or saved(task)
            quietly(driver.stage_S7)
        finally:
            S.pretriage = saved
        check_eq("K6: the same three calls, with the same words, in the same order as before this change", moves,
                 [("code_only", "S7", NO_FAILURES, ["work/run-report.json"]),
                  ("stage_done.py", ["--task", TASK, "--stage", "S7", "--status", "done", "--digest", NO_FAILURES, "--no-journal"]),
                  ("log_append.py", ["--event", "dispatch_skipped", "--task", TASK, "--reason", "S7: no failures to triage"])])
        check_eq("K6: no role, and the pre-triage is not even called (nothing to decide)", (launched, calls), ([], []))
        check_eq("K6: and triage.json is not created", rows_of(task_root), [])
        # the all-null story (everything handed to a person): S6 closed by code, the run says not_executed
        write(task_root, {"execution_status": "not_executed", "current_results": [], "current_manual_checks": [], "current_totals": {}})
        driver, moves, launched = rig(root, env)
        saved = S.s6_closed_by_code
        try:
            S.s6_closed_by_code = lambda task_root_: True
            quietly(driver.stage_S7)
        finally:
            S.s6_closed_by_code = saved
        check_eq("(iv)/(v): the all-null story after an S6 code-only receipt: S7 closes with the same words, no role",
                 ([m[:3] for m in moves if m[0] == "code_only"], launched), ([("code_only", "S7", NO_FAILURES)], []))
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K8
def s7_repairs_run(rows, declared="real", digest="qa-automator S5 TC-1 · ok\nTC-1 · green · fixed\nwork/x.md"):
    """`s7_repairs` over triage rows, the repair rounds recorded: (the list of rework verdict lines, the printed text)."""
    import handoff
    root, task_root, env = seed(TASK)
    saved = handoff.null_outcomes
    try:
        driver = driver_for(root, env, TASK)
        write(task_root, triage={"triage": rows})
        done = []
        driver.budget_or_none = lambda stage, role, scope: {"counted": 0, "cap": 2}
        driver.rework = lambda stage, role, cases, reason, **kw: (done.append(reason) or (digest, {}))
        driver.py = lambda script, *args, **kwargs: (0, "")
        if declared != "real":
            handoff.null_outcomes = lambda contract: declared
        return quietly(driver.s7_repairs), done
    finally:
        handoff.null_outcomes = saved
        harness.cleanup(root)


def k8_s7_repairs_reads_the_declaration() -> None:
    rows = [{"case": "TC-1", "instance_id": "t_a", "verdict": "TEST_BUG"},
            {"case": "TC-2", "instance_id": "t_b", "verdict": "TEST_BUG:collection"},
            {"case": "TC-3", "instance_id": "t_c", "verdict": "FLAKY"},
            {"case": "TC-4", "instance_id": "t_d", "verdict": "APP_BUG"},
            {"case": "TC-5", "instance_id": "t_e", "verdict": "FLAKY", "fix_result": "fixed"},
            {"case": "TC-6", "instance_id": "t_f", "verdict": "NOT_EXECUTED"}]
    _out, done = s7_repairs_run(rows)
    check_eq("K8: the declared verdicts (TEST_BUG, TEST_BUG:collection, FLAKY) are repaired, once each; APP_BUG, a fixed FLAKY row and a "
             "NOT_EXECUTED row are not", [d.rsplit("verdict ", 1)[1] for d in done], ["TEST_BUG", "TEST_BUG:collection", "FLAKY"])
    # NEG: the declaration without FLAKY - a FLAKY row is not repaired
    no_flaky = {"scope": {"condition": "triage_has_no_repair", "params": {"repair_verdicts": ["TEST_BUG", "TEST_BUG:collection"],
                                                                         "listed_in": "not_for_repair"}}}
    _out, done = s7_repairs_run(rows, no_flaky)
    check_eq("K8 NEG: params without FLAKY: the FLAKY row is not repaired, the other two are", [d.rsplit("verdict ", 1)[1] for d in done],
             ["TEST_BUG", "TEST_BUG:collection"])
    only_flaky = {"scope": {"condition": "triage_has_no_repair", "params": {"repair_verdicts": ["flaky"], "listed_in": "not_for_repair"}}}
    _out, done = s7_repairs_run(rows, only_flaky)
    check_eq("K8: the handover check's rule (the word before the first colon, upper-cased) is the filter's: `flaky` repairs FLAKY only",
             [d.rsplit("verdict ", 1)[1] for d in done], ["FLAKY"])
    # a declaration that cannot be read is a refusal naming the key (never a guessed list)
    import story_run
    for label, declared in (("no declaration", {}), ("no params", {"scope": {}}), ("an empty verdict list",
                            {"scope": {"params": {"repair_verdicts": []}}}), ("a verdict list that is not a list",
                            {"scope": {"params": {"repair_verdicts": "TEST_BUG"}}})):
        try:
            s7_repairs_run(rows, declared)
            check(f"K8: {label} is refused", False, "no refusal")
        except story_run.Refusal as exc:
            check_in(f"K8: {label} is refused, naming the key", "null_outcome.scope.params.repair_verdicts", str(exc))
    # (no scan of story_run.py's source here: `test_driver_layers` L8 counts the tests that read the driver's text, and the
    # two NEG checks above already fail on a literal pair - they were red on that mutant)


# ------------------------------------------------------------------------------------------------------ K9
def k9_refresh_keeps_and_archives_code_rows() -> None:
    from test_s7_null_outcome import _Reduced
    import test_s7_null_outcome as T
    code = {"instance_id": "TC-9", "attempt_id": "a1", "case": "TC-9", "verdict": S.VERDICT, "source": S.SOURCE, "evidence": ["x"]}
    analyst = {"instance_id": "t_a", "attempt_id": "x1", "verdict": "APP_BUG", "evidence": "e"}

    def refreshed(rows, rep):
        task = harness.temp_dir("qa-s7-k9-")
        try:
            write(task, triage={"schema_version": 2, "triage": rows})
            with _Reduced(rep) as finalize:
                finalize.refresh(task)
            doc = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
            return doc, [r.get("instance_id") for r in T.archived_rows(task)]
        finally:
            harness.cleanup(task)

    doc, archived = refreshed([code, analyst], report([result("t_a")], [check_row("TC-9")]))
    check_eq("K9: a code row bound to a current failure is kept beside the analyst's", ([r["instance_id"] for r in doc["triage"]], archived),
             (["TC-9", "t_a"], []))
    check_eq("K9: an analyst row was kept, so the flag is true", doc["analyst_preserved"], True)
    doc, archived = refreshed([code], report(manual=[check_row("TC-9")]))
    check_eq("K9: only a code row kept: the row stays, and `analyst_preserved` is FALSE (it is code's own)",
             ([r["instance_id"] for r in doc["triage"]], doc["analyst_preserved"], archived), (["TC-9"], False, []))
    doc, archived = refreshed([code, analyst], report([result("t_a")], [check_row("TC-9", "pass", limitations=[])]))
    check_eq("K9 NEG: a code row for a failure that went green is archived as stale (E12); the analyst's stays",
             ([r["instance_id"] for r in doc["triage"]], archived, doc["analyst_preserved"]), (["t_a"], ["TC-9"], True))
    doc, archived = refreshed([code], report([result("t_a")]))
    check_eq("K9: no failure of the code row's is left: archived, nothing preserved", ([r["instance_id"] for r in doc["triage"]], archived,
             doc.get("analyst_preserved")), ([], ["TC-9"], False))
    doc, archived = refreshed([code, analyst], report())
    check_eq("K9: nothing failed at all: both archived as repaired (the old behaviour)", (doc["triage"], sorted(archived)), ([], ["TC-9", "t_a"]))


# ----------------------------------------------------------------------------------------------------- K10
def k10_the_s6_null_close_reduces_first() -> None:
    root, task_root, env = seed(TASK)
    try:
        driver, moves, _launched = rig(root, env)
        driver.stage_scope = lambda stage, kind="": {"scope": []}
        quietly(driver.stage_S6)
        names = [m[0] for m in moves]
        check_eq("K10: the S6 null close is finalize_task, then the receipt, then stage_done - in that order", names,
                 ["finalize_task.py", "code_only", "stage_done.py"])
        if names == ["finalize_task.py", "code_only", "stage_done.py"]:     # the order above is the key; the rest reads its moves
            check_eq("K10: finalize_task runs on the task root", Path(moves[0][1][0]).resolve(), task_root.resolve())
            check_in("K10: the receipt says what it is", "nothing to execute", moves[1][2])
            check_in("K10: and the close is the S6 stage_done", "--stage S6 --status done", " ".join(moves[2][1]))
        # a reduction that fails: nothing is closed over a report nobody could build
        driver, moves, _launched = rig(root, env)
        driver.stage_scope = lambda stage, kind="": {"scope": []}
        driver.py = lambda script, *args, **kwargs: (moves.append((script, [str(a) for a in args])) or (3, "reduce: corrupt block"))
        import story_run
        try:
            quietly(driver.stage_S6)
            check("K10: a failing reduction is refused", False, "no refusal")
        except story_run.Refusal as exc:
            check_in("K10: a failing reduction is refused, naming the exit and the line", "exit 3: reduce: corrupt block", str(exc))
        check_eq("K10: ...and no receipt and no close were written", [m[0] for m in moves], ["finalize_task.py"])

        # S7 reads the report of that close
        null_report = {"execution_status": "not_executed", "current_results": [], "current_manual_checks": [], "current_totals": {}}
        write(task_root, null_report)
        driver = driver_for(root, env, TASK)
        saved = S.s6_closed_by_code
        try:
            S.s6_closed_by_code = lambda task_root_: True
            check_eq("K10: not_executed after an S6 code-only receipt is read: no failure, so nothing to triage",
                     driver.failures_to_triage(), "")
            write(task_root, dict(null_report, current_manual_checks=[check_row("TC-9")], current_totals={"inconclusive": 1}))
            check_eq("K10: ...and a failure in it is named as ever", driver.failures_to_triage(), "manual TC-9")
            S.s6_closed_by_code = lambda task_root_: False
            write(task_root, null_report)
            import story_run
            try:
                driver.failures_to_triage()
                check("K10 NEG: not_executed with no S6 code-only receipt still refuses", False, "no refusal")
            except story_run.Refusal as exc:
                check_eq("K10 NEG: ...with today's text, word for word", str(exc),
                         "S7 entry: run-report.json execution_status is `not_executed` — nothing to triage yet; "
                         "the S6 halt that produced it stands")
            for status in ("env_blocked", "broken_run", "timeout", None):
                write(task_root, dict(null_report, execution_status=status))
                S.s6_closed_by_code = lambda task_root_: True
                try:
                    driver.failures_to_triage()
                    check(f"K10: execution_status {status!r} is still refused (only not_executed is read), receipt or not", False, "no refusal")
                except story_run.Refusal as exc:
                    check_in(f"K10: {status!r} is refused with the same sentence", f"execution_status is `{status}`", str(exc))
        finally:
            S.s6_closed_by_code = saved
    finally:
        harness.cleanup(root)
    # the receipt is the controller's own record, read through the REAL controller
    import test_fixes_13797 as F
    task = harness.temp_dir("qa-s7-k10-")
    try:
        c = F.s6_story(task)
        check_eq("K10 real controller: before any receipt S6 is not closed by code", S.s6_closed_by_code(task), False)
        F.runner(c, task, "S6-auto", "automation", ["TC-1"], False)
        check_eq("K10 real controller: an accepted runner dispatch is no code-only receipt", S.s6_closed_by_code(task), False)
        evidence = F.BASE.evidence_ref(task, "run-report.json", "{}")
        c.apply("code_only", {"id": "S6-code-only-1", "stage": "S6", "reason": "nothing to execute", "evidence_refs": [evidence],
                              "expected_revision": c.state().get("revision", 0), "idempotency_key": "code_only:S6:1"})
        check_eq("K10 real controller: after the S6 code-only receipt it is", S.s6_closed_by_code(task), True)
    finally:
        harness.cleanup(task)
    empty = harness.temp_dir("qa-s7-k10-empty-")
    try:
        check_eq("K10: a task root the controller cannot read says False (a doubt never opens S7)", S.s6_closed_by_code(empty / "nothing"), False)
    finally:
        harness.cleanup(empty)


# ------------------------------------------------------------------------------------------------------ RL8 (C1-5b2, t-698 §4.4)
PASSES = {"qa-automator": "round pass 3 for qa-automator on S5:aaaaaaaaaaaa", "qa-code-critic": "round pass 3 for qa-code-critic on S5:bbbbbbbbbbbb"}
BAD = "qa-automator S5 TC-1 · ok\nTC-1 · still_red · not fixed\nwork/x.md"
GREEN = "qa-automator S5 TC-1 · ok\nTC-1 · green · fixed\nwork/x.md"
LIFE = "S7-qa-failure-analyst-1"
ROW_1 = {"case": "TC-1", "instance_id": "inst_1", "test": "tests/test_a.py::test_one", "verdict": "TEST_BUG"}
ROW_2 = {"case": "TC-2", "instance_id": "inst_2", "test": "tests/test_b.py::test_two", "verdict": "TEST_BUG"}


class LimitRig:
    """A driver over `rows` at S7 with the controller's count in `self.n` (cap 2, passes for both roles), the scripts recorded in `self.py_log`,
    `rework` recorded in `self.rounds` (and counting when `self.counts`), and every question the seam raised in `self.asks` (the tests it named)."""

    def __init__(self, rows, counted=2, counts=True, by_case=None, green=()):
        self.root, self.task_root, env = seed(TASK)
        self.driver = d = driver_for(self.root, env, TASK)
        write(self.task_root, triage={"triage": list(rows)})
        self.n, self.counts, self.rounds, self.py_log, self.asks = counted, counts, [], [], []
        self.by_case, self.green = dict(by_case or {}), set(green)      # the count per case (else the shared `n`); the cases whose round ends green
        d.code_only = lambda stage, reason, evidence: self.py_log.append(("code_only", [stage, reason, list(evidence)]))
        d.s7_life = lambda: LIFE                                     # the analyst's accepted dispatch (the controller file of `seed` holds none)
        d.s7_refs = lambda row: ([row["instance_id"]], True)        # the ledger's refs are `test_ledger.py`'s and the end-to-end pin's
        d.s7_fresh = lambda: True
        d.repair_budget = lambda stage, role, scope: {"counted": self.by_case.get(scope[0], self.n) if scope else self.n, "cap": 2,
                                                      "by_cause": {}, "passes": dict(PASSES)}
        d.py = lambda script, *args, **kwargs: (self.py_log.append((script, list(args))) or (0, ""))
        d.rework = self.rework
        raised = d.repair_limit_raise
        d.repair_limit_raise = lambda ask: (self.asks.append(list(ask["tests"])), raised(ask))[1]

    def rework(self, stage, role, cases, reason, **kw):
        self.rounds.append((role, list(cases)))
        if cases and cases[0] in self.by_case:
            self.by_case[cases[0]] += int(self.counts)
        else:
            self.n += int(self.counts)
        return (GREEN if cases and cases[0] in self.green else BAD), {}

    def run(self):
        """(what `s7_repairs` raised or None, what it printed)."""
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.driver.s7_repairs()
        except Exception as raised:
            return raised, out.getvalue()
        return None, out.getvalue()

    def answer(self, words):
        d = self.driver
        ask = d.state["repair_ask"]
        d._answer = {"text": words, "rel": None}
        d.words_file = lambda text, name: self.task_root / "state" / "words" / "a.txt"
        d.answer_file = lambda: "state/words/a.txt"
        quietly(lambda: d._answer_repair_limit(words, "q", "S7", ask["dispatch"]))

    def owed(self, row=ROW_1, executed=False):
        """The person's `round` for `row` at the current count, recorded and not yet run (what `_answer_repair_limit` writes)."""
        d = self.driver
        slot = d.s7_slot(row["instance_id"], LIFE, self.n)
        d.state.setdefault("repair_limit_s7", {})[slot] = {"dispatch": slot, "token": "round", "cases": [row["case"]], "tests": [row["instance_id"]],
                                                           "life": LIFE, "ident": row["instance_id"], "key": "s7.repair_limit", "executed": executed}
        return d.state["repair_limit_s7"][slot]

    def done(self):
        harness.cleanup(self.root)


def rl8_refused_owed_round_is_taken_back() -> None:
    """t-760 row 3, for S7: the controller REFUSES to start the person's round (`ReworkRefused`, no role ran, `last_dispatch` unchanged):
    the mark `executed` that `s7_round` set before the dispatch is taken back - in memory AND on disk - so the person's round is still owed
    and the next entry runs it once; the refusal is raised as before. A refusal AFTER a role ran keeps the mark (the round is not run twice)."""
    import story_run as SR
    rig = LimitRig([ROW_1])
    try:
        owed, d = rig.owed(), rig.driver

        def refuse(stage, role, cases, reason, **kw):
            raise SR.ReworkRefused("the controller refused the rework: the window is busy")
        d.rework = refuse
        raised, _ = rig.run()
        check_eq("RL8 take-back: the refusal of the owed round is raised as before", type(raised).__name__, "ReworkRefused")
        saved = json.loads((d.state_dir / "driver-state.json").read_text(encoding="utf-8"))["repair_limit_s7"]
        check_eq("RL8 take-back: and the person's round is STILL owed (the mark is taken back, in memory and on disk)",
                 (owed["executed"], [e["executed"] for e in saved.values()]), (False, [False]))
        d.rework = rig.rework
        raised, _ = rig.run()
        check_eq("RL8 take-back: the next entry runs the round once, on that test's window, and marks it", (rig.rounds, owed["executed"]),
                 ([("qa-automator", ["TC-1"])], True))
        check_eq("RL8 take-back: then the new count is asked, not the old one (nothing is run twice)", (type(raised).__name__, rig.asks), ("Person", [["inst_1"]]))
    finally:
        rig.done()
    # control: a role RAN (last_dispatch moved) and the rework is refused afterwards - the mark stays
    rig = LimitRig([ROW_1])
    try:
        owed, d = rig.owed(), rig.driver

        def ran_then_refused(stage, role, cases, reason, **kw):
            d.last_dispatch = "S5-qa-automator-9"
            raise SR.ReworkRefused("the controller refused after the role ran")
        d.rework = ran_then_refused
        raised, _ = rig.run()
        check_eq("RL8 take-back control: a refusal AFTER the role ran raises and keeps the mark (the round is not run twice)",
                 (type(raised).__name__, owed["executed"]), ("ReworkRefused", True))
    finally:
        rig.done()


REORDER_ROW = {"case": "TC-1", "instance_id": "inst_r", "test": "tests/test_r.py::test_r", "verdict": "APP_BUG", "reorder": True,
               "blocked_thens": [{"then": 3, "blocking_check": "TC-9", "detail": "x"}]}
CRITIC_OK = "qa-code-critic S5 TC-1 · ok\nTC-1 · approved\nwork/x.md"


def r7_the_reorder_round() -> None:
    """K-R7-1, 2, 5, 7, 9 through the driver: the rows, the round (author, finish, critic), the outcome, the refusals."""
    import s7_reorder as RO
    import story_run as SR
    rows_rig = LimitRig([REORDER_ROW, dict(ROW_1, verdict="APP_BUG"), dict(REORDER_ROW, instance_id="inst_f", fix_result="fixed")])
    try:
        check_eq("K-R7-1/2: an APP_BUG row with `reorder` is a repair row; an APP_BUG row without it and a fixed one are not",
                 [r["instance_id"] for r in rows_rig.driver.s7_repair_rows()], ["inst_r"])
    finally:
        rows_rig.done()
    bad = LimitRig([dict(REORDER_ROW, blocked_thens=[])])
    try:
        try:
            bad.driver.s7_repair_rows()
            check("K-R7-1: a reorder row with no blocked_thens is refused", False, "no refusal")
        except SR.Refusal as exc:
            check_in("K-R7-1: ...naming the row and the missing field", "blocked_thens", str(exc))
    finally:
        bad.done()

    carried_result = {"status": "carried", "attempt": "a2", "case": "TC-1",
                      "critic": {"reason": "S7 reorder review: tests/test_r.py::test_r", "brief": ["Review only it"]}}
    FORM = ("findings:\n  - id: F1\n    problem: the moved assert reads the wrong value\n    cause: test_defect\n    blocking: true\n")

    def run_round(critics, finishes=("ok",), author=GREEN, form=None, carried=False):
        """`form`: the critic's typed form text (written as the handoff of the critic dispatch); `carried`: the round is already
        carried and unjudged (`carried_round` answers it) - `start` and the author must then never run."""
        rig = LimitRig([REORDER_ROW], counted=0)
        run_round.asks = rig.asks
        d, log, calls = rig.driver, [], {"c": 0, "f": 0}
        saved = (RO.start, RO.finish, RO.red_thens, RO.mark_fixed, RO.carried_round, RO.send_back)
        RO.start = lambda *a, **k: log.append("start") or {"status": "started", "snapshot": "work/s7-reorder/x.json"}
        RO.red_thens = lambda *a, **k: []
        RO.mark_fixed = lambda *a, **k: log.append("marked") or True
        RO.carried_round = lambda *a, **k: carried_result if carried else None
        RO.send_back = lambda *a, **k: log.append("sent_back") or True
        if form:
            write_form = rig.task_root / "work" / "handoffs" / "S5-qa-code-critic-1.yaml"
            write_form.parent.mkdir(parents=True, exist_ok=True)
            write_form.write_bytes(form.encode("utf-8"))

        def finish_(*a, **k):
            step = finishes[min(calls["f"], len(finishes) - 1)]
            calls["f"] += 1
            if step != "ok":
                raise RO.ReorderRefused("refused: " + step, step)
            return {"status": "carried", "attempt": "a2", "case": "TC-1",
                    "critic": {"reason": "S7 reorder review: tests/test_r.py::test_r", "brief": ["Review only it"]}}
        RO.finish = finish_

        def rework(stage, role, cases, reason, **kw):
            log.append((role, reason, kw.get("cause")))
            if role == "qa-automator":
                rig.n += 1
                return author, {}
            digest = critics[min(calls["c"], len(critics) - 1)]
            calls["c"] += 1
            d.last_dispatch = "S5-qa-code-critic-1"
            return digest, {}
        d.rework = rework
        try:
            raised, _out = rig.run()
            outcome = ((d.state.get("s7_rows") or {}).get(LIFE) or {}).get("inst_r", {}).get("outcome")
            return raised, outcome, log
        finally:
            RO.start, RO.finish, RO.red_thens, RO.mark_fixed, RO.carried_round, RO.send_back = saved
            rig.done()
    _raised, outcome, log = run_round([CRITIC_OK])
    check_eq("K-R7-7: author (S7 reorder) then critic (S7 reorder review), both test_defect; a green AUTHOR digest is not the outcome",
             [(r, why.split(":")[0], c) for r, why, c in (x for x in log if isinstance(x, tuple))],
             [("qa-automator", "S7 reorder", "test_defect"), ("qa-code-critic", "S7 reorder review", "test_defect")])
    check_eq("K-R7-7: an approving critic -> repaired, and the carried row is marked fixed", (outcome, "marked" in log), ("repaired", True))
    def authors(log) -> int:
        return len([x for x in log if isinstance(x, tuple) and x[0] == "qa-automator"])
    # a `concerns` review sends the window back whatever its rows say (`repair_route.SEND_BACK`, read through `route_of`): one more
    # round within the cap; at the cap (the author's round spent it) the loop meets the LIMIT QUESTION (`s7.repair_limit`), never a
    # silent `no_progress` (spec 5.7 p.4: another round or the limit question)
    for label, digest in (("concerns + a `rejected` row", "qa-code-critic S5 TC-1 · concerns\nTC-1 · rejected\nwork/x.md"),
                          ("concerns + an `approved_with_fixes` row", "qa-code-critic S5 TC-1 · concerns\nTC-1 · approved_with_fixes\nwork/x.md")):
        # the critic's form carries one typed finding (the form gate refuses a send-back without it); the untyped road is K4/K8a/K8b
        raised, outcome, log = run_round([digest], form=FORM)
        check_eq(f"K-R7-7: {label} is sent back (retry), not `no_progress`: two rounds spend the cap, then the limit question names the "
                 "test, and nothing is marked", (type(raised).__name__, outcome, "marked" in log, authors(log), run_round.asks),
                 ("Person", None, False, 2, [["inst_r"]]))
    _r, outcome, log = run_round(["qa-code-critic S5 TC-1 · ok\nTC-1 · rejected\nwork/x.md"])
    check_eq("K-R7-7: an approving verdict with a `rejected` row is not `repaired` (no_progress), nothing marked, no second round",
             (outcome, "marked" in log, authors(log)), ("no_progress", False, 1))
    _r, outcome, log = run_round(["qa-code-critic S5 TC-1 · concerns\nTC-1 · rejected\nwork/x.md", CRITIC_OK], form=FORM)
    check_eq("retry: a blocking `test_defect` finding of the critic's form sends the round back; the next review approves -> repaired, "
             "the judged round is closed (`send_back`) before the next one starts, two authors",
             (outcome, log.count("sent_back"), "marked" in log, authors(log)), ("repaired", 1, True, 2))
    raised, outcome, log = run_round([CRITIC_OK], carried=True)
    check_eq("F2: a round already carried and unjudged goes straight to its critic - no snapshot, no author - and is repaired",
             (outcome, "start" in log, authors(log), [x[0] for x in log if isinstance(x, tuple)]),
             ("repaired", False, 0, ["qa-code-critic"]))
    _r, outcome, _l = run_round(["qa-code-critic S5 TC-1 · halt\nwork/x.md"])
    check_eq("a halting critic -> no_progress", outcome, "no_progress")
    _r, outcome, _l = run_round(["qa-code-critic S5 TC-1 · concerns\nTC-1 · unverified\nwork/x.md"])
    check_eq("an unverified critic row -> no_progress", outcome, "no_progress")
    _r, outcome, log = run_round([CRITIC_OK], finishes=("green",))
    check_eq("K-R7-5: a green re-run (kind green) -> no_progress and no critic is dispatched", (outcome, [x for x in log if isinstance(x, tuple) and x[0] == "qa-code-critic"]),
             ("no_progress", []))
    _r, outcome, log = run_round([CRITIC_OK], finishes=("shape", "ok"))
    check_eq("another refusal kind (shape) -> one more round within the cap, then the approving critic repairs",
             (outcome, [x[0] for x in log if isinstance(x, tuple) and x[0] == "qa-automator"]),
             ("repaired", ["qa-automator", "qa-automator"]))
    rig = LimitRig([REORDER_ROW], counted=0)
    try:
        saved = (RO.start, RO.red_thens)
        RO.start, RO.red_thens = (lambda *a, **k: {"status": "started"}), (lambda *a, **k: [])

        def refuse(stage, role, cases, reason, **kw):
            raise SR.ReworkRefused("the controller refused: plan before windows")
        rig.driver.rework = refuse
        raised, _ = rig.run()
        check_eq("K-R7-9: ReworkRefused from the registration is raised, not repeated", type(raised).__name__, "ReworkRefused")
    finally:
        RO.start, RO.red_thens = saved
        rig.done()
    # F10: the person's `round` is taken back when `start` refuses BEFORE any role ran (no_test, unreadable): nothing was spent
    rig = LimitRig([REORDER_ROW], counted=2)
    try:
        owed, saved = rig.owed(REORDER_ROW), RO.start
        started = []

        def refuse_start(*a, **k):
            started.append(1)
            raise RO.ReorderRefused("the manifest names no such test", "no_test")
        RO.start = refuse_start
        raised, _ = rig.run()
        outcome = ((rig.driver.state.get("s7_rows") or {}).get(LIFE) or {}).get("inst_r", {}).get("outcome")
        check_eq("F10: `start` refused with the person's round owed: it ran (once), the round is STILL owed, nothing marked, no role ran",
                 (len(started), owed["executed"], outcome, rig.rounds, raised), (1, False, None, [], None))
    finally:
        RO.start = saved
        rig.done()
    # the literal `S7 fix` has ONE carrier (s5_precheck.S7_FIX_PREFIX): the writer and the reader both follow it
    import s5_precheck
    rig, prefix = LimitRig([ROW_1], counted=0), s5_precheck.S7_FIX_PREFIX
    seen, record = [], {}
    try:
        s5_precheck.S7_FIX_PREFIX = "S7 mend"

        def rework(stage, role, cases, reason, **kw):
            seen.append(reason)
            record.update(id="S5-qa-automator-9", reason=reason)
            return GREEN, {}
        rig.driver.rework = rework
        rig.run()
        check("S7 fix: the ordinary round registers its reason with the constant, not the literal",
              bool(seen) and seen[0].startswith("S7 mend:") and not seen[0].startswith("S7 fix"), str(seen))
        dispatch_record = s5_precheck.dispatch_record
        s5_precheck.dispatch_record = lambda task_root, dispatch_id: dict(record) if dispatch_id == record.get("id") else None
        try:
            check("S7 fix: and the reader follows the same constant (a record with this reason is an S7 fix round)",
                  s5_precheck.is_s7_fix_round(rig.task_root, "S5-qa-automator-9") is True)
            record["reason"] = "S7 fix: x"
            check("S7 fix: control - the old literal is no longer one while the constant says otherwise",
                  s5_precheck.is_s7_fix_round(rig.task_root, "S5-qa-automator-9") is False)
        finally:
            s5_precheck.dispatch_record = dispatch_record
    finally:
        s5_precheck.S7_FIX_PREFIX = prefix
        rig.done()


def r7_the_conductor_text() -> None:
    """K-R7-11: the Repair section of s7.md names the commands and words code reads (the brief-lines sentences are rows of design/role-rules.json)."""
    text = (PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s7.md").read_text(encoding="utf-8")
    repair = text.split("## Repair", 1)[1].split("## No repair", 1)[0]
    for key in ("s7_reorder.py\" start", "s7_reorder.py\" finish", "s7_reorder.py\" mark-fixed", "S7 reorder review", "plan before windows",
                "--words-file", "controller.py\" --operation rework", "story_step.py\" materialize"):
        check_in(f"K-R7-11: the Repair section carries {key!r}", key, repair)


def rl8_asked_once_per_test_and_count() -> None:
    """I1: one question per (test, count). Two tests at the cap are two questions; a rerun or a later loop turn at the SAME count asks nothing."""
    rig = LimitRig([ROW_1, ROW_2])
    try:
        first, _ = rig.run()
        check_eq("RL8 once: the first test at the cap is asked", (type(first).__name__, rig.asks), ("Person", [["inst_1"]]))
        again, _ = rig.run()
        check_eq("RL8 once: a rerun with no answer asks the SAME test again (nothing closes, nothing is skipped)", (type(again).__name__, rig.asks[-1]), ("Person", ["inst_1"]))
        rig.asks.clear()
        rig.answer("debt")
        second, _ = rig.run()
        check_eq("RL8 once: after the first answer the SECOND test is asked - two tests, two questions", (type(second).__name__, rig.asks), ("Person", [["inst_2"]]))
        rig.asks.clear()
        rig.answer("debt")
        third, _ = rig.run()
        check_eq("RL8 once: both answered - the next entry asks nothing, runs nothing, finalizes", (third, rig.asks, rig.rounds,
                 [s for s, _a in rig.py_log if s == "finalize_task.py"]), (None, [], [], ["finalize_task.py"]))
        fourth, _ = rig.run()
        check_eq("RL8 once: and a later entry at the same counts asks nothing either", (fourth, rig.asks), (None, []))
    finally:
        rig.done()
    # the same test, a later loop turn at the SAME count (the controller does not count the round): no second question, no second round
    rig = LimitRig([ROW_1], counts=False)
    try:
        rig.run()
        rig.answer("round")
        rig.asks.clear()
        raised, printed = rig.run()
        check_eq("RL8 once: a loop turn at the same count asks nothing and runs the one round only", (raised, rig.asks, rig.rounds), (None, [], [("qa-automator", ["TC-1"])]))
        check_in("RL8 once: and the stop is printed", "the person's answer `round` for this count is used", printed)
    finally:
        rig.done()


def rl8_closed_story_never_reaches_the_gate() -> None:
    """(A guard of the carrier, not evidence of C1-5b2's own code: the routing of `dispatch_action` predates it and no mutation of the S7 code
    can turn this red - t-823 F10.) Edge 6: `s7_repairs` runs only inside `stage_S7`, which the loop reaches by `prepare_stage`; a closed story is the action `closed`, which
    stops (or runs the retro) and never enters S7. Nothing is asked. POSITIVE control: `prepare_stage` S7 does reach `stage_S7`."""
    import story_run as SR
    rig = LimitRig([ROW_1])
    try:
        d, reached = rig.driver, []
        d.s7_repairs, d.stage_S7 = lambda: reached.append("s7_repairs"), lambda: reached.append("stage_S7")
        d.stage_S9 = lambda: reached.append("stage_S9")
        d.dispatch_action({"action": "prepare_stage", "stage": "S7"})
        check_eq("RL8 closed (control): the loop's own `prepare_stage` enters S7", reached, ["stage_S7"])
        reached.clear()
        try:
            d.dispatch_action({"action": "closed"})
            stopped = None
        except SR.Stop as exc:
            stopped = exc.code
        d.dispatch_action({"action": "closed", "retro_pending": True, "stage": "S9"})
        check_eq("RL8 closed: a closed story stops, or runs the retro only - S7 is not entered, nothing is asked", (stopped, reached, rig.asks, d.state.get("repair_ask")),
                 (SR.EXIT_DONE, ["stage_S9"], [], None))
    finally:
        rig.done()


# ------------------------------------------------------------------------------------------------------ the fix round t-829
# (t-698 §18.8, §20 N14, §21): S7 stays OPEN until its repairs end and is closed by code. Each pin names its key (T-L*, T-S*, E*, N*) in
# its label. The mutations that kill them are the hand-back's table (MU1-MU10); the killing file of every one is THIS file, but for MU7 and MU8
# and for the live worlds (T-L1, T-L3/T-S4, the P2 world, the re-triage bound), which live in test_story_run_s7_live.py (t-698 §22 FX-5).
def s7_lines(printed) -> list:
    return [line for line in printed.splitlines() if line.startswith("S7:")]


def s7_fresh_rig(report_rows, triage_rows):
    """A K5 rig with an ACCEPTED analyst dispatch and the real freshness check over `report_rows` / `triage_rows`."""
    root, task_root, env = seed(TASK)
    write(task_root, report(report_rows), {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": triage_rows})
    driver, moves, launched = rig(root, env, dispatches={"S7-qa-failure-analyst-1": {"stage": "S7", "role": "qa-failure-analyst", "status": "accepted"}})
    driver.s7_repairs = lambda: moves.append(("s7_repairs", []))
    return root, task_root, driver, moves, launched


def tl5_the_analyst_is_only_as_fresh_as_the_triage() -> None:
    """T-L5 (N1, §20) and §21 (iv): an accepted analyst whose triage does not bind EVERY current failure is not trusted - S7 is triaged again, never
    closed over the untriaged failure. The case: a person-word rework of S5 while S7 is open made the run report carry a failure the triage has no
    row for (the controller's stamp does not stale an OPEN S7, M-7). A failure with NO NAME is unbound too (iv). Positive control: all bound -> the
    repairs. MU10 (the freshness precondition removed) is killed here."""
    row = {"case": "TC-1", "instance_id": "inst_1", "verdict": "TEST_BUG", "evidence": "e"}
    for label, results, triage, expected in (
            ("every failure bound (control)", [result("inst_1")], [row], []),
            ("a failure no row answers", [result("inst_1"), result("inst_new")], [row], ["qa-failure-analyst"]),
            ("a failure with NO name (iv)", [result("inst_1"), {"status": "failed", "reason": "boom", "case": "TC-1"}], [row], ["qa-failure-analyst"])):
        root, task_root, driver, moves, launched = s7_fresh_rig(results, triage)
        try:
            with Verdict(True):
                _v, printed = quietly(driver.stage_S7)
            check_eq(f"T-L5: {label}: an accepted analyst is trusted only when every failure is bound; else the analyst is dispatched again",
                     [e["role"] for e in launched], expected)
            check_eq(f"T-L5: {label}: the repairs follow (after the new triage if there was one)", [m[0] for m in moves if m[0] == "s7_repairs"], ["s7_repairs"])
            check_eq(f"T-L5: {label}: and S7 is never closed by code in that entry", [m[0] for m in moves if m[0] in ("code_only", "stage_done.py")], [])
            if expected:
                check_in(f"T-L5: {label}: the re-triage is said", "the failure analyst triages again", printed)
        finally:
            harness.cleanup(root)
    # the same precondition at the CLOSE: the repairs ended, finalize ran, a failure has no row - nothing is recorded, S7 stays open for the next entry
    rig_ = LimitRig([ROW_1], counted=0, green=("TC-1",))
    try:
        d = rig_.driver
        d.s7_fresh = lambda: story_run.Driver.s7_fresh(d)
        write(rig_.task_root, report([result("inst_1"), result("inst_new")]))
        raised, printed = rig_.run()
        check_eq("T-L5 at the close: finalize ran, but no receipt and no stage_done were written over the untriaged failure",
                 (raised, [s for s, _a in rig_.py_log]), (None, ["finalize_task.py"]))
        check_in("T-L5 at the close: and it is said, S7 stays open for the analyst's next triage", "S7 stays open", printed)
    finally:
        rig_.done()
    # control: with every failure bound the same entry closes
    rig_ = LimitRig([ROW_1], counted=0, green=("TC-1",))
    try:
        d = rig_.driver
        d.s7_fresh = lambda: story_run.Driver.s7_fresh(d)
        write(rig_.task_root, report([result("inst_1")]))
        raised, printed = rig_.run()
        check_eq("T-L5 control: with every failure bound the close writes the receipt and the record", (raised, [s for s, _a in rig_.py_log]),
                 (None, ["finalize_task.py", "code_only", "stage_done.py"]))
    finally:
        rig_.done()


def ts1_life_keeps_two_triages_apart() -> None:
    """T-S1: an answer of an OLD life (an earlier analyst dispatch) at the same count never silences the NEW life's question. The slot carries the life
    (a direct check) and an old record stays beside the new one. MU3 (life dropped from the slot) is killed here."""
    rig_ = LimitRig([ROW_1])
    try:
        d, old = rig_.driver, "S7-qa-failure-analyst-0"
        check("T-S1: the slot of one test at one count differs by life", d.s7_slot("inst_1", old, 2) != d.s7_slot("inst_1", LIFE, 2))
        record = {"cases": ["TC-1"], "tests": ["inst_1"], "life": old, "ident": "inst_1", "key": "s7.repair_limit", "executed": True}
        d.state["repair_limit_s7"] = {d.s7_slot("inst_1", old, 2): dict(record, dispatch=d.s7_slot("inst_1", old, 2), token="round"),
                                      d.s7_slot("inst_1", old, 3): dict(record, dispatch=d.s7_slot("inst_1", old, 3), token="debt")}
        raised, _ = rig_.run()
        check_eq("T-S1: the new life is asked at count 2 although the old life answered `round` there and `debt` for the test",
                 (type(raised).__name__, rig_.asks, rig_.rounds), ("Person", [["inst_1"]], []))
        rig_.answer("debt")
        check_eq("T-S1: the new answer is a THIRD record; the old life's two stay as they were", sorted(r["life"] for r in d.state["repair_limit_s7"].values()),
                 sorted([old, old, LIFE]))
    finally:
        rig_.done()


def ts2_debt_is_final_for_its_test() -> None:
    """T-S2: A answers `debt`, B answers `round`; B's round moves the shared count to 3 and A is not asked again. The record itself is final: `s7_limit`
    answers a `debt` of this life BEFORE it reads the count (a direct call at count 3). MU4 (debt not final) is killed by the direct call."""
    rig_ = LimitRig([ROW_1, ROW_2])
    try:
        d = rig_.driver
        rig_.run()
        rig_.answer("debt")
        rig_.run()
        rig_.answer("round")
        rig_.asks.clear()
        raised, _ = rig_.run()
        check_eq("T-S2: after A `debt` and B `round` the count is 3; only B is asked (at 3), A never", (type(raised).__name__, rig_.asks, rig_.n),
                 ("Person", [["inst_2"]], 3))
        found = None
        try:
            found = d.s7_limit("t", "inst_1", ["inst_1"], True, "TC-1", {"counted": 3, "cap": 2, "by_cause": {}, "passes": dict(PASSES)}, LIFE)
        except Exception as exc:
            found = exc
        check_eq("T-S2: `s7_limit` for A at count 3 returns A's recorded `debt` (no question, no count lookup)", (isinstance(found, dict) and found.get("token")), "debt")
    finally:
        rig_.done()


def ts3_a_repaired_row_is_not_rounded_again() -> None:
    """T-S3: row A is repaired green BEFORE the question at row B; the re-entry after B's `round` does not give A another round. MU5 (outcomes ignored)
    is killed here: A would be repaired again (its count 1 is below the cap)."""
    rig_ = LimitRig([ROW_1, ROW_2], by_case={"TC-1": 0, "TC-2": 2}, green=("TC-1",))
    try:
        raised, _ = rig_.run()
        check_eq("T-S3: A is repaired (one round, green), then B at the cap is asked", (type(raised).__name__, rig_.rounds, rig_.asks),
                 ("Person", [("qa-automator", ["TC-1"])], [["inst_2"]]))
        rig_.answer("round")
        raised, _ = rig_.run()
        check_eq("T-S3: the re-entry runs B's round only - A is not rounded again", [r[1] for r in rig_.rounds], [["TC-1"], ["TC-2"]])
        check_eq("T-S3: the outcomes are kept per life and test", {k: v.get("outcome") for k, v in rig_.driver.state["s7_rows"][LIFE].items()}["inst_1"], "repaired")
    finally:
        rig_.done()


def ts5_edges_of_the_close() -> None:
    """T-S5: E6 (all rows ended at entry -> close at once, in the order finalize, receipt, record), E7 (the controller holds S7 completed -> no finalize,
    no second receipt), E8 (an unreadable declaration at the analyst's finish keeps S7 open; the entry refuses), E11 (the reason: 300 whole, 301 cut)."""
    import handoff
    rig_ = LimitRig([ROW_1, ROW_2])
    try:
        rig_.driver.state["s7_rows"] = {LIFE: {"inst_1": {"outcome": "repaired"}, "inst_2": {"outcome": "no_progress"}}}
        raised, printed = rig_.run()
        names = [s for s, _a in rig_.py_log]
        check_eq("T-S5 E6: every row already ended at entry: no round, no question, the close at once in the order finalize -> receipt -> record",
                 (raised, rig_.rounds, rig_.asks, names), (None, [], [], ["finalize_task.py", "code_only", "stage_done.py"]))
        receipt = next((a for s, a in rig_.py_log if s == "code_only"), ["", "", []])      # a mutant that writes none is a FAIL line, not a crash
        check_eq("T-S5 E6: the receipt names the endings in words and its evidence", (receipt[0], "1 repaired; 0 left failing by your answer; 1 stopped because a round changed nothing" in receipt[1],
                                                                                   receipt[2]), ("S7", True, ["work/triage.json", "work/run-report.json"]))
        done_args = next((a for s, a in rig_.py_log if s == "stage_done.py"), [])
        check_in("T-S5 E6: the record carries the repairs' counts in the digest", "repairs: fixed=1 not_fixed=0 stopped=1", " ".join(done_args))
    finally:
        rig_.done()
    rig_ = LimitRig([ROW_1])
    try:
        rig_.driver.controller_state = lambda: {"stages": {"S7": {"status": "completed"}}, "dispatches": {}}
        wrote = rig_.driver.close_by_code("S7", "r", ["work/triage.json"], finalize=True)
        check_eq("T-S5 E7: the controller holds S7 completed: no finalize, no second receipt, no record", (wrote, rig_.py_log), (True, []))
    finally:
        rig_.done()
    rig_ = LimitRig([ROW_1])
    saved = handoff.null_outcomes
    try:
        handoff.null_outcomes = lambda contract: {}
        kept = rig_.driver.s7_open_work()
        check_eq("T-S5 E8: a declaration that cannot be read at the analyst's finish KEEPS S7 open (OpenWork, never None)",
                 (type(kept).__name__, awaits(kept)), ("OpenWork", "repairs_pending"))
        raised, _ = rig_.run()
        check_in("T-S5 E8: ...and the entry refuses naming the key", "null_outcome.scope.params.repair_verdicts", str(raised))
    finally:
        handoff.null_outcomes = saved
        rig_.done()
    prefix = "the failure analyst found 1 failing test(s) whose fault is the test itself; S7 was kept open for their repairs: "
    for size in (300, 301):
        rig_ = LimitRig([{"case": "TC-1", "test": "t" * (size - len(prefix)), "verdict": "TEST_BUG"}])
        try:
            reason = rig_.driver.s7_open_work().reason
            if size == 300:
                check_eq("T-S5 E11: a reason of exactly 300 characters is shown whole", (len(reason), reason.startswith(prefix), "…" in reason), (300, True, False))
            else:
                check_eq("T-S5 E11: 301 characters are cut to 300 at most, with the ellipsis and the path of the whole list",
                         (len(reason) <= 300, "… [list: work/triage.json]" in reason, reason.endswith("work/triage.json]")), (True, True, True))
            check_not_in(f"T-S5 E11 ({size}): the reason is timeless (no 'is kept' present tense)", "S7 is kept", reason)
        finally:
            rig_.done()


def e9_the_s7_rule_stands_before_rework_of() -> None:
    """E9 (MU9): the analyst's own REWORK (`rework_of`, the person's words) is judged by the S7 rule first: rows -> OpenWork, none -> None. The
    `rework_of` rule answers False, which would let the controller refuse the finish or close S7 over the rows."""
    rig_ = LimitRig([ROW_1])
    try:
        complete = rig_.driver.completion_for("S7", "qa-failure-analyst", {"rework_of": "S7-qa-failure-analyst-1"})
        def ruled(rule):      # a mutant that answers a bool (the `rework_of` rule) is a FAIL line here, not a crash
            return rule("digest") if callable(rule) else rule
        check_eq("E9: with a repair row a reworked analyst's finish is OpenWork (S7 stays open)", type(ruled(complete)).__name__, "OpenWork")
        write(rig_.task_root, triage={"triage": [{"case": "TC-1", "instance_id": "inst_1", "verdict": "APP_BUG"}]})
        # X7-6: with nothing to repair the finish is not "today's road" (None) any more: it awaits the consumer (the scribe), never closes S7
        check_eq("E9: with nothing to repair the same call awaits the scribe's acceptance (X7-6)",
                 (type(ruled(complete)).__name__, awaits(ruled(complete))), ("OpenWork", "stage_awaits_acceptance"))
        check_eq("E9 control: another stage's rework still answers False", rig_.driver.completion_for("S5", "qa-automator", {"rework_of": "x"}), False)
    finally:
        rig_.done()


def e12_a_round_finished_outside_the_loop() -> None:
    """E12: the round's dispatch id was recorded the moment the controller returned it (N9); when it was accepted and its saved digest is green, the
    next entry marks the test repaired and dispatches nothing. A saved digest that is not green does not."""
    for label, saved, expected in (("green", GREEN, ([], "repaired")), ("not green", BAD, ([("qa-automator", ["TC-1"])], "no_progress"))):
        rig_ = LimitRig([ROW_1], counted=0, counts=False)
        try:
            d = rig_.driver
            d.state["s7_rows"] = {LIFE: {"inst_1": {"round": "S5-qa-automator-9"}}}
            d.controller_state = lambda: {"dispatches": {"S5-qa-automator-9": {"status": "accepted"}}}
            runs = d.state_dir / "driver-runs"
            runs.mkdir(parents=True, exist_ok=True)
            (runs / "S5-qa-automator-9.done.json").write_text(json.dumps({"result": saved}), encoding="utf-8")
            raised, printed = rig_.run()
            check_eq(f"E12: a round finished outside the loop with a {label} digest", (raised, rig_.rounds, d.state["s7_rows"][LIFE]["inst_1"]["outcome"]),
                     (None,) + expected)
        finally:
            rig_.done()


def n2_the_persons_decision_outranks_the_code() -> None:
    """N2 both ways: the person's recorded `close` -> no round, ONE printed line, no close by code (the stage is left to the person); their `open_work`
    -> the rounds run, `close_by_code` is NOT called, ONE printed line, and the end of the life is the closed question (`fx2_...` below)."""
    for kind in ("close", "open_work"):
        rig_ = LimitRig([ROW_1], counted=0, green=("TC-1",))
        try:
            decisions = rig_.task_root / "state" / "decisions"
            decisions.mkdir(parents=True, exist_ok=True)
            (decisions / f"{LIFE}.json").write_text(json.dumps({"dispatch": LIFE, "stage": "S7", kind: {"words_ref": "state/words/w.txt", "at": "t"}}), encoding="utf-8")
            raised, printed = rig_.run()
            lines = s7_lines(printed)
            close = kind == "close"
            check_eq(f"N2 `{kind}`: " + ("no round" if close else "the round runs (green)") + ", nothing is closed by code or finalized",
                     (type(raised).__name__ if raised else None, rig_.rounds, [s for s, _a in rig_.py_log if s in ("finalize_task.py", "code_only", "stage_done.py")]),
                     ("Person" if not close else None, [] if close else [("qa-automator", ["TC-1"])], []))
            check_eq(f"N2 `{kind}`: exactly one S7 line says why", (len(lines), "decision" in " ".join(lines)), (1, True))
        finally:
            rig_.done()


def open_rig(words="keep it open: the export check is still to be run by hand", ended=False):
    """A `LimitRig` over ROW_1 (below the cap, the round ends green) whose analyst dispatch holds the person's recorded `open_work`
    (`decide --open` kept the words in `state/words/`); `ended`: the row's repairs have ended already (the decision came after them)."""
    rig_ = LimitRig([ROW_1], counted=0, green=("TC-1",))
    d = rig_.driver
    decisions = rig_.task_root / "state" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    kept = rig_.task_root / "state" / "words"
    kept.mkdir(parents=True, exist_ok=True)
    (kept / "open.txt").write_text(words, encoding="utf-8")
    (decisions / f"{LIFE}.json").write_text(json.dumps({"dispatch": LIFE, "stage": "S7", "open_work": {"words_ref": "state/words/open.txt", "unresolved": [], "at": "t"}}),
                                            encoding="utf-8")
    if ended:
        d.state["s7_rows"] = {LIFE: {"inst_1": {"outcome": "repaired"}}}
    d.answer_file = lambda: "state/words/a.txt"
    return rig_


def closed_by_code(rig_) -> list:
    return [s for s, _a in rig_.py_log if s in ("finalize_task.py", "code_only", "stage_done.py")]


def fx2_the_end_of_an_open_work_life_asks_one_closed_question() -> None:
    """t-698 §22 FX-2 (decided (a)): when every row of an `open_work` life has ended the driver asks ONE closed question that names the person's
    open decision (their own words, quoted) and offers `close` / `stop`; `decide --close` is not the door; no paid call, no round, no close by
    code until `close`. A rerun with the question unanswered asks it again (no rounds, no close); `close` -> the next entry closes S7 by code
    (finalize, receipt, stage_done); `stop` is held and the question comes back; an unread word goes to the seam with THIS question shown again.
    Edge (E6 shape): the decision recorded AFTER the rows ended is asked on the next entry, with no round dispatched."""
    rig_ = open_rig()
    try:
        d = rig_.driver
        raised, printed = rig_.run()
        text = getattr(raised, "text", "")
        check_eq("FX-2: the rounds ran (green), then the Person is raised: kind `open_work`, stage S7, the analyst's life as the dispatch",
                 (rig_.rounds, getattr(raised, "kind", None), getattr(raised, "stage", None), getattr(raised, "dispatch", None)),
                 ([("qa-automator", ["TC-1"])], "open_work", "S7", LIFE))
        check_in("FX-2: the question names the person's open decision, in their own words", "the export check is still to be run by hand", text)
        check_in("FX-2: ...and says what the factory did (one repaired)", "1 repaired", text)
        check_eq("FX-2: the answers are `close` and `stop`, each with its price lines (the factory / you / the story)",
                 (sorted(getattr(raised, "priced", ())), text.count("the factory:"), text.count("you:")), (["close", "stop"], 2, 2))
        check_in("FX-2: the `close` price line is the data's (this answer only)", "this answer only", text)
        check_not_in("FX-2: the question names no door that refuses (`decide --close`) and no id", "decide --", text)
        check_eq("FX-2: nothing is closed by code or finalized before the person's `close`", closed_by_code(rig_), [])
        check_eq("FX-2: the question is on record for this life, unanswered", (d.state.get("s7_open_work") or {}).get(LIFE, {}).get("token"), "")
        # the rerun with the question unanswered asks again: no round, no close
        raised, printed = rig_.run()
        check_eq("FX-2: an entry with the question unanswered asks AGAIN - no second round, no close",
                 (getattr(raised, "kind", None), len(rig_.rounds), closed_by_code(rig_)), ("open_work", 1, []))
        # `stop` is held and comes back
        try:
            quietly(lambda: d._answer_open_work("stop", "q", "S7", LIFE))
            held = None
        except story_run.Person as person:
            held = person
        check("FX-2: `stop` is held (the question comes back changed) and records no close",
              held is not None and "You said to stop" in held.text and not d.s7_open_answer(LIFE))
        raised, printed = rig_.run()
        check_eq("FX-2: after `stop` an entry asks again", getattr(raised, "kind", None), "open_work")
        # an unread word goes to the seam, with this question as the one shown again
        seen = []
        d.unread = lambda kind, stage, dispatch, qtext, **kw: seen.append((kind, stage, dispatch, kw))
        quietly(lambda: d._answer_open_work("maybe later", "q", "S7", LIFE))
        again = seen[0][3]["again"]("not read") if seen else None
        check_eq("FX-2: an unread word is handed to the seam with the doors `close` / `stop` and nothing recorded",
                 ([(k, st, di, kw.get("doors")) for k, st, di, kw in seen], d.s7_open_answer(LIFE)), ([("open_work", "S7", LIFE, ("close", "stop"))], False))
        check("FX-2: ...and the question shown again is THIS one, with the unread lead above it",
              getattr(again, "kind", None) == "open_work" and getattr(again, "text", "").startswith("not read") and "export check" in getattr(again, "text", ""))
        # `close`: recorded, and the NEXT entry closes S7 by code
        quietly(lambda: d._answer_open_work("close", "q", "S7", LIFE))
        check_eq("FX-2: `close` is recorded for this life", (d.s7_open_answer(LIFE), (d.state["s7_open_work"][LIFE]).get("words_file")), (True, "state/words/a.txt"))
        raised, printed = rig_.run()
        check_eq("FX-2: after `close` the entry closes S7 by code - finalize, the receipt, stage_done, in that order - and runs no second round",
                 (raised, closed_by_code(rig_), len(rig_.rounds)), (None, ["finalize_task.py", "code_only", "stage_done.py"], 1))
    finally:
        rig_.done()
    rig_ = open_rig(ended=True)
    try:
        raised, printed = rig_.run()
        check_eq("FX-2 edge (E6 shape): the decision recorded after the rows ended is asked on the next entry, with no round dispatched",
                 (getattr(raised, "kind", None), rig_.rounds, closed_by_code(rig_)), ("open_work", [], []))
    finally:
        rig_.done()
    rig_ = open_rig(words="   ")
    try:
        raised, printed = rig_.run()
        check("FX-2 edge: a decision whose words file is blank still asks, without a quote",
              getattr(raised, "kind", None) == "open_work" and "your words" not in getattr(raised, "text", ""))
    finally:
        rig_.done()


def n3_the_relaunch_fallback_passes_the_analysts_completion() -> None:
    """N3: `_act_relaunch` with no packet starts the role with `complete=completion_for(stage, role, {})`: for the S7 analyst that is the callable
    that keeps S7 open - not None (the controller's own default would close it)."""
    rig_ = LimitRig([ROW_1])
    try:
        d, seen = rig_.driver, []
        d.run_role = lambda stage, role, **kw: seen.append((stage, role, kw.get("complete")))
        d.role_lines = lambda stage, role: []
        d._act_relaunch({"stage": "S7", "role": "qa-failure-analyst"})
        check_eq("N3: the relaunch fallback runs the S7 analyst", [(s, r) for s, r, _c in seen], [("S7", "qa-failure-analyst")])
        check("N3: ... with the S7 completion rule (a callable), not the default", len(seen) == 1 and callable(seen[0][2]))
        check_eq("N3: ... which keeps S7 open while a repair row remains", type(seen[0][2]("digest")).__name__ if seen and callable(seen[0][2]) else None, "OpenWork")
    finally:
        rig_.done()


def n7_a_refused_stage_done_retries_alone() -> None:
    """N7: `stage_done` refused after a SUCCESSFUL `code_only` is a Refusal whose retry runs `stage_done` alone - one finalize, one receipt."""
    import story_run as SR
    rig_ = LimitRig([ROW_1])
    try:
        d, calls = rig_.driver, []
        d.state["s7_rows"] = {LIFE: {"inst_1": {"outcome": "repaired"}}}

        def py(script, *args, check=False, expect=""):      # C1-7c Q-3: the real `py`'s signature; a G site's `expect` is forwarded
            calls.append(script)
            rig_.py_log.append((script, [str(a) for a in args]))
            refused = script == "stage_done.py" and calls.count("stage_done.py") == 1
            if refused and check:
                retry = lambda: py(script, *args, check=True, expect=expect)      # noqa: E731
                raise (SR.gate_refusal(script, 1, "stage_done refused S7", expect, retry) if expect
                       else SR.Refusal("stage_done refused S7", retry=retry))
            return (1 if refused else 0), ""
        d.py = py
        raised, _ = rig_.run()
        check_eq("N7: the refused stage_done is a Refusal that carries a retry", (type(raised).__name__, callable(getattr(raised, "retry", None))), ("Refusal", True))
        if callable(getattr(raised, "retry", None)):
            raised.retry()
        check_eq("N7: the retry runs stage_done ALONE: one finalize, one receipt, two stage_done calls",
                 (calls, [s for s, _a in rig_.py_log].count("code_only")), (["finalize_task.py", "stage_done.py", "stage_done.py"], 1))
    finally:
        rig_.done()


def stuck_text_names_the_open_decision() -> None:
    """§21 (ii): the stuck seam's text, when S7 waits on the person's recorded `open_work`, names that decision as the reason (one line instead of 'I
    cannot tell'); the call site (the loop) reads the decision, so a story with no such decision keeps today's words."""
    rig_ = LimitRig([ROW_1])
    try:
        d = rig_.driver
        plain, said = d.stuck_text("S7"), d.stuck_text("S7", waits_on_person=True)
        check_in("stuck: no decision -> today's words", "I cannot tell from here what is holding it", plain)
        check_in("stuck: S7 waiting on the person's open_work names that decision", "you decided to keep this stage open for more work", said)
        check_not_in("stuck: ...instead of 'I cannot tell'", "I cannot tell", said)
        check_eq("stuck: it is ONE added line (the head is the same)", said.split("\n\n")[0], plain.split("\n\n")[0])

        class Halt(BaseException):
            pass

        def loop(with_decision):
            seen = []
            decisions = rig_.task_root / "state" / "decisions"
            decisions.mkdir(parents=True, exist_ok=True)
            path = decisions / f"{LIFE}.json"
            path.unlink(missing_ok=True)
            if with_decision:
                path.write_text(json.dumps({"dispatch": LIFE, "stage": "S7", "open_work": {"words_ref": "state/words/w.txt", "at": "t"}}), encoding="utf-8")

            def no_move(state, moves=None):
                seen.append(state)
                raise Halt()
            d.where, d.boundary_step, d.no_move = (lambda: {"action": "prepare_stage", "stage": "S7"}), (lambda action: None), no_move
            try:
                quietly(d.run)
            except Halt:
                pass
            return seen[0]["lead"] if seen else ""
        check_in("stuck, the loop's call site: with the person's open_work recorded the seam's text names it", "you decided to keep this stage open",
                 loop(True))
        check_in("stuck, the loop's call site: without it the text is today's", "I cannot tell from here", loop(False))
    finally:
        rig_.done()


def main() -> None:
    tl5_the_analyst_is_only_as_fresh_as_the_triage()
    ts1_life_keeps_two_triages_apart()
    ts2_debt_is_final_for_its_test()
    ts3_a_repaired_row_is_not_rounded_again()
    ts5_edges_of_the_close()
    e9_the_s7_rule_stands_before_rework_of()
    e12_a_round_finished_outside_the_loop()
    n2_the_persons_decision_outranks_the_code()
    fx2_the_end_of_an_open_work_life_asks_one_closed_question()
    n3_the_relaunch_fallback_passes_the_analysts_completion()
    n7_a_refused_stage_done_retries_alone()
    stuck_text_names_the_open_decision()
    k5_stage_s7_asks_code_before_the_analyst()
    k6_nothing_failed_is_byte_identical()
    k8_s7_repairs_reads_the_declaration()
    rl8_refused_owed_round_is_taken_back()
    r7_the_reorder_round()
    r7_the_conductor_text()
    rl8_asked_once_per_test_and_count()
    rl8_closed_story_never_reaches_the_gate()
    k9_refresh_keeps_and_archives_code_rows()
    k10_the_s6_null_close_reduces_first()
    finish("story run s7")


if __name__ == "__main__":
    main()
