#!/usr/bin/env python3
"""GW1-41: the register fence of the S3 exit (A1, A4, A6, A7 of docs/tasks/specs/t-525-fence-amendment.md).
KEYS: F1 `row_requirements` forms (read / deliberately not read / junk), F2 `requirements_without_row` (plan side, md side, whole-id,
dispositions, `md_known`), F3 `contract.register_fence_view` (the unreadable cases of A4), F4 the detector (the fence runs, `not_planned`
stands in for nothing, UNREADABLE never hides a REJECT and never prints beside one, an exception of the fence is `unknown`, window 1
reads nothing), F5 `requirements_waiting_without_branch` + `no_row_for_question` (A6), F6 `row_owes_case` + `level` (A7),
F7 the test-plan.md reading (`parse_plan` ids) and the F-5 warning list."""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import planning_contract as PC  # noqa: E402


def row(rid="TS-1", disposition="skip", reqs=("R-9",), **extra) -> dict:
    return {"id": rid, "requirements": list(reqs), "disposition": disposition, "reason": "r", **extra}


def question(qid="Q2", text="Is R-9 in scope?", status="named", **extra) -> dict:
    return {"id": qid, "question": text, "source_says": "", "status": status, "letters": ["a", "b"], "readings": [
        {"id": "a", "reading": "in"}, {"id": "b", "reading": "out"}], **extra}


# --- F1: row_requirements --------------------------------------------------------------------------
check_eq("F1 requirements", PC.row_requirements({"requirements": ["R-9"]}), ["R-9"])
check_eq("F1 r_refs (13877)", PC.row_requirements({"r_refs": ["R-1"]}), ["R-1"])
check_eq("F1 obligation requirement_refs, string and {ref, revision}",
         PC.row_requirements({"coverage_obligations": [{"requirement_refs": ["R-2", {"ref": "R-3", "revision": "x"}]}]}), ["R-2", "R-3"])
check_eq("F1 register: prefix", PC.row_requirements({"risk_source_refs": ["register:R-9"]}), ["R-9"])
check_eq("F1 if_answered is NOT read (a branch nobody took is no cover)",
         PC.row_requirements({"if_answered": {"Q1": {"a": {"requirements": ["R-9"]}}}}), [])
check_eq("F1 oracle fields are NOT read", PC.row_requirements({"observation_contract": {"oracle_ref": "R-3", "oracle": "R-3"}}), [])
check_eq("F1 a work/requirements-register.md#R-12 ref is no prefix form", PC.row_requirements({"risk_source_refs": ["work/requirements-register.md#R-12"]}), [])
check_eq("F1 junk risk_source_refs (5) does not raise", PC.row_requirements({"risk_source_refs": 5, "requirements": ["R-9"]}), ["R-9"])
check_eq("F1 junk coverage_obligations / requirement_refs do not raise",
         PC.row_requirements({"coverage_obligations": 5, "r_refs": 7}) + PC.row_requirements({"coverage_obligations": [{"requirement_refs": 3}, 4]}), [])
check_eq("F1 order of first appearances: plain keys, then risk_source_refs, then the new keys",
         PC.row_requirements({"r_refs": ["R-3"], "risk_source_refs": ["register:R-2"], "requirements": ["R-1"]}), ["R-1", "R-2", "R-3"])

# --- F2: requirements_without_row --------------------------------------------------------------------
md = [{"requirements": ["R-9"]}]
check_eq("F2 closed in both", PC.requirements_without_row([row()], md, ["R-9"]), [])
check_eq("F2 JSON names, md does not -> where md", PC.requirements_without_row([row()], [{"requirements": []}], ["R-9"]), [{"id": "R-9", "where": "md"}])
check_eq("F2 md names, JSON does not -> where plan", PC.requirements_without_row([row(reqs=())], md, ["R-9"]), [{"id": "R-9", "where": "plan"}])
for wrong in ("R-09", "R-90", "BR-9", "R-9.", "(R-9)"):
    check_eq(f"F2 whole value only: {wrong!r} does not close R-9", PC.requirements_without_row([row(reqs=(wrong,))], md, ["R-9"]),
             [{"id": "R-9", "where": "plan"}])
check_eq("F2 prose in a closed key with a disposition and an md line: the accepted gap",
         PC.requirements_without_row([{"id": "TS-1", "disposition": "skip", "covers": "does not cover R-9"}], md, ["R-9"]), [])
check_eq("F2 no disposition from the closed list: the row counts for nothing",
         PC.requirements_without_row([{"id": "TS-1", "requirements": ["R-9"], "disposition": "deferred"}], md, ["R-9"]),
         [{"id": "R-9", "where": "plan"}])
check_eq("F2 only an if_answered patch names it: refused",
         PC.requirements_without_row([row(reqs=(), if_answered={"Q1": {"a": {"requirements": ["R-9"]}}})], md, ["R-9"]),
         [{"id": "R-9", "where": "plan"}])
check_eq("F2 rows not a list / row not a dict: all ids refused, no raise",
         PC.requirements_without_row("x", md, ["R-9"]) + PC.requirements_without_row(["x", 5], md, ["R-9"]),
         [{"id": "R-9", "where": "plan"}] * 2)
check_eq("F2 risk_source_refs: 5 -> not raising, refused", PC.requirements_without_row([{"id": "TS-1", "disposition": "skip", "risk_source_refs": 5}], md, ["R-9"]),
         [{"id": "R-9", "where": "plan"}])
check_eq("F2 no test-plan.md (md_known=False): the md half is silent", PC.requirements_without_row([row()], [], ["R-9"], md_known=False), [])
check_eq("F2 md without a plan table ([]): every id is where md", PC.requirements_without_row([row()], [], ["R-9"], md_known=True),
         [{"id": "R-9", "where": "md"}])
check_eq("F2 an obligation names it and the md has it: closed, named only by reference",
         PC.requirements_without_row([row(reqs=(), coverage_obligations=[{"requirement_refs": [{"ref": "R-9"}]}])], md, ["R-9"]), [])
check_eq("F7 by-reference list (F-5), one list per plan",
         PC.requirements_by_reference_only([row(reqs=(), r_refs=["R-9"]), row("TS-2", reqs=("R-8",))], ["R-9", "R-8"]), ["R-9"])

# --- F3: register_fence_view -------------------------------------------------------------------------
tmp = harness.temp_dir()


def reg(name, text) -> Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


HEAD = "## Register\n\n| R | requirement | source | derived_from |\n|---|---|---|---|\n"
view = C.register_fence_view(tmp / "absent.md")
check_eq("F3 no file -> unknown", view["state"], "unknown")
check_in("F3 no file names the file", "is not there", view["why"])
check_eq("F3 no table -> unknown", C.register_fence_view(reg("a.md", "# nothing\n"))["state"], "unknown")
check_in("F3 no table says so", "no table", C.register_fence_view(reg("a2.md", "# nothing\n"))["why"])
changes = C.register_fence_view(reg("b.md", "## Register changes\n\n| R | x |\n|---|---|\n| R-1 | y |\n"))
check_eq("F3 first heading '## Register changes' -> unknown", changes["state"], "unknown")
check_in("F3 names the heading it would read", "## Register changes", changes["why"])
check_eq("F3 header only -> empty", C.register_fence_view(reg("c.md", HEAD))["state"], "empty")
for bad in ("**R-9**", "R-9a", "r-9", "R–9"):
    got = C.register_fence_view(reg("d.md", HEAD + f"| R-1 | a | s | d |\n| {bad} | b | s | d |\n"))
    check_eq(f"F3 a row without an R-n id ({bad!r}) -> unknown", got["state"], "unknown")
good = C.register_fence_view(reg("e.md", HEAD + "| R-1 | a | s | d |\n| R-1 | repeat | s | d |\n| R-2 | b | s | d |\n"))
check_eq("F3 readable, a repeated id is no error", (good["state"], good["ids"]), ("rows", ["R-1", "R-2"]))


# --- F4: the detector ---------------------------------------------------------------------------------
def story(register=None, plan_rows=None, md_ids=("R-9",), name="S"):
    root = tmp / name
    (root / "work").mkdir(parents=True, exist_ok=True)
    if register is not None:
        (root / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
    if plan_rows is not None:
        (root / "work" / "test-plan.json").write_text(json.dumps({"rows": plan_rows}), encoding="utf-8")
    if md_ids is not None:
        cells = "".join(f"| TS-{i + 1} | {r} | x | automate | y | z | w | v | u |\n" for i, r in enumerate(md_ids))
        (root / "test-plan.md").write_text("## Plan\n\n| TS | R | observable | disposition + reason | level | fit | a | b | c |\n"
                                           "|---|---|---|---|---|---|---|---|---|\n" + cells, encoding="utf-8")
    return root


def run(root):
    saved = PC.detector_story
    PC.detector_story = lambda *a, **k: root
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = PC.detector_main(root)
    finally:
        PC.detector_story = saved
    return code, out.getvalue()


code, text = run(story(HEAD + "| R-9 | a | s | d |\n", [row("TS-1", "skip", reqs=("R-1",))], md_ids=("R-1",), name="s1"))
check("F4 R-9 without a row is refused", code == 1 and "R-9: this requirement of the register has no row in the test plan" in text, text)
check_in("F4 the text says a not_planned entry does not stand in for a row", "`not_planned` entry does not stand in for a row", text)
check_in("F4 the summary line counts it", "1 requirement(s) without a row", text)
check_not_in("F4 a known REJECT never prints beside UNREADABLE", "UNREADABLE", text)
code, text = run(story(HEAD + "| R-9 | a | s | d |\n", [row()], md_ids=None, name="s2"))
check_not_in("F4 plan names R-9, there is no test-plan.md: no plan-side refusal either", "has no row in the test plan", text)
check_not_in("F4 no test-plan.md: no md refusal (the exit's required_outputs refuses the file)", "not in the `R` column", text)
code, text = run(story(HEAD + "| R-9 | a | s | d |\n", [row()], md_ids=("R-1",), name="s3"))
check_in("F4 JSON names R-9 and md does not: the md refusal", "R-9: this requirement of the register is named in work/test-plan.json but not in the `R` column", text)
code, text = run(story(None, [row()], name="s4"))
check("F4 no register: UNREADABLE, never OK (or a REJECT of the old checks, without UNREADABLE)",
      ("UNREADABLE" in text and "OK:" not in text) or ("REJECT" in text and "UNREADABLE" not in text), text)
code, text = run(story(HEAD + "| R-9 | a | s | d |\n", [row("TS-1", "skip", reqs=("R-9",), risk_source_refs=5, reason="x")], name="s5"))
check_not_in("F4 a row with junk risk_source_refs does not break the detector", "could not complete", text)

# with the plan's own checks clean, the fence alone decides: unknown is UNREADABLE (exit 3) and never OK; empty says so and passes
saved_plan_errors = PC.gate_plan_errors
PC.gate_plan_errors = lambda *a, **k: []
code, text = run(story(None, [row()], name="c1"))
check("F4 clean plan, no register: UNREADABLE, exit 3, no OK", code == 3 and "UNREADABLE:" in text and "OK:" not in text, f"{code} {text}")
code, text = run(story(HEAD, [row()], name="c2"))
check("F4 clean plan, empty register: 'nothing to fence' then OK", code == 0 and "register lists no requirement: nothing to fence" in text and "OK:" in text, f"{code} {text}")
code, text = run(story(HEAD + "| R-9 | a | s | d |\n", [row()], name="c3"))
check("F4 clean plan, a covered register: OK, exit 0", code == 0 and "OK:" in text, f"{code} {text}")
code, text = run(story(HEAD + "| R-9 | a | s | d |\n| R-8 | a | s | d |\n", [row()], name="c4"))
check("F4 clean plan, one id uncovered: REJECT names it, exit 1, no UNREADABLE", code == 1 and "R-8: this requirement" in text and "UNREADABLE" not in text, f"{code} {text}")
PC.gate_plan_errors = saved_plan_errors

# a fence that raises is `unknown` and the old REJECT stays reachable
saved_view = C.register_fence_view
C.register_fence_view = lambda path: (_ for _ in ()).throw(RuntimeError("boom"))
code, text = run(story(HEAD + "| R-9 | a | s | d |\n", [{"id": "TS-1"}], name="s6"))
C.register_fence_view = saved_view
check("F4 the fence raises AND the plan has a known REJECT: the REJECT prints, no UNREADABLE line", "REJECT" in text and "UNREADABLE" not in text, text)
check_eq("F4 register_fence never raises: a story that is no folder is unknown", PC.register_fence(tmp / "nowhere", [row()])["state"], "unknown")

# window 1 reads nothing
import exit_gate as EG  # noqa: E402
saved_w = EG._s3_window_one
EG._s3_window_one = lambda art: True
fence = PC.register_fence(story(HEAD + "| R-9 | a | s | d |\n", [], name="s8"), [])
EG._s3_window_one = saved_w
check_eq("F4 window 1 of S3: no fence, no block", (fence["state"], fence["missing"]), ("window_one", []))
check_in("F4 window 1 says it was not read", "not read in window 1", fence["why"])
check_eq("F4 window 2 (or no controller) always fences", PC.register_fence(story(HEAD + "| R-9 | a | s | d |\n", [], name="s9"), [])["missing"],
         [{"id": "R-9", "where": "plan"}])

# --- F5: A6 -------------------------------------------------------------------------------------------
q = question()
waiting = PC.requirements_waiting_without_branch([row("TS-1", "unverifiable")], [q], ["R-9"])
check_eq("F5 an open question naming R-9, an unverifiable row with no branch: refused", waiting, [{"id": "R-9", "question": "Q2"}])
check_eq("F5 {a:{}, b:{}, not_needed:{}} is no executor",
         PC.requirements_waiting_without_branch([row("TS-1", "unverifiable", if_answered={"Q2": {"a": {}, "b": {}, "not_needed": {}}})], [q], ["R-9"]),
         [{"id": "R-9", "question": "Q2"}])
check_eq("F5 a non-empty patch for a reading is the executor",
         PC.requirements_waiting_without_branch([row("TS-1", "unverifiable", if_answered={"Q2": {"a": {"disposition": "automate"}}})], [q], ["R-9"]), [])
check_eq("F5 only not_needed non-empty: still no executor",
         PC.requirements_waiting_without_branch([row("TS-1", "unverifiable", if_answered={"Q2": {"not_needed": {"disposition": "skip"}}})], [q], ["R-9"]),
         [{"id": "R-9", "question": "Q2"}])
check_eq("F5 an automate row of R-9 is a row the case can follow: not this refusal",
         PC.requirements_waiting_without_branch([row("TS-1", "automate")], [q], ["R-9"]), [])
check_eq("F5 R-9 inside R-90 is no token", PC.requirements_waiting_without_branch([row("TS-1", "unverifiable")], [question(text="Is R-90 in scope?")], ["R-9"]), [])
check_eq("F5 a settled question waits for nothing",
         PC.requirements_waiting_without_branch([row("TS-1", "unverifiable")], [question(status="not_needed")], ["R-9"]), [])

PLAN_Q = [row("TS-1", "skip", question_refs=["Q1"], if_answered={"Q1": {"a": {"disposition": "skip"}}})]
found = PC.variant_errors(PLAN_Q, [question("Q1", "Unrelated?"), question("Q2", "Is R-9 in scope?")])
check("F5 no_row_for_question: an open question naming R-9 that no row or case answers",
      [f["where"] for f in found if f["kind"] == "no_row_for_question"] == ["Q2"], str(found))
found = PC.variant_errors(PLAN_Q, [question("Q1", "Unrelated?"), question("Q2", "Is the stand up?")])
check_eq("F5 a question with no register id is not examined", [f for f in found if f["kind"] == "no_row_for_question"], [])
found = PC.variant_errors(PLAN_Q, [question("Q1", "Unrelated?"), question("Q2", "Is R-9 in scope?")],
                          [{"case": "TC-1", "readable": True, "question_thens": json.dumps([{"question": "Q2", "then": 1, "readings": {"a": "x", "b": "y"}}]),
                            "thens": [1]}])
check_eq("F5 a case with question_thens on it is an executor", [f for f in found if f["kind"] == "no_row_for_question"], [])
found = PC.variant_errors([row("TS-1", "skip")], [question("Q2", "Is R-9 in scope?")])
check_eq("F5 an old story with no branch field and a pre-contract plan: nothing", found, [])

# --- F6: A7 -------------------------------------------------------------------------------------------
BRANCHED = row("TS-13", "unverifiable", reqs=("R-13",), question_refs=["Q3"], reason="waits for Q3",
               if_answered={"Q3": {"a": {"disposition": "automate", "level": "api"}, "b": {"disposition": "skip"},
                                   "not_needed": {"disposition": "skip"}}})
Q3 = question("Q3", "Is R-13 a bug?")
found = PC.variant_errors([BRANCHED], [Q3], [], at_cases_stage=True)
owes = [f for f in found if f["kind"] == "row_owes_case"]
check("F6 S4 rehearsal, no case for the row: row_owes_case", len(owes) == 1 and owes[0]["where"] == "TS-13" and owes[0]["owner"] == "designer", str(found))
check_in("F6 the text names the row, the question and the reading", "TS-13: the row is `unverifiable` and Q3 = a makes it `automate`", owes[0]["message"])
check_eq("F6 S3 exit (at_cases_stage False): silent", [f for f in PC.variant_errors([BRANCHED], [Q3], []) if f["kind"] == "row_owes_case"], [])
check_eq("F6 a case with Plan row: TS-13 closes it",
         [f for f in PC.variant_errors([BRANCHED], [Q3], [{"case": "TC-1", "readable": True, "question_thens": None, "thens": [], "plan_row": "TS-13"}],
                                       at_cases_stage=True) if f["kind"] == "row_owes_case"], [])
check_in("F9 F-7 the row_owes_case text ends with the person's word (A7)", "no road back to S4 for a row id. A person's word passes this", owes[0]["message"])
check_eq("F6 0 cases at S4 is NOT silence", len([f for f in PC.variant_errors([BRANCHED], [Q3], [], at_cases_stage=True) if f["kind"] == "row_owes_case"]), 1)
SKIP_ONLY = row("TS-14", "unverifiable", reqs=("R-14",), question_refs=["Q3"],
                if_answered={"Q3": {"a": {"disposition": "skip"}, "b": {"disposition": "skip"}, "not_needed": {"disposition": "skip"}}})
check_eq("F6 no reading brings a case: no finding", [f for f in PC.variant_errors([SKIP_ONLY], [Q3], [], at_cases_stage=True) if f["kind"] == "row_owes_case"], [])
NOLEVEL = row("TS-15", "unverifiable", reqs=("R-15",), question_refs=["Q3"],
              if_answered={"Q3": {"a": {"disposition": "automate"}, "b": {"disposition": "skip"}, "not_needed": {"disposition": "skip"}}})
lev = [f for f in PC.variant_errors([NOLEVEL], [Q3], []) if f["kind"] == "missing_branch" and "level" in f.get("lacking", "")]
check("F6 a branch that makes the row automate without a level: missing_branch, lacking `level` for a", len(lev) == 1 and lev[0]["lacking"] == "`level` for a", str(lev))
check_eq("F6 the branch with a level is clean", [f for f in PC.variant_errors([BRANCHED], [Q3], []) if "level" in f.get("lacking", "")], [])

# --- F6b: the obligations a case quotes (A7) ---------------------------------------------------------------
OBQ = question("Q5", "Does R-9 hold for the export?", "open")


def obligation_rows(patch_obligations):
    patch = {"disposition": "automate", "level": "api"}
    if patch_obligations is not None:
        patch["coverage_obligations"] = patch_obligations
    return [row("TS-20", "unverifiable", reqs=("R-9",), question_refs=["Q5"], coverage_obligations=[{"obligation_id": "OB-1"}],
                if_answered={"Q5": {"a": patch, "b": {"disposition": "skip"}, "not_needed": {"disposition": "skip"}}})]


OBCASE = [{"case": "TC-1", "readable": True, "question_thens": None, "thens": [], "plan_row": "TS-20", "text": "Obligation: OB-1. covers it"}]


def drops(rows, cases):
    return [f for f in PC.variant_errors(rows, [OBQ], cases, at_cases_stage=True) if f["kind"] == "bad_branch" and "drops obligation ids" in f["message"]]


found = drops(obligation_rows([{"obligation_id": "OB-2"}]), OBCASE)
check("F6b a patch that replaces the obligations and drops OB-1, which a case quotes: bad_branch naming it",
      len(found) == 1 and "OB-1" in found[0]["message"] and "Q5 = a" in found[0]["message"], str(found))
check_eq("F6b adding a new id and keeping OB-1 is fine (a subset, not equality)",
         drops(obligation_rows([{"obligation_id": "OB-1"}, {"obligation_id": "OB-2"}]), OBCASE), [])
check_eq("F6b a patch with no coverage_obligations leaves the row's own: fine", drops(obligation_rows(None), OBCASE), [])
check_eq("F6b no case of the row quotes OB-1: nothing to drop", drops(obligation_rows([{"obligation_id": "OB-2"}]),
         [dict(OBCASE[0], text="Obligation: OB-7")]), [])
check_eq("F6b at the S3 exit there are no cases: silent", drops(obligation_rows([{"obligation_id": "OB-2"}]), []), [])
check_eq("F6b OB-10 in the case text is not OB-1", drops(obligation_rows([{"obligation_id": "OB-2"}]),
         [dict(OBCASE[0], text="Obligation: OB-10")]), [])

# --- F8: A2 (a case set aside) and A3 (a row waiting for an open question) -----------------------------
import check_traceability as CT  # noqa: E402
import check_delivery as CD  # noqa: E402
import traceability as TR  # noqa: E402

PLAN_HEAD = ("---\ntask: T-1\n---\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | "
             "disposition + reason | fit | level | technique |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n")
QUESTION = {"id": "Q3", "question": "Is the export of R-9 in scope for this story at all?", "source_says": "", "severity": "major",
            "readings": [{"id": "a", "reading": "yes"}, {"id": "b", "reading": "no"}]}


def trace_story(name, disposition="skip", json_rows="default", answer=None, case=True, report=None, register=True, questions=True):
    """A story folder: R-9 -> TS-1 (`disposition`) -> TC-001 (if `case`); `answer` is the recorded reading of Q3 (None = no record)."""
    art = tmp / name / "qa-factory" / "artifacts" / "T-1"
    (art / "work" / "test-cases" / "a").mkdir(parents=True, exist_ok=True)
    if register:
        (art / "work" / "requirements-register.md").write_text(
            "---\ntask: T-1\n---\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref |\n|---|---|---|---|---|---|\n"
            "| R-9 | Nine | ac | - | yes | AC-9 |\n", encoding="utf-8")
    (art / "test-plan.md").write_text(
        PLAN_HEAD + f"| TS-1 | TS-1 what | R-9 | contract @ x | degraded | P2 | diff:a.py:1 | requirement:R-9 | `{disposition}` - reason | | | review |\n",
        encoding="utf-8")
    if json_rows == "default":
        json_rows = [{"id": "TS-1", "requirements": ["R-9"], "disposition": disposition, "reason": "waits", "question_refs": ["Q3"]}]
    if json_rows == "broken":
        (art / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")
    elif json_rows is not None:
        (art / "work" / "test-plan.json").write_text(json.dumps({"rows": json_rows}), encoding="utf-8")
    if questions:
        (art / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [QUESTION]}), encoding="utf-8")
    if answer:
        (art / "work" / "question-answers.jsonl").write_text(json.dumps(
            {"id": "Q3", "status": "answered", "reading": answer, "words": "Q3: " + answer, "where": "gate A", "at": "2026-10-30T10:00:00"}) + "\n",
            encoding="utf-8")
    if case:
        (art / "work" / "test-cases" / "a" / "TC-001.md").write_text(
            "---\nid: TC-001\ntitle: Case TC-001\narea: a\ntask: T-1\ncovers: [R-9]\nplan_row: TS-1\n---\nRequirements: R-9\nPlan row: TS-1\n\n## Then\n1. It happens.\n",
            encoding="utf-8")
    if report is not None:
        (art / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
    (art / "pipeline.json").write_text(json.dumps({"ticket": "T-1"}), encoding="utf-8")
    return art


def walked(art):
    return CT.walk(art, handed=frozenset())["rows"][0]


# A2: the unrun case of an excluded row is set aside, the row's decision speaks (answer b -> skip, the case stayed)
got = walked(trace_story("a2-b", answer="b"))
check_eq("A2 answer b: skip row + an unrun case -> deferred_by_decision, no case", (got["outcome"], got["cases"], got["gaps"]), ("deferred_by_decision", [], []))
got = walked(trace_story("a2-nocase", answer="b", case=False))
check_eq("A2 control: the same row with no case reads the same", (got["outcome"], got["cases"]), ("deferred_by_decision", []))
got = walked(trace_story("a2-auto", disposition="automate", answer="a"))
check_eq("A2 answer a -> automate, the test is not in the manifest: the honest chain break (not set aside)",
         (got["outcome"], got["cases"], got["gaps"]), ("", ["TC-001"], [{"case": "TC-001", "gap": "not_in_manifest"}]))
got = walked(trace_story("a2-ran", answer="b", report={"impossible": [{"case": "TC-001", "reason": "no stand"}]}))
check_eq("A2 a case that RAN (impossible in the run report) on a skip row is never hidden: read through the case",
         (got["outcome"], got["cases"]), ("impossible", ["TC-001"]))
RED = {"execution_status": "completed", "results": [{"instance_id": "t.py::test_x", "case": "TC-001", "status": "failed"}]}
red_art = trace_story("a2-red", answer="b", report=RED)
(red_art / "work" / "automation-manifest.json").write_text(json.dumps(
    {"tests": [{"file": "t.py", "test_function": "test_x", "covers": ["TC-001"]}]}), encoding="utf-8")
got = walked(red_art)
check_eq("A2 a skip row whose case ran RED is never hidden: executed_failed through the case", (got["outcome"], got["cases"]), ("executed_failed", ["TC-001"]))
row9 = next(r for r in TR.build(tmp / "a2-red" / "qa-factory", red_art)["rows"] if r["requirement"] == "R-9")
check_eq("A2 and the trace row reads through the case, not 'deferred'", (row9["case"], row9["result"] != "deferred"), ("TC-001", True))
CASE_NO_ROW = trace_story("a2-norow", answer="b")
case_path = CASE_NO_ROW / "work" / "test-cases" / "a" / "TC-001.md"
case_path.write_text(case_path.read_text(encoding="utf-8").replace("plan_row: TS-1\n", "").replace("Plan row: TS-1\n", ""), encoding="utf-8")
got = walked(CASE_NO_ROW)
check("A2 a case with no `Plan row:` is not set aside (it stays a case of the requirement)", got["cases"] == ["TC-001"], str(got))
check("A2 the set-aside predicate: an excluded row, never ran -> True; automate -> False; ran -> False",
      C.case_set_aside("TC-001", "skip", {}, {}) is True and C.case_set_aside("TC-001", "automate", {}, {}) is False
      and C.case_set_aside("TC-001", "skip", {}, {"impossible": [{"case": "TC-001"}]}) is False)

# A3: an excluded row that rests on an OPEN question is not a decision
got = walked(trace_story("a3-open", case=False))
check_eq("A3 open question, no case: outcome empty and the question_open gap", (got["outcome"], got["gaps"]),
         ("", [{"case": "", "gap": "question_open", "question": "Q3"}]))
check_in("A3 the detail names the question", "Q3", got["detail"])
got = walked(trace_story("a3-open-case", case=True))
check_eq("A3 open question and an unrun case on the skip row: the case is set aside, the gap stays",
         (got["outcome"], got["gaps"]), ("", [{"case": "", "gap": "question_open", "question": "Q3"}]))
got = walked(trace_story("a3-unver", disposition="unverifiable", case=False))
check_eq("A3 `unverifiable` rests on the open question too", got["gaps"], [{"case": "", "gap": "question_open", "question": "Q3"}])
got = walked(trace_story("a3-b", answer="b", case=False))
check_eq("A3 answered b: a decision, as it was", (got["outcome"], got["gaps"]), ("deferred_by_decision", []))
got = walked(trace_story("a3-nojson", json_rows=None, case=False))
check_eq("A3 no work/test-plan.json (an older story): as it was", (got["outcome"], got["gaps"]), ("deferred_by_decision", []))
got = walked(trace_story("a3-broken", json_rows="broken", case=False))
check_eq("A3 the JSON present and unreadable: the same gap with no question (unknown is no pass)",
         (got["outcome"], got["gaps"]), ("", [{"case": "", "gap": "question_open", "question": ""}]))
check_in("A3 and the detail says it was not read", "could not be read", got["detail"])
got = walked(trace_story("a3-noid", json_rows=[{"id": "TS-7", "disposition": "skip", "question_refs": ["Q3"]}], case=False))
check_eq("A3 the JSON has no row of that id: as it was", got["outcome"], "deferred_by_decision")
got = walked(trace_story("a3-noq", json_rows=[{"id": "TS-1", "requirements": ["R-9"], "disposition": "skip", "reason": "nothing to say"}], case=False))
check_eq("A3 a row that names no question: the strategist's decision, as it was", got["outcome"], "deferred_by_decision")
got = walked(trace_story("a3-reason", json_rows=[{"id": "TS-1", "requirements": ["R-9"], "disposition": "skip", "reason": "per Q3 (a): later"}], case=False))
check_eq("A3 a whole token of `reason` counts", got["gaps"], [{"case": "", "gap": "question_open", "question": "Q3"}])
got = walked(trace_story("a3-q30", json_rows=[{"id": "TS-1", "requirements": ["R-9"], "disposition": "skip", "reason": "per Q30 only"}], case=False))
check_eq("A3 Q30 is not Q3", got["outcome"], "deferred_by_decision")
got = walked(trace_story("a3-keys", json_rows=[{"id": "TS-1", "requirements": ["R-9"], "disposition": "skip",
                                                "if_answered": {"Q3": {"a": {"disposition": "automate"}}}}], case=False))
check_eq("A3 a key of if_answered counts", got["gaps"], [{"case": "", "gap": "question_open", "question": "Q3"}])
check_eq("A3 row_open_questions: unknown ids are not returned, junk reads as nothing",
         (PC.row_open_questions({"question_refs": ["Q99", "Q3"]}, [QUESTION]), PC.row_open_questions("x", [QUESTION]),
          PC.row_open_questions({"question_refs": 5, "if_answered": 3, "reason": None}, [QUESTION]), PC.row_open_questions({"question_refs": ["Q3"]}, None)),
         (["Q3"], [], [], []))

# A3: the delivery verdict and the trace
art = trace_story("a3-deliv", case=False)
records = [r for r in CD.traceability_records(art) if r.get("gap") == "question_open"]
check_eq("A3 delivery: one record of the unconfirmed-expectation kind, keyed by R-9, no case",
         [(r["kind"], r["case"], r["ref"], r["requirements"]) for r in records], [("unconfirmed_expectation", "", "R-9", ["R-9"])])
check("A3 delivery: to_check names the question, the requirement and the question's text",
      bool(records) and records[0]["to_check"].startswith("answer Q3 (R-9): Is the export of R-9"), str(records))
items = CD.build_left_items(records, CD.gather(art))
check("A3 Left with you holds R-9 and keeps the record's to_check (not 'was not recorded')",
      len(items) == 1 and items[0]["ref"] == "R-9" and items[0]["to_check"].startswith("answer Q3 (R-9)"), str(items))
art = trace_story("a3-deliv-b", answer="b", case=False)
check_eq("A3 delivery: the question settled with b -> no record of the gap",
         [r for r in CD.traceability_records(art) if r.get("gap") == "question_open"], [])
art = trace_story("a3-deliv-broken", json_rows="broken", case=False)
records = [r for r in CD.traceability_records(art) if r.get("gap") == "question_open"]
check_eq("A3 delivery: unreadable plan -> the record says it could not be read",
         [r["to_check"] for r in records], ["the plan or its questions could not be read for R-9"])
art = trace_story("a3-trace", case=False)
row9 = next(r for r in TR.build(tmp / "a3-trace" / "qa-factory", art)["rows"] if r["requirement"] == "R-9")
check_eq("A3 trace: an open question reads wait", row9["result"], "wait")
check_in("A3 trace: with the same words as an unconfirmed claim", "expectation unconfirmed, check not executed", row9["basis"])
art = trace_story("a3-trace-b", answer="b", case=False)
row9 = next(r for r in TR.build(tmp / "a3-trace-b" / "qa-factory", art)["rows"] if r["requirement"] == "R-9")
check_eq("A3 trace: settled with b -> deferred, as it was", row9["result"], "deferred")
art = trace_story("a3-trace-un", disposition="unverifiable", answer="b", case=False)
row9 = next(r for r in TR.build(tmp / "a3-trace-un" / "qa-factory", art)["rows"] if r["requirement"] == "R-9")
check_eq("A3 trace: unverifiable + settled -> not planned (the old pin)", row9["result"], "not planned")
art = trace_story("a2-trace", answer="b", case=True)
check_eq("A2 --check is green: a set-aside case is deliberately in no row", TR.check(tmp / "a2-trace" / "qa-factory", art), [])
row9 = next(r for r in TR.build(tmp / "a2-trace" / "qa-factory", art)["rows"] if r["requirement"] == "R-9")
check_eq("A2 trace: the unrun case on a skip row is not the row of the requirement: deferred, no case", (row9["result"], row9["case"]), ("deferred", ""))

# --- F9: the fix round of the diff critic (t-604, t-605: F-1 .. F-7) ---------------------------------------------
import report_facts as RF  # noqa: E402
import gate_brief  # noqa: E402
import delivery_verdict as DV  # noqa: E402

# F-1: an open question is no decision of the plan: the row waits and is never filed under "approved at gate A"
PLAN_SKIP = [{"ts": "TS-1", "requirements": ["R-9"], "disposition": "skip", "reason": "waits for Q3"}]
check_in("F9 F-1 control: a skip row with a reason and no open question is the plan's decision",
         "skipped by the plan", RF._plan_decision({"id": "R-9", "results": ["deferred"]}, PLAN_SKIP, {}))
check_eq("F9 F-1 a requirement whose trace row WAITS (an open question) is never the plan's decision",
         RF._plan_decision({"id": "R-9", "results": ["wait"]}, PLAN_SKIP, {}), "")
check_eq("F9 F-1 ...not even with a gate A waiver of another kind of row beside it (wait is read first)",
         RF._plan_decision({"id": "R-9", "results": ["wait", "deferred"]}, PLAN_SKIP, {}), "")

# F-2: a run case is never hidden: the bare id and the `area/id` spelling both count
RED_BARE = {"results": [{"case": "TC-001", "status": "failed", "instance_id": "t.py::test_x"}]}
check_eq("F9 F-2 a red run row with the bare id: the area-keyed case is not set aside",
         C.case_set_aside("a/TC-001", "skip", {}, RED_BARE), False)
check_eq("F9 F-2 ...nor when the row spells the area (covers a/TC-001)",
         C.case_set_aside("a/TC-001", "skip", {}, {"results": [{"covers": ["a/TC-001"], "status": "failed", "instance_id": "t.py::test_y"}]}), False)
check_eq("F9 F-2 a manifest test linked by the bare id keeps the area-keyed case",
         C.case_set_aside("a/TC-001", "skip", {"tests": [{"file": "t.py", "test_function": "test_x", "covers": ["TC-001"]}]}, {}), False)
check_eq("F9 F-2 an impossible row with the bare id keeps it too",
         C.case_set_aside("a/TC-001", "skip", {}, {"impossible": [{"case": "TC-001", "reason": "no stand"}]}), False)
check_eq("F9 F-2 control: nothing ran, nothing links it: set aside", C.case_set_aside("a/TC-001", "skip", {}, {}), True)
check_eq("F9 F-2 control: another case's result does not keep it", C.case_set_aside("a/TC-001", "skip", {}, {"impossible": [{"case": "TC-002"}]}), True)

# F-3: the card line "no row or case changes with this answer" where no row and no case speaks about the question
Q_CARD = {"id": "Q3", "question": "Is the export of R-9 in scope?", "severity": "major", "owner_role": "strategist",
          "readings": [{"reading": "in", "from": "description"}, {"reading": "out", "from": "description"}]}
NO_CHANGE = "no row or case changes with this answer"
check_in("F9 F-3 a question that names R-9 and has no row and no case: the line is printed",
         NO_CHANGE, "\n".join(gate_brief.question_card(Q_CARD, 1, {})))
check_in("F9 F-3 ...also when the story has no effects at all (None)", NO_CHANGE, "\n".join(gate_brief.question_card(Q_CARD, 1)))
check_not_in("F9 F-3 a question whose letters already said 'nothing changes' does not say it a third time",
             NO_CHANGE, "\n".join(gate_brief.question_card(Q_CARD, 1, {"Q3": {"a": [], "b": [], "not_needed": []}})))
check_not_in("F9 F-3 a question with no R-n token gets no line (A6: one INFO line elsewhere, not a card line)",
             NO_CHANGE, "\n".join(gate_brief.question_card(dict(Q_CARD, question="Is the export in scope?"), 1, {})))
check_not_in("F9 F-3 R-90 is not R-9 and `R-` alone is no id", NO_CHANGE, "\n".join(gate_brief.question_card(dict(Q_CARD, question="Is R- in scope?"), 1, {})))

# F-4: the refusal's second door is one the receiver can use
shown = "\n".join(line for _head, lines in PC.fence_lines({"missing": [], "candidates": [], "waiting": [{"id": "R-9", "question": "Q3"}]}) for line in lines)
check_in("F9 F-4 the door is a person's word (the waiver line below)", "a person's word: the waiver line below", shown)
check_not_in("F9 F-4 'settle the row as skip' is gone (a skip row is refused too)", "settle the row as", shown)
check_eq("F9 F-4 the premise: a skip row with a reason and an open Q3 naming R-9 IS still refused",
         PC.requirements_waiting_without_branch([row("TS-1", "skip", reqs=("R-9",), reason="no answer brings it back")],
                                                [question("Q3", "Is R-9 in scope?")], ["R-9"]), [{"id": "R-9", "question": "Q3"}])

# F-5, F-6: the trace table with a person's word, and with a plan that could not be read
art = trace_story("f9-waiver", case=False)
(art / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "gate_waivers": [{"gate": "A", "requirement": "R-9", "decision": "the export is out"}]}),
                                   encoding="utf-8")
row9 = next(r for r in TR.build(tmp / "f9-waiver" / "qa-factory", art)["rows"] if r["requirement"] == "R-9")
check_eq("F9 F-5 a gate A waiver of R-9 closes the walk, so the table does not say wait", row9["result"], "deferred")
check_eq("F9 F-5 ...and the walk agrees", walked(art)["outcome"], "deferred_by_decision")
art = trace_story("f9-broken", json_rows="broken", case=False)
row9 = next(r for r in TR.build(tmp / "f9-broken" / "qa-factory", art)["rows"] if r["requirement"] == "R-9")
check_eq("F9 F-6 an unreadable plan still waits (unknown is no pass)", row9["result"], "wait")
check_in("F9 F-6 ...and the basis says it could not be read, as the walk and the delivery do", "could not be read for R-9", row9["basis"])
check_not_in("F9 F-6 ...and not 'no question is named for it'", "no question is named", row9["basis"])


# F-7: two rows of one requirement (A2): only the skip row's case is dropped; the delivery verdict after each answer
def two_rows(name, answer):
    art = trace_story(name, answer=answer, case=False, json_rows=[
        {"id": "TS-1", "requirements": ["R-9"], "disposition": "skip", "reason": "waits", "question_refs": ["Q3"]},
        {"id": "TS-2", "requirements": ["R-9"], "disposition": "automate", "reason": "the main path"}])
    for case_id, plan_row in (("TC-001", "TS-2"), ("TC-002", "TS-1")):
        (art / "work" / "test-cases" / "a" / f"{case_id}.md").write_text(
            f"---\nid: {case_id}\ntitle: Case {case_id}\narea: a\ntask: T-1\ncovers: [R-9]\nplan_row: {plan_row}\n---\n"
            f"Requirements: R-9\nPlan row: {plan_row}\n\n## Then\n1. It happens.\n", encoding="utf-8")
    return art


got = walked(two_rows("f9-two", "b"))
check_eq("F9 F-7 two rows: only the automate row's case stays, the skip row's unrun case is set aside; the test is not written yet",
         (got["cases"], got["gaps"]), (["TC-001"], [{"case": "TC-001", "gap": "not_in_manifest"}]))
kinds_a = {r["kind"] for r in CD.traceability_records(two_rows("f9-two-a", "a"))}
check_eq("F9 F-7 DV.decide after `a` with no test: no (the chain is broken, honestly)", DV.decide(kinds_a)[0], "no")
art = trace_story("f9-b", answer="b", case=False)
check_eq("F9 F-7 DV.decide after `b` (the row is skip, the person decided): yes", DV.decide({r["kind"] for r in CD.traceability_records(art)})[0], "yes")

# --- F10: the minimal run of the critic (question 4): a row `unverifiable` with branches and a case reaches S5 after `Q3: a` ---
import gate_preflight  # noqa: E402
from controller import Controller  # noqa: E402
from harness import cleanup, mark_project, temp_dir  # noqa: E402

run_root = temp_dir("f10-minimal-run-")
try:
    mark_project(run_root)
    ctrl = Controller(run_root)
    ctrl.apply("initialize", {"scope": ["TC-001"], "source_revision": "src-1", "known_paths": {"root": str(run_root)}, "idempotency_key": "init"})
    work = run_root / "work"
    work.mkdir(exist_ok=True)
    plan_row = {"id": "TS-1", "requirements": ["R-9"], "disposition": "unverifiable", "reason": "waits for Q3", "question_refs": ["Q3"],
                "if_answered": {"Q3": {"a": {"disposition": "automate", "level": "api", "reason": "in scope"}, "b": {"disposition": "skip", "reason": "out of scope"},
                                    "not_needed": {"disposition": "skip", "reason": "not needed"}}}}
    (work / "test-plan.json").write_text(json.dumps({"rows": [plan_row]}), encoding="utf-8")
    (work / "requirements-readiness.json").write_text(json.dumps({"verdict": "blocked", "open_questions": [
        {"id": "Q3", "question": "Is the export of R-9 in scope for this story at all?", "severity": "major",
         "readings": [{"reading": "yes", "from": "description", "if_chosen": "x"}, {"reading": "no", "from": "description", "if_chosen": "x"}]}]}),
        encoding="utf-8")
    (work / "test-cases" / "a").mkdir(parents=True, exist_ok=True)
    (work / "test-cases" / "a" / "TC-001.md").write_text(
        "---\nid: TC-001\ntitle: Case TC-001\narea: a\ntask: T-1\ncovers: [R-9]\nplan_row: TS-1\n---\nRequirements: R-9\nPlan row: TS-1\n\n## Then\n1. It happens.\n",
        encoding="utf-8")
    rehearsal = gate_preflight.Rehearsal(run_root, "A")
    rehearsal.check_question_branches()
    check_eq("F10 the rehearsal's question-branch check is clean on the row with branches",
             [f for f in rehearsal.findings if f["check"] == "question_branches"], [])
    PC.apply_gate_answers(run_root, "Q3: a")
    check_in("F10 after `Q3: a` the case of the row, now automate, is in the scope of S5", "TC-001", ctrl.stage_scope("S5")["scope"])
finally:
    cleanup(run_root)

finish("test_planning_contract_not_planned")
