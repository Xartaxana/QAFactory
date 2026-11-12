#!/usr/bin/env python3
"""S7 by code: `s7_pretriage` writes a triage row for a manual `inconclusive` whose own record says what stopped it, and
for nothing else (t-305 N1, keys K1-K4 and K12 of the node spec; the Lead's edges (i), (ii), (v), (vi)).

TP1-15045 (man1, 02.10): five failures reached the analyst - four red tests and one manual `inconclusive` (TC_009)
whose record already said, in the runner's words, why the check could not conclude. Pre-judging the red ones is what the
brief's B-274 asked for and what P20 forbids: TC_004 and TC_008 are `blocked_by_env` only as S5's manifest rows, their
results are `failed`, and a red test goes to the analyst. Code decides one state.

THE INTEGRATOR'S HUNK. `NOT_EXECUTED` is a word of `contract.TRIAGE_VERDICTS` now (t-350), so `Verdict(present=True)`
patches nothing; only the scenario of edge (vi) runs inside `Verdict(present=False)`, which patches the word OUT of the
constant in this process (the world before the hunk). The patch is the test's own and never touches a file.

Proved here:
  * K1  the decision table R1-R11 (`R1` ... `R11` in every check name): code writes a row for R5 only;
  * K2  the adversarial battery a1-a9 stays with the analyst, except a8 (the boundary: another image id is the role's text);
  * K3  a code row binds through `contract.bind_triage` to exactly its failure, carrying `source: code`, `from` and the
        role's limitations verbatim;
  * K4  two runs give byte-equal triage.json; an analyst row on the same failure is never written over;
  * K12 the man1 fixture (copied slices of the run report, the manifest and an empty triage): exactly 1 of 5 failures is
        decided by code, the 4 red tests stay with the analyst; the same fixture without TC_009's role limitation: 0 of 5;
  * edges E4/E13/E20/E22, the unreadable triage, a missing triage, the temporal refusal, and the pin of the one sentence
        `manual_evidence` writes for the record's own identity.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import contract as C  # noqa: E402
import s7_pretriage as S  # noqa: E402

MAN1 = FIXTURES / "man1-s7"
IDENT = "image:sha256:" + "ab" * 32
ROLE_LIMITATION = "P-invalid not runnable: PUT validates, so no invalid saved revision can be seeded via the product."
IDENTITY = S.identity_sentence(IDENT)


class Verdict:
    """The world before (`present=False`) or after (`present=True`) NOT_EXECUTED is a word of
    `contract.TRIAGE_VERDICTS`. The word is real now (t-350), so `present=True` patches nothing and says so if it is
    missing; `present=False` patches the word OUT for the block (the temporal key) and restores the constant."""

    def __init__(self, present: bool):
        self.present = present

    def __enter__(self):
        self.saved = C.TRIAGE_VERDICTS
        if self.present:
            check("NOT_EXECUTED is a real word of contract.TRIAGE_VERDICTS (no patch is applied)", S.VERDICT in self.saved)
        else:
            C.TRIAGE_VERDICTS = tuple(w for w in self.saved if w != S.VERDICT)
        return self

    def __exit__(self, *_exc):
        C.TRIAGE_VERDICTS = self.saved


def result(name: str, status: str = "failed", **extra) -> dict:
    return {"instance_id": name, "test_id": "mod::" + name, "attempt_id": "x1", "status": status, "reason": "boom", **extra}


def check_row(case: str = "TC-9", outcome: str = "inconclusive", limitations="role", **over) -> dict:
    """A manual check as the reducer writes it: validated, one attempt, the stand identified by its image (so the code's
    identity sentence is among the limitations, as in man1)."""
    given = [ROLE_LIMITATION, IDENTITY] if limitations == "role" else limitations
    row = {"schema_version": 2, "case": case, "attempt_id": "a1", "result": outcome, "evidence_validated": True,
           "limitations": given, "runtime_identity": IDENT, "runtime_before": {"observed_runtime_identity": IDENT},
           "runtime_after": {"observed_runtime_identity": IDENT}, "obligation_ids": ["OB-9"],
           "evidence_refs": [{"path": f"work/evidence/manual/{case}/a1/001.png", "kind": "image", "phase": "pre_action"}]}
    row.update(over)
    return row


def report(results=(), manual=()) -> dict:
    return {"execution_status": "failed", "current_results": list(results), "current_manual_checks": list(manual),
            "current_totals": {"failed": len(results)}}


def manifest_with(*unresolved) -> dict:
    return {"tests": [], "unresolved": list(unresolved)}


def a_task(rep=None, man=None, triage=None, raw_triage=None) -> Path:
    task = temp_dir("qa-s7-pre-")
    work = task / "work"
    work.mkdir()
    for name, doc in (("run-report.json", rep), ("automation-manifest.json", man)):
        if doc is not None:
            (work / name).write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    if raw_triage is not None:
        (work / "triage.json").write_text(raw_triage, encoding="utf-8")
    elif triage is not None:
        (work / "triage.json").write_text(json.dumps({"schema_version": 2, "task_id": task.name, "triage": triage}),
                                          encoding="utf-8")
    return task


def triage_bytes(task: Path) -> bytes:
    path = task / "work" / "triage.json"
    return path.read_bytes() if path.exists() else b""


def triage_rows(task: Path) -> list:
    path = task / "work" / "triage.json"
    return json.loads(path.read_text(encoding="utf-8"))["triage"] if path.exists() else []


def run(task: Path, present: bool = True) -> dict:
    with Verdict(present):
        return S.pretriage(task)


def one(label: str, rep, *, man=None, triage=None, written=(), results=(), manual=(), unnamed=0, analyst=(),
        kept=(), rows_after=None) -> dict:
    """One decision: what code wrote, and what is left to the analyst, by name."""
    task = a_task(rep, man, triage if triage is not None else [])
    try:
        res = run(task)
        check_eq(f"{label}: code wrote a row for {list(written) or 'nothing'}", res["written"], list(written))
        check_eq(f"{label}: left to the analyst - red results", res["left"]["results"], list(results))
        check_eq(f"{label}: left to the analyst - manual checks", res["left"]["manual"], list(manual))
        check_eq(f"{label}: left to the analyst - nameless failures", len(res["left"]["unnamed"]), unnamed)
        check_eq(f"{label}: answered by an analyst row", res["analyst"], list(analyst))
        check_eq(f"{label}: code rows standing", res["kept"], list(kept))
        got = triage_rows(task)
        check_eq(f"{label}: triage.json holds {len(triage or []) + len(written)} row(s)", len(got),
                 len(triage or []) + len(written))
        if rows_after is not None:
            check_eq(f"{label}: the rows of triage.json", got, rows_after)
        return res
    finally:
        cleanup(task)


# ------------------------------------------------------------------------------------------------ K1: the table
def k1_the_decision_table() -> None:
    blocked = {"case": "TC-1", "reason": "blocked_by_env", "detail": "edit page stayed on Loading"}
    one("R1 a red result", report([result("t_a[json]")]), results=["t_a[json]"])
    one("R2 an errored result", report([result("t_b", "error")]), results=["t_b"])
    one("R3 a red result that is unverified", report([result("t_c", verification_status="unverified")]), results=["t_c"])
    one("R4 a manual fail", report(manual=[check_row("TC-4", "fail")]), manual=["TC-4"])
    one("R5 a manual inconclusive with a limitation of the role's own", report(manual=[check_row()]),
        written=["TC-9"], kept=["TC-9"])
    one("R6 a reducer-made inconclusive (current_reason)", report(manual=[check_row(current_reason="ambiguous_attempt_order")]),
        manual=["TC-9"])
    one("R6 ...and one the reducer marked evidence_validated: false",
        report(manual=[check_row(evidence_validated=False, evidence_errors=["x"])]), manual=["TC-9"])
    one("R7 a manual error", report(manual=[check_row("TC-7", "error")]), manual=["TC-7"])
    one("R8 an inconclusive whose case has a contradicts_requirement row",
        report(manual=[check_row()]), man=manifest_with({"case": "TC-9", "reason": "contradicts_requirement", "detail": "R-17"}),
        manual=["TC-9"])
    old = {"instance_id": "TC-9", "attempt_id": "a1", "case": "TC-9", "verdict": "APP_BUG", "evidence": "evidence/x"}
    one("R9 a failure the analyst already answered", report(manual=[check_row()]), triage=[old], analyst=["TC-9"],
        rows_after=[old])
    code_row = {"instance_id": "TC-9", "attempt_id": "a1", "case": "TC-9", "verdict": S.VERDICT, "source": S.SOURCE,
                "evidence": ["x"]}
    one("R9 ...and one a code row already answers: nothing is added", report(manual=[check_row()]), triage=[code_row],
        kept=["TC-9"], rows_after=[code_row])
    one("R10 a failed result with no id", report([{"status": "failed", "reason": "boom"}]), unnamed=1)
    one("R10 ...and a manual check with no name", report(manual=[{"result": "inconclusive", "limitations": [ROLE_LIMITATION],
                                                                  "evidence_validated": True, "attempt_id": "a1"}]), unnamed=1)
    one("R11 a red result whose manifest row says blocked_by_env (man1 TC_004) is NOT pre-judged",
        report([result("t_ui")]), man=manifest_with(blocked), results=["t_ui"])
    one("-- a skipped result and an env-blocked row are no failure at all",
        dict(report([result("t_s", "skipped")]), env_blocked=[{"case": "TC-2"}], current_env_blocked=[{"case": "TC-2"}]))
    # the whole table at once: one row written, the rest named, in the order the failures have
    mixed = report([result("t_a"), result("t_b", "error")], [check_row("TC-9"), check_row("TC-4", "fail")])
    one("a mixed report: only R5 is decided", mixed, written=["TC-9"], results=["t_a", "t_b"], manual=["TC-4"], kept=["TC-9"])


# --------------------------------------------------------------------------------------- K2: the adversarial set
def k2_the_adversarial_battery() -> None:
    one("a1 an inconclusive whose ONLY limitation is the identity sentence", report(manual=[check_row(limitations=[IDENTITY])]),
        manual=["TC-9"])
    one("a1 ...with the sentence twice and a blank", report(manual=[check_row(limitations=[IDENTITY, IDENTITY, "  "])]),
        manual=["TC-9"])
    one("a1 ...the sentence with whitespace round it is still the code's", report(manual=[check_row(limitations=["  " + IDENTITY + "\n"])]),
        manual=["TC-9"])
    one("a2 a reducer-made inconclusive (an invalidated record)", report(manual=[check_row(current_reason="invalidated_evidence")]),
        manual=["TC-9"])
    one("a3 evidence_validated false", report(manual=[check_row(evidence_validated=False)]), manual=["TC-9"])
    no_flag = check_row()
    del no_flag["evidence_validated"]
    one("a3 ...and absent (a record the reducer did not validate)", report(manual=[no_flag]), manual=["TC-9"])
    one("a3 ...and the string \"true\" is not true", report(manual=[check_row(evidence_validated="true")]), manual=["TC-9"])
    one("a4 an inconclusive plus contradicts_requirement for its case (E22: CASE_DEFECT is the analyst's alone)",
        report(manual=[check_row()]), man=manifest_with({"case": "TC-9", "reason": "contradicts_requirement"}), manual=["TC-9"])
    one("a4 ...a row naming the case only in covers[]", report(manual=[check_row()]),
        man=manifest_with({"covers": ["TC-1", "TC-9"], "reason": "contradicts_requirement"}), manual=["TC-9"])
    one("a4 ...a row naming no case at all holds back every manual check (it cannot be told whose it is)",
        report(manual=[check_row()]), man=manifest_with({"reason": "contradicts_requirement", "detail": "x"}), manual=["TC-9"])
    one("a4 control: a contradicts row of ANOTHER case holds nothing back", report(manual=[check_row()]),
        man=manifest_with({"case": "TC-2", "reason": "contradicts_requirement"}), written=["TC-9"], kept=["TC-9"])
    one("a5 man1's TC_004 shape: a red result plus a manifest blocked_by_env row", report([result("t_ui")]),
        man=manifest_with({"case": "TC-4", "reason": "blocked_by_env"}), results=["t_ui"])
    one("a6 a manual fail with a role limitation", report(manual=[check_row("TC-6", "fail")]), manual=["TC-6"])
    one("a7 limitations that are not strings", report(manual=[check_row(limitations=[None, 5, {"x": 1}, [], True, "", " "])]),
        manual=["TC-9"])
    one("a7 ...limitations that are not a list", report(manual=[check_row(limitations="a role sentence")]), manual=["TC-9"])
    one("a7 ...no limitations key at all", report(manual=[{k: v for k, v in check_row().items() if k != "limitations"}]),
        manual=["TC-9"])
    task = a_task(report(manual=[check_row(limitations=[None, "", ROLE_LIMITATION, 7, IDENTITY])]), None, [])
    try:
        run(task)
        row = triage_rows(task)[0]
        check_eq("a7 control: among the junk the one real sentence is the row's whole limitation", row["limitation"], [ROLE_LIMITATION])
    finally:
        cleanup(task)
    other = S.identity_sentence("image:sha256:" + "cd" * 32)
    one("a8 the identity sentence with ANOTHER image id is the role's text (the boundary): code writes",
        report(manual=[check_row(limitations=[other])]), written=["TC-9"], kept=["TC-9"])
    one("a8 ...and a copy of the sentence's head only is the role's text too", report(manual=[check_row(limitations=[S.IDENTITY_HEAD])]),
        written=["TC-9"], kept=["TC-9"])
    # a9: only the CURRENT list counts
    history = [check_row("TC-9", "inconclusive", attempt_id="a1")]
    now = [check_row("TC-9", "pass", attempt_id="a2")]
    one("a9 an old inconclusive attempt beside a current pass: no failure at all",
        dict(report(manual=now), manual_checks=history + now))
    one("a9 ...the current inconclusive is the one written (attempt a2), the old attempt is not read",
        dict(report(manual=[check_row("TC-9", attempt_id="a2")]), manual_checks=history + [check_row("TC-9", attempt_id="a2")]),
        written=["TC-9"], kept=["TC-9"])
    one("a9 ...two failing rows of ONE case on two attempts: left to the analyst",
        report(manual=[check_row("TC-9", attempt_id="a1"), check_row("TC-9", attempt_id="a2")]), manual=["TC-9"])
    one("a9 ...two failing rows on one attempt (two obligations): one row, both limitations",
        report(manual=[check_row("TC-9"), check_row("TC-9", limitations=["a second thing stopped it", IDENTITY])]),
        written=["TC-9"], kept=["TC-9"])
    one("a9 ...but one of the two is a fail: the analyst's", report(manual=[check_row("TC-9"), check_row("TC-9", "fail")]),
        manual=["TC-9"])
    one("E4 no attempt_id (the analyst's own producer refuses a row without one)", report(manual=[check_row(attempt_id="")]),
        manual=["TC-9"])
    # legacy list: `manual_checks` read when the current list is empty (as triage_targets does)
    legacy = {"execution_status": "failed", "current_results": [], "manual_checks": [check_row()]}
    task = a_task(legacy, None, [])
    try:
        res = run(task)
        check_eq("a legacy report (manual_checks only): the same decision, pointer names that list", res["written"], ["TC-9"])
        check_in("...pointer", "manual_checks[case=TC-9, attempt=a1]", json.dumps(triage_rows(task)))
    finally:
        cleanup(task)


# ------------------------------------------------------------------------------- K3: the row and its binding
def k3_a_code_row_binds_to_exactly_its_failure() -> None:
    task = a_task(report([result("t_a")], [check_row("TC-9"), check_row("TC-5", "pass", limitations=[IDENTITY])]), None, [])
    try:
        res = run(task)
        rows = triage_rows(task)
        check_eq("K3: one row written", [r["instance_id"] for r in rows], ["TC-9"])
        row = rows[0]
        check_eq("K3: verdict, source", (row["verdict"], row["source"]), (S.VERDICT, S.SOURCE))
        check_eq("K3: from.state and from.artifact", (row["from"]["state"], row["from"]["artifact"]),
                 ("inconclusive", "work/run-report.json"))
        check_eq("K3: from.pointer names the list, the case and the attempt", row["from"]["pointer"],
                 "current_manual_checks[case=TC-9, attempt=a1]")
        check_eq("K3: the role's limitation is quoted VERBATIM, the code's identity sentence is not", row["limitation"], [ROLE_LIMITATION])
        check_eq("K3: the evidence paths of the record", row["evidence"], ["work/evidence/manual/TC-9/a1/001.png"])
        check_eq("K3: instance_id and attempt_id are there (artifact_producer requires both of every row)",
                 (row["instance_id"], row["attempt_id"], row["case"]), ("TC-9", "a1", "TC-9"))
        report_doc = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))
        failures, unnamed = C.triage_failures(report_doc)
        bound = C.bind_triage(failures, rows)
        check_eq("K3: the row binds to exactly its failure (matched 1), nothing is ambiguous",
                 ({k[1]: len(v) for k, v in bound["matched"].items()}, bound["ambiguous"]), ({"t_a": 0, "TC-9": 1}, []))
        check_eq("K3: the red result beside it still has no row", res["left"]["results"], ["t_a"])
        # NEG: a row keyed by `case` only, for a RESULT failure that belongs to that case, answers nothing (a result
        # failure is named by its instance or test id; its case is not a name - t-323 A1)
        with_case = dict(report_doc, current_results=[dict(result("t_a"), case="TC-1")])
        failures_c, _unnamed = C.triage_failures(with_case)
        bound = C.bind_triage(failures_c, [{"case": "TC-1", "verdict": S.VERDICT, "source": S.SOURCE}])
        check_eq("K3 NEG: a `case`-keyed row for a RESULT failure binds to nothing and is not ambiguous",
                 ({k[1]: len(v) for k, v in bound["matched"].items() if k[0] == "result"}, bound["ambiguous"]), ({"t_a": 0}, []))
        bound = C.bind_triage(failures_c, [{"instance_id": "t_a", "verdict": S.VERDICT, "source": S.SOURCE}])
        check_eq("K3 control: the same row keyed by the instance id binds",
                 {k[1]: len(v) for k, v in bound["matched"].items() if k[0] == "result"}, {"t_a": 1})
    finally:
        cleanup(task)


# ------------------------------------------------------------------------- K4: idempotent, never over an analyst
def k4_two_runs_and_the_analysts_row() -> None:
    task = a_task(report(manual=[check_row()]), None, [])
    try:
        first = run(task)
        before = triage_bytes(task)
        second = run(task)
        check_eq("K4: the second run writes nothing", second["written"], [])
        check_eq("K4: ...and both runs say the same row stands", (first["kept"], second["kept"]), (["TC-9"], ["TC-9"]))
        check_eq("K4: triage.json is byte-equal after the second run", triage_bytes(task), before)
    finally:
        cleanup(task)
    analyst = {"instance_id": "TC-9", "attempt_id": "a1", "case": "TC-9", "verdict": "APP_BUG", "owner": "factory",
               "evidence": "evidence/manual/TC-9/a1.json", "our_signal": "own words"}
    task = a_task(report(manual=[check_row()]), None, [analyst])
    try:
        before = triage_bytes(task)
        res = run(task)
        check_eq("K4: an analyst's APP_BUG row on TC-9 stays APP_BUG and no code row is added", triage_rows(task), [analyst])
        check_eq("K4: ...byte for byte", triage_bytes(task), before)
        check_eq("K4: ...and the report says the analyst's row answers it", (res["written"], res["analyst"], res["kept"]),
                 ([], ["TC-9"], []))
        check_eq("K4: ...so S7 does not close by code over it", res["closes"], False)
    finally:
        cleanup(task)
    # an analyst row that REPLACED a code row (Q11): the analyst's wins, code does not bring its row back
    task = a_task(report(manual=[check_row()]), None, [])
    try:
        run(task)
        replaced = dict(analyst, verdict="ENV_ISSUE")
        (task / "work" / "triage.json").write_text(json.dumps({"triage": [replaced]}), encoding="utf-8")
        before = triage_bytes(task)
        run(task)
        check_eq("K4 Q11: the analyst replaced the code row with its own: it stays, code adds nothing", triage_bytes(task), before)
    finally:
        cleanup(task)
    # E10: the analyst dropped the code row: the next run writes it back
    task = a_task(report(manual=[check_row()]), None, [])
    try:
        run(task)
        (task / "work" / "triage.json").write_text(json.dumps({"schema_version": 2, "triage": []}), encoding="utf-8")
        res = run(task)
        check_eq("E10: a code row the analyst dropped is restored by the next run", (res["written"], len(triage_rows(task))), (["TC-9"], 1))
    finally:
        cleanup(task)


def closing_and_the_brief() -> None:
    """`closes` is true only when EVERY failure is answered by a code row; `brief` names only what is left."""
    task = a_task(report(manual=[check_row("TC-9"), check_row("TC-8", limitations=["the capture could not read the page"])]),
                  None, [])
    try:
        res = run(task)
        check_eq("closes: every failure is a code row", (res["closes"], res["kept"], res["failures"]), (True, ["TC-9", "TC-8"], 2))
    finally:
        cleanup(task)
    task = a_task(report([result("t_a")], [check_row("TC-9")]), None, [])
    try:
        res = run(task)
        check_eq("closes: a red result beside it keeps the analyst", res["closes"], False)
        check_eq("brief: names the red result only", S.brief([("result", n) for n in res["left"]["results"]], res["left"]["unnamed"]),
                 "failed results t_a")
    finally:
        cleanup(task)
    check_eq("brief: results, manual checks and a note, in that order",
             S.brief([("manual", "TC-4"), ("result", "t_a"), ("result", "t_b")], ["failed result row #3 has no instance_id"]),
             "failed results t_a, t_b; manual TC-4; failed result row #3 has no instance_id")
    check_eq("brief: nothing left reads empty", S.brief([], []), "")
    check_eq("no failure at all: nothing closes by code (the old close stands)", run(a_task(report(), None, []))["closes"], False)


# -------------------------------------------------------------------------------------------- K12: the man1 shape
def k12_the_man1_fixture() -> None:
    rep = json.loads((MAN1 / "run-report.json").read_text(encoding="utf-8"))
    failures, unnamed = C.triage_failures(rep)
    kinds = sorted(k[0] for k in failures)
    print(f"step 0 (man1 slice): contract.triage_failures = {kinds.count('result')} failed results, "
          f"{kinds.count('manual')} manual inconclusive, {len(unnamed)} unnamed")
    check_eq("K12 step 0: the fixture holds 4 failed results and 1 manual inconclusive", (kinds.count("result"), kinds.count("manual"), unnamed),
             (4, 1, []))
    check_eq("K12 step 0: current_totals as in man1", rep["current_totals"], {"failed": 4, "inconclusive": 1, "passed": 11, "skipped": 2})
    task = temp_dir("qa-s7-man1-")
    try:
        (task / "work").mkdir()
        for name, target in (("run-report.json", "run-report.json"), ("automation-manifest.json", "automation-manifest.json"),
                             ("triage-empty.json", "triage.json")):
            (task / "work" / target).write_bytes((MAN1 / name).read_bytes())
        res = run(task)
        rows = triage_rows(task)
        check_eq("K12: exactly 1 of 5 failures is decided by code: TC_009", (res["written"], len(rows)), (["TP1-15045_TC_009"], 1))
        check_eq("K12: ...its source state is inconclusive", rows[0]["from"]["state"], "inconclusive")
        check_eq("K12: ...with the runner's own sentence only (the identity line is the code's)", rows[0]["limitation"],
                 [json.loads((MAN1 / "run-report.json").read_text(encoding="utf-8"))["current_manual_checks"][3]["limitations"][0]])
        check_eq("K12: ...and its three evidence files", len(rows[0]["evidence"]), 3)
        check_eq("K12: the 4 red tests are left to the analyst (TC_010 and TC_015 are red with contradicts_requirement rows, TC_004 and "
                 "TC_008 are red with blocked_by_env rows)",
                 sorted(res["left"]["results"]),
                 sorted(["test_validate_rejects_bad_input_with_same_code_as_put[json]",
                         "test_put_invalid_input_returns_stable_code_and_stores_nothing[multi]",
                         "test_version_history_button_accessible_from_visual_editor",
                         "test_shortcuts_with_history_popup_open_change_neither_diff_nor_editor"]))
        check_eq("K12: no manual check and nothing nameless is left", (res["left"]["manual"], res["left"]["unnamed"]), ([], []))
        check_eq("K12: S7 does not close by code (4 red tests need the analyst)", res["closes"], False)
        check_eq("K12: the kept-rows line would name TC_009", res["kept"], ["TP1-15045_TC_009"])
        # what the real code wrote into the real record is the sentence the module compares against (the pin on real data)
        check("K12: the identity line of the real TC_009 record IS identity_sentence(its own image)",
              S.identity_sentence(rep["current_manual_checks"][3]["runtime_before"]["observed_runtime_identity"])
              in rep["current_manual_checks"][3]["limitations"])
    finally:
        cleanup(task)
    # NEG: the same fixture with TC_009's role limitation removed: 0 code rows, 5 failures for the analyst
    task = temp_dir("qa-s7-man1-neg-")
    try:
        (task / "work").mkdir()
        bare = json.loads((MAN1 / "run-report.json").read_text(encoding="utf-8"))
        tc9 = next(r for r in bare["current_manual_checks"] if r["case"].endswith("TC_009"))
        tc9["limitations"] = [t for t in tc9["limitations"] if t == S.identity_sentence(tc9["runtime_before"]["observed_runtime_identity"])]
        (task / "work" / "run-report.json").write_text(json.dumps(bare), encoding="utf-8")
        (task / "work" / "automation-manifest.json").write_bytes((MAN1 / "automation-manifest.json").read_bytes())
        (task / "work" / "triage.json").write_bytes((MAN1 / "triage-empty.json").read_bytes())
        res = run(task)
        check_eq("K12 NEG: without the role's limitation 0 rows are written and 5 failures are the analyst's",
                 (res["written"], len(res["left"]["results"]) + len(res["left"]["manual"]), triage_rows(task)), ([], 5, []))
    finally:
        cleanup(task)


# -------------------------------------------------------------------------------------------------- the edges
def edges() -> None:
    # (vi) temporal: the verdict is not yet a word of the contract
    task = a_task(report([result("t_a")], [check_row("TC-9")]), None, [])
    try:
        before = triage_bytes(task)
        res = run(task, present=False)
        check_eq("(vi) before the hunk: nothing is written, the file is untouched", (res["written"], triage_bytes(task)), ([], before))
        check_in("(vi) ...and the refusal names the constant", "contract.TRIAGE_VERDICTS", res["refused"])
        check_in("(vi) ...the verdict", S.VERDICT, res["refused"])
        check_in("(vi) ...and the door: the integrator's change, and what until then", "the integrator's change", res["refused"])
        check_eq("(vi) ...the manual check goes to the analyst as it did before", res["left"]["manual"], ["TC-9"])
        check_eq("(vi) ...and S7 does not close by code", res["closes"], False)
        check_in("(vi) ...the driver prints it", "S7 pre-triage", " ".join(res["notes"]))
        res = run(task, present=True)
        check_eq("(vi) after the hunk the same task gets its row", (res["written"], res["refused"]), (["TC-9"], ""))
    finally:
        cleanup(task)
    task = a_task(report([result("t_a")]), None, [])
    try:
        check_eq("(vi) before the hunk, nothing to decide: no refusal is printed", run(task, present=False)["refused"], "")
    finally:
        cleanup(task)
    # E13: no run report - nothing written, ONE text with the `blocked` door
    task = a_task(None, None, [])
    try:
        before = triage_bytes(task)
        res = run(task)
        import handoff_check as HC
        check_eq("E13: no run report: nothing written, nothing decided", (res["written"], res["failures"], triage_bytes(task)), ([], 0, before))
        check_in("E13: the one unreadable-report sentence of the S7 form check", HC.REPORT_UNREADABLE, res["refused"])
        check_in("E13: ...with its `blocked` door", HC.REPORT_DOOR, res["refused"])
        check_in("E13: ...and what code could not tell", HC.REPORT_TELL, res["refused"])
    finally:
        cleanup(task)
    for label, text in (("not JSON", "{broken"), ("not an object", "[1, 2]"), ("no results list", json.dumps({"execution_status": "failed"}))):
        task = a_task(text, None, [])
        try:
            res = run(task)
            check_eq(f"E13: a run report that is {label}: nothing written, the refusal stands", (res["written"], bool(res["refused"])), ([], True))
        finally:
            cleanup(task)
    # the analyst's triage that cannot be read is never overwritten by a guess
    for label, raw in (("not JSON", "{broken"), ("not an object", "[]"), ("no triage list", json.dumps({"reason": "x"})),
                       ("a row that is not an object", json.dumps({"triage": [1]}))):
        task = a_task(report(manual=[check_row()]), None, raw_triage=raw)
        try:
            res = run(task)
            check_eq(f"a triage.json that is {label} is left byte for byte", (res["written"], triage_bytes(task)), ([], raw.encode("utf-8")))
            check_in(f"...and the refusal names the file ({label})", "work/triage.json", res["refused"])
            check_eq(f"...the failure goes to the analyst ({label})", res["left"]["manual"], ["TC-9"])
        finally:
            cleanup(task)
    # a triage.json that does not exist yet is created, whole
    task = a_task(report(manual=[check_row()]), None)
    try:
        res = run(task)
        doc = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
        check_eq("no triage.json yet: it is created with its envelope and the one row", (res["written"], doc["schema_version"],
                 doc["task_id"] == task.name, len(doc["triage"])), (["TC-9"], 2, True, 1))
    finally:
        cleanup(task)
    # other keys of the analyst's file survive an addition
    task = a_task(report(manual=[check_row()]), None, raw_triage=json.dumps({"schema_version": 2, "triage": [], "reducer": {"name": "x"},
                                                                          "analyst_preserved": False}))
    try:
        run(task)
        doc = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
        check_eq("an existing document keeps its other keys", (doc["reducer"], doc["analyst_preserved"], len(doc["triage"])), ({"name": "x"}, False, 1))
    finally:
        cleanup(task)
    # E20: the write is atomic_json's, once
    task = a_task(report(manual=[check_row("TC-9"), check_row("TC-8", limitations=["capture stopped"])]), None, [])
    calls = []
    saved = S.atomic_json
    try:
        S.atomic_json = lambda path, value: (calls.append((Path(path).name, len(value["triage"]))), saved(path, value))[1]
        run(task)
        check_eq("E20: ONE atomic_json write of triage.json carrying both rows", calls, [("triage.json", 2)])
        check_eq("E20: and no temporary file is left behind", sorted(p.name for p in (task / "work").glob("*.tmp")), [])
        run(task)
        check_eq("E20: the second run does not write at all", len(calls), 1)
    finally:
        S.atomic_json = saved
        cleanup(task)
    # the decision is pure: no file is needed
    check_eq("decide() reads nothing: a report in, rows out", [r["instance_id"] for r in S.decide(report(manual=[check_row()]), {}, [])["write"]], ["TC-9"])
    check_eq("decide() on a report that is not an object: no failure", S.decide("x", None, None)["failures"], 0)


PERSON_WORD = {"result": "person_confirmed", "observed_runtime_identity": IDENT,
               "person_confirmation": {"words": "yes, it is deployed", "at": "2026-10-02T11:00:00+00:00", "task": "TP1-15045",
                                       "kind": "deployed", "revision": "a" * 40}}


def the_identity_sentence_is_the_one_manual_evidence_writes() -> None:
    """The image sentence is a second copy that `manual_evidence` NO LONGER WRITES (t-300 N2: an `unknown` is not taken, so no
    new record is built on an image identity) but that 3 records of TP1-15045 still carry (F11): `code_sentences` keeps
    recognising it, pinned on the frozen man1 record by K12. The sentences of a person's word are the other kind: ONE function
    (`manual_evidence.person_sentences`) writes them and `code_sentences` reads the same function (X12, K-N2.13)."""
    import manual_evidence as MEv
    text = (PLUGIN_ROOT / "scripts" / "manual_evidence.py").read_text(encoding="utf-8")
    check("pin positive control: the same search finds a phrase known to be in manual_evidence.py",
          "inconclusive requires a limitation" in text)
    check("pin (F11): manual_evidence.py no longer writes the image sentence, and s7_pretriage still knows it",
          S.IDENTITY_HEAD not in text and bool(S.identity_sentence("X")))
    check_eq("the sentence for one id", S.identity_sentence("X"), "the stand was identified by the image it runs (X), not by the sources it serves")
    sentences = MEv.person_sentences(PERSON_WORD)
    check_eq("K-N2.13: code_sentences yields the sentence manual_evidence writes for a person's word (one function, imported), "
             "beside the image sentence F11 keeps (the identity of that record)",
             sorted(S.code_sentences({"runtime_before": PERSON_WORD, "runtime_identity": ""})),
             sorted([*sentences, S.identity_sentence(IDENT)]))
    check_eq("K-N2.13: ...and from the record's runtime_after too",
             set(sentences) <= S.code_sentences({"runtime_before": {"observed_runtime_identity": IDENT}, "runtime_after": PERSON_WORD}), True)
    # K-N2.13: an `inconclusive` whose ONLY limitation is the person's-word sentence is left to the analyst (nothing of the role's)
    only = check_row("TC-9", limitations=list(sentences), runtime_before=PERSON_WORD, runtime_after=dict(PERSON_WORD))
    out = S.decide(report(manual=[only]), {}, [])
    check_eq("K-N2.13: an inconclusive whose only limitation is the PC sentence is left to the analyst",
             ([r["instance_id"] for r in out["write"]], out["why"][("manual", "TC-9")]),
             ([], "its record carries no limitation of the role's own"))
    both = check_row("TC-9", limitations=[ROLE_LIMITATION, *sentences], runtime_before=PERSON_WORD, runtime_after=dict(PERSON_WORD))
    out = S.decide(report(manual=[both]), {}, [])
    check_eq("K-N2.13 CONTROL: with the role's own text beside it the check gets its code row, carrying the role's text only",
             [(r["instance_id"], r["limitation"]) for r in out["write"]], [("TC-9", [ROLE_LIMITATION])])
    check_eq("K-N2.13 CONTROL: a role's text that merely MENTIONS the word is the role's (exact equality is the whole test, FR-12)",
             S.role_limitations(check_row(limitations=["the build was confirmed by the person (yes, it is deployed), not read by the factory"],
                                          runtime_before=PERSON_WORD)),
             ["the build was confirmed by the person (yes, it is deployed), not read by the factory"])
    check_eq("code_sentences reads both identities a record carries",
             sorted(S.code_sentences({"runtime_before": {"observed_runtime_identity": "A"}, "runtime_identity": "B"})),
             sorted([S.identity_sentence("A"), S.identity_sentence("B")]))
    check_eq("...and none from a record that carries none (every limitation is then the role's)",
             S.code_sentences({"runtime_before": "x", "runtime_identity": ""}), set())
    check_eq("role_limitations keeps order and drops repeats", S.role_limitations({"limitations": ["b", "a", "b", IDENTITY],
                                                                                  "runtime_identity": IDENT}), ["b", "a"])


def the_whole_sentence_is_what_the_live_writer_produces() -> None:
    """t-352 F2 (t-300 N2: the live writer now writes the sentences of a PERSON'S WORD, not the image one): the pin against the
    live writer. The REAL `manual_evidence.py build` (the scaffold and steps of test_manual_capture's K-N2.8) writes a record on a
    person's word, and every sentence `code_sentences` knows for it must equal, byte for byte, a limitation the writer wrote:
    a writer that changes one character turns this red, and the role would then be handed code's own sentence as its text.
    The image sentence (3 old records carry it) is pinned by the frozen man1 K12."""
    import test_manual_capture as TM
    scaffold = TM.S
    t = scaffold.make_task()
    try:
        TM.seed_runtime_records(t)
        steps = TM._write(t, f"goto {TM.UI}\ncapture pre_action initial\ncapture post_action completion\n")
        TM.patch_backends(scaffold.FakeBrowser(), probes=lambda spec: TM.person_probe())
        scaffold.run(["ui", "--task-root", str(t.task), "--case", TM.UI_CASE, "--steps-file", str(steps)])
        code, _out, err = TM.build(t, TM.UI_CASE, "--result", "pass", "--actual", "the scale grew", "--masked")
        check_eq("F2: the live writer built a record on the person's word" + ("" if code == 0 else " | " + err[:200]), code, 0)
        record = json.loads((t.attempt_dir(TM.UI_CASE) / "record.json").read_text(encoding="utf-8"))
        sentences = S.code_sentences(record)
        check_eq("F2: code knows the person's-word sentence of this record (not empty: the pin has something to pin)",
                 len([s for s in sentences if "confirmed by the person" in s]), 1)
        check("F2: every sentence code knows for it IS, byte for byte, a limitation the live writer wrote (except the image one, "
              "which this record does not carry)", all(s in record["limitations"] for s in sentences if "confirmed by the person" in s))
        check_eq("F2: and it is the code's only limitation of that record (no limitation of the role's is left)",
                 S.role_limitations(record), [])
    finally:
        scaffold.cleanup(t)


def main() -> None:
    k1_the_decision_table()
    k2_the_adversarial_battery()
    k3_a_code_row_binds_to_exactly_its_failure()
    k4_two_runs_and_the_analysts_row()
    closing_and_the_brief()
    k12_the_man1_fixture()
    edges()
    the_identity_sentence_is_the_one_manual_evidence_writes()
    the_whole_sentence_is_what_the_live_writer_produces()
    finish("s7 pretriage")


if __name__ == "__main__":
    main()
