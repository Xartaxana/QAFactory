#!/usr/bin/env python3
"""TQ1-27: the S4 case critic answers duplicates and level; a merge travels to S5 as a concern; the S4 exit holds the structure by code.

Keys (spec docs/tasks/specs/t-723-tq1-27-amended.md section 4, amended by the plan review t-736): K0 `_case_records` (`covers`, `status`) on
the adversarial inputs and the five owed pairs of the 12586 fixture; K1 an owed pair and the clean cases; K2 the form of the NEWEST round;
K3 / K3b which pairs a row answers, the truncation AT and BEYOND `refusal_units_shown`; K4 a merged case needs the concern (and the
no-`verdict`-column branch, B-2 of the review); K5 older rounds; K6 the level line; K7 a project case-id form; K8 `plan_case_budget` and
the `Over the plan case budget:` line; K8b the brief line; K9 the exit (`detector_main`) and the person's word; K-CAL the 12586 round;
(K-DOC, the charter and card phrases, moved to design/role-rules.json.)

K-CAL pins that the code CARRIES and HOLDS the three calibration merges when the critic writes them; it does not find them - the three
share no requirement, and what makes them one form is judgment (FR-12); their finding is the live run (FR-33).

Mutations (named, NOT run by the builder; each killed by this file):
  M1  merge_candidate_errors returns before _owed_pair_errors            -> K1
  M2  covers(a) & covers(b) read as `|`                                  -> K1 (two cases sharing nothing, clean)
  M3  an `approve` accepted as a carried merge                           -> K4
  M4  a pair answered only by a two-id row                               -> K3
  M5  the budget compared with `>=` for `>`                              -> K8 (count == n)
  M6  the `Archived` filter dropped                                      -> K8 (3 cases, one Archived)
  M7  the KEEP_GROUNDS check dropped                                     -> K2
  M8  only the newest round consulted for answers                        -> K5
  M9  the level order check removed                                      -> K6
  M10 the partner-id check after the token removed                       -> K4
  M11 the truncation tail line dropped                                   -> K3b
  M12 the no-`verdict`-column branch of the concern check removed        -> K4 (B-2)
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import branch_accounting as BA  # noqa: E402
import brief_pack as BP  # noqa: E402
import contract as C  # noqa: E402
import critic_rollcall as CR  # noqa: E402
import detector_verdict as DV  # noqa: E402
import planning_contract  # noqa: E402
import waiver  # noqa: E402

TOKEN = "parametrise into one test:"
FIX = FIXTURES / "run-12586-red-then" / "controller" / "TP1-12586"
MERGES_HEADING = "Merge candidates"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def case_text(cid: str, covers: str = "R-1", status: str = "Draft", plan_row: str = "TS-1") -> str:
    return (f"---\nid: {cid}\ntitle: t\narea: area\nstatus: {status}\ncovers: [{covers}]\nplan_row: {plan_row}\ntask: QA-1\n---\n"
            f"Requirements: {covers}\n\n## Given\n- a stand.\n\n## When\n1. act.\n\n## Then\n1. seen.\n")


def story(root: Path, cases: dict, plan=None, ticket: str = "QA-1") -> Path:
    """`cases`: {id: (covers, status)}. `plan`: a dict/list (JSON) or raw text for work/test-plan.json, None for no plan."""
    task = root / "qa-factory" / "artifacts" / ticket
    for cid, (covers, status) in cases.items():
        write(task / "work" / "test-cases" / "area" / f"{cid}.md", case_text(cid, covers, status))
    if plan is not None:
        write(task / "work" / "test-plan.json", plan if isinstance(plan, str) else json.dumps(plan))
    return task


def findings(task: Path, *rounds: str, area: str = "area") -> Path:
    """Write the rounds (NEWEST FIRST, as they are prepended) into one findings file."""
    path = task / "work" / "test-cases" / area / "critic-findings.md"
    write(path, "\n".join(rounds))
    return path


def row(plan_row: str, case: str, verdict="approve_with_concerns", note: str = "", reviewed: str = "yes") -> dict:
    return {"plan_row": plan_row, "case": case, "reviewed": reviewed, "verdict": verdict, "note": note}


def round_text(n: int = 1, verdict: str = "approve_with_concerns", roll=(), merges=None, extra=(),
               cols=("plan_row", "case", "reviewed", "verdict", "note")) -> str:
    out = [f"# Critic findings round {n}", "", f"Verdict: {verdict}", ""]
    if roll:
        out += ["## Roll-call", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in roll]
        out.append("")
    if merges is not None:
        out += ["## Merge candidates", "", "| cases | verdict | reason |", "|---|---|---|"]
        out += [f"| {a} | {b} | {c} |" for a, b, c in merges]
        out.append("")
    return "\n".join(out + list(extra)) + "\n"


def errors_of(task: Path, files=None) -> list:
    return CR.merge_candidate_errors(task, files)[0]


def about(errors, *needles) -> list:
    return [e for e in errors if all(n in e for n in needles)]


def carried(*ids) -> str:
    return f"{TOKEN} {', '.join(ids)}"


# --- K0 ----------------------------------------------------------------------------------------------------

def k0_records() -> None:
    root = temp_project("qa-merges-k0-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        cases = task / "work" / "test-cases" / "area"
        head = "---\nid: {id}\ntitle: t\narea: area\n{status}covers: {covers}\nplan_row: TS-1\ntask: QA-1\n---\nbody\n{tail}"
        raw = {
            "TC-001": "﻿" + head.format(id="TC-001", status="status: Archived\n", covers="[R-1, R-2]", tail=""),
            "TC-002": head.format(id="TC-002", status='status: "Archived"\n', covers="[R-1]", tail=""),
            "TC-003": head.format(id="TC-003", status="status: archived\n", covers="[R-1]", tail=""),
            "TC-004": head.format(id="TC-004", status="status: Draft\n", covers="[R-1,R-2]", tail=""),
            "TC-005": head.format(id="TC-005", status="status: Draft\n", covers="[AC-1]", tail=""),
            "TC-006": head.format(id="TC-006", status="", covers="[R-1]", tail="status: Archived\n"),
        }
        for cid, text in raw.items():
            write(cases / f"{cid}.md", text)
        got = {r["id"]: r for r in BA._case_records(task)}
        check_eq("K0: a BOM before the front matter and `status: Archived` -> Archived, covers both R-ids",
                 (got["TC-001"]["status"], got["TC-001"]["covers"]), ("Archived", {"R-1", "R-2"}))
        check_eq("K0: `status: \"Archived\"` quoted is NOT the exact word (live)", got["TC-002"]["status"], '"Archived"')
        check_eq("K0: `status: archived` lower case is live", got["TC-003"]["status"], "archived")
        check_eq("K0: `covers: [R-1,R-2]` with no spaces", got["TC-004"]["covers"], {"R-1", "R-2"})
        check_eq("K0: `covers: [AC-1]` holds no requirement", got["TC-005"]["covers"], set())
        check_eq("K0: a `status:` line only in the body is no status", got["TC-006"]["status"], "")
        live = {c for c, r in got.items() if r["status"] != "Archived"}
        check_eq("K0: only the exact word retires a case from the pair check", live, {"TC-002", "TC-003", "TC-004", "TC-005", "TC-006"})
    finally:
        cleanup(root)

    root = temp_project("qa-merges-k0b-")
    try:
        task = root / "qa-factory" / "artifacts" / "TP1-12586"
        shutil.copytree(FIX, task)
        errors, _notes = CR.merge_candidate_errors(task, files=[])
        pairs = {(m.group(1), m.group(2), m.group(3)) for e in errors
                 for m in [re.search(r"`(TC-\d+)` and `(TC-\d+)` both cover (R-[\d, R-]+?) and no round", e)] if m}
        check_eq("K0: the 12586 fixture owes exactly the five pairs (none of them a calibration merge)", pairs,
                 {("TC-005", "TC-006", "R-11"), ("TC-005", "TC-014", "R-15"), ("TC-006", "TC-010", "R-8"),
                  ("TC-008", "TC-012", "R-4"), ("TC-011", "TC-012", "R-9")})
        check_eq("K0: ... and only those refusals", len(errors), 5)
    finally:
        cleanup(root)


# --- K1 ----------------------------------------------------------------------------------------------------

def k1_owed_pair() -> None:
    root = temp_project("qa-merges-k1-")
    try:
        task = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-1", "Draft"), "TC-003": ("R-2", "Draft")})
        roll = [row("TS-1", "TC-001"), row("TS-2", "TC-002"), row("TS-3", "TC-003", "approve", "")]
        findings(task, round_text(roll=roll))
        got = errors_of(task)
        check_eq("K1: no section, two cases share R-1 -> ONE refusal", len(got), 1)
        check("K1: ... it names both ids, `R-1` and `Merge candidates`",
              bool(about(got, "TC-001", "TC-002", "R-1", MERGES_HEADING)), str(got))
        check("K1: ... and the door: the row to write", bool(about(got, "| TC-001, TC-002 | merge or keep |")), str(got))
        findings(task, round_text(roll=roll, merges=[("TC-001, TC-002", "keep", "P16: one red line tells the branches apart")]))
        check_eq("K1: `keep | P16: ...` answers the pair -> clean", errors_of(task), [])
        # E1/E2: no shared requirement -> nothing owed, even with the same text in both cases (code never reads the Given/When)
        none = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-2", "Draft")}, ticket="QA-2")
        findings(none, round_text(roll=[row("TS-1", "TC-001"), row("TS-2", "TC-002")]))
        check_eq("K1: two cases sharing nothing, no section -> clean (E2)", errors_of(none), [])
        one = story(root, {"TC-001": ("R-1", "Draft")}, ticket="QA-3")
        findings(one, round_text(roll=[row("TS-1", "TC-001")]))
        check_eq("K1: one live case -> clean (E1)", errors_of(one), [])
        zero = story(root, {}, ticket="QA-4")
        findings(zero, round_text())
        check_eq("K1: no case at all -> clean (E1)", errors_of(zero), [])
    finally:
        cleanup(root)


# --- K2 ----------------------------------------------------------------------------------------------------

def k2_form() -> None:
    root = temp_project("qa-merges-k2-")
    try:
        cases = {f"TC-00{i}": (f"R-{i}", "Draft") for i in range(1, 8)}       # no shared requirement: only the form can refuse
        task = story(root, cases)
        bad = [("TC-001", "keep", "P16: x"), ("TC-001, TC-099", "keep", "P16: x"), ("TC-001, TC-002", "fold", "x"),
               ("TC-003, TC-004", "keep", "because"), ("TC-005, TC-006", "merge", ""),
               ("TC-001, TC-007", "merge", "same form"), ("TC-001, TC-007", "keep", "P16: x")]
        findings(task, round_text(merges=bad))
        other = task / "work" / "test-cases" / "other" / "critic-findings.md"
        write(other, "# Critic findings round 1\n\nVerdict: approve\n\n## Merge candidates\n\n| cases | verdict |\n|---|---|\n| TC-001, TC-002 | keep |\n")
        got = errors_of(task)
        check_eq("K2: seven defects (six rows of one file, a table with no `reason` column in another) -> seven refusals", len(got), 7)
        check("K2: ... every refusal names the section", all(MERGES_HEADING in e for e in got), str(got))
        for label, needles in (("one id", ("fewer than two",)), ("an unknown id", ("TC-099", "no case of this story")),
                               ("verdict `fold`", ("fold",)), ("`keep` with the reason `because`", ("P16", "P19")),
                               ("`merge` with no reason", ("merge", "no reason")), ("a pair answered twice", ("answered twice", "merge and keep")),
                               ("no `reason` column", ("no `reason` column", "| TC-a, TC-b | merge or keep |"))):
            check(f"K2: {label} is refused and named", bool(about(got, *needles)), str(got))
        # the same defects in an OLDER round are never form-checked (an old malformed row could never be mended)
        findings(task, round_text(2, merges=[]), round_text(1, merges=bad))
        write(other, "# Critic findings round 1\n\nVerdict: approve\n")
        check_eq("K2: the same defects in an older round -> none", errors_of(task), [])
    finally:
        cleanup(root)


# --- K3 / K3b ----------------------------------------------------------------------------------------------

def k3_pairs() -> None:
    root = temp_project("qa-merges-k3-")
    try:
        task = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-1", "Draft"), "TC-003": ("R-1", "Draft")})
        findings(task, round_text(merges=[("TC-001, TC-002, TC-003", "keep", "P19: another level")]))
        check_eq("K3: one row of three ids answers its three pairs", errors_of(task), [])
        findings(task, round_text(merges=[("TC-001, TC-002", "keep", "P16: x")]))
        got = errors_of(task)
        check_eq("K3: only A,B answered -> A/C and B/C are refused", sorted(re.findall(r"`(TC-\d+)` and `(TC-\d+)`", " ".join(got))),
                 [("TC-001", "TC-003"), ("TC-002", "TC-003")])
    finally:
        cleanup(root)


def k3b_truncation() -> None:
    lim = BA.limit("refusal_units_shown")
    cases = {f"TC-{i:03d}": ("R-1", "Draft") for i in range(1, 9)}        # 8 cases on R-1: 28 pairs
    ids = sorted(cases)
    all_pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
    check("K3b: the limit fits the fixture of 28 pairs", lim + 2 <= len(all_pairs), f"limit {lim}")
    root = temp_project("qa-merges-k3b-")
    try:
        task = story(root, cases)
        for owed in (lim, lim + 1, lim + 2):
            answered = all_pairs[:len(all_pairs) - owed]
            findings(task, round_text(merges=[(f"{a}, {b}", "keep", "P16: x") for a, b in answered]))
            got = errors_of(task)
            pair_lines = [e for e in got if "both cover" in e]
            tail = [e for e in got if "more pairs under" in e]
            if owed <= lim:
                check_eq(f"K3b: {owed} owed pairs (AT the limit {lim}) -> {owed} lines, no tail", (len(pair_lines), len(tail)), (owed, 0))
            else:
                check_eq(f"K3b: {owed} owed pairs (BEYOND the limit {lim}) -> {lim} lines + one tail", (len(pair_lines), len(tail)), (lim, 1))
                check("K3b: ... the tail holds the count and the section name",
                      bool(tail) and f"{owed} in all" in tail[0] and MERGES_HEADING in tail[0], str(tail))
    finally:
        cleanup(root)


# --- K4 / K5 -----------------------------------------------------------------------------------------------

def k4_concern() -> None:
    root = temp_project("qa-merges-k4-")
    try:
        task = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-2", "Draft"), "TC-003": ("R-3", "Draft")})
        merge = [("TC-001, TC-002", "merge", "one form")]
        both = carried("TC-001", "TC-002")

        def run(b, cols=("plan_row", "case", "reviewed", "verdict", "note"), verdict="approve_with_concerns", a=None):
            a = a or row("TS-1", "TC-001", note=both)
            findings(task, round_text(verdict=verdict, roll=[a, b], merges=merge, cols=cols))
            return errors_of(task)

        check_eq("K4: both cases `approve_with_concerns` with the token and the partner -> clean", run(row("TS-2", "TC-002", note=both)), [])
        got = run(row("TS-2", "TC-002", "approve"))
        check("K4: B `approve` -> refusal naming B, the token and the door", bool(about(got, "TC-002", "approve_with_concerns", TOKEN)), str(got))
        check_eq("K4: ... and only B", len(got), 1)
        # M3 (canon part 2, t-769): the token and the partner in the note do not make an `approve` row a carrier - only the verdict does
        got = run(row("TS-2", "TC-002", "approve", both))
        check_eq("K4: B `approve` WITH the token and the partner in the note -> still a refusal naming B (only `approve_with_concerns` carries)",
                 (len(got), bool(about(got, "TC-002", "approve_with_concerns", TOKEN))), (1, True))
        check("K4: B `approve_with_fixes` -> refusal", bool(about(run(row("TS-2", "TC-002", "approve_with_fixes", both)), "TC-002")))
        check("K4: B `approve_with_concerns` with no token -> refusal", bool(about(run(row("TS-2", "TC-002", note="a concern")), "TC-002")))
        check("K4: B's note names only B (the partner absent) -> refusal",
              bool(about(run(row("TS-2", "TC-002", note=carried("TC-002"))), "TC-002")))
        check_eq("K4: B `reject` -> no refusal from this check (E8: it is not approved)", run(row("TS-2", "TC-002", "reject", both)), [])
        check_eq("K4: the token in other case -> clean", run(row("TS-2", "TC-002", note="PARAMETRISE  INTO ONE TEST: TC-001, TC-002")), [])
        # B-2 of the plan review: no `verdict` column and an approving round word -> the merge would be lost silently
        no_col = ("plan_row", "case", "reviewed", "note")
        got = run(row("TS-2", "TC-002", note=both), cols=no_col, a=row("TS-1", "TC-001", note=both))
        check("K4: no `verdict` column + an approving round word -> refusal asking for the column",
              bool(about(got, "`verdict` column", "TC-001")) and bool(about(got, "`verdict` column", "TC-002")), str(got))
        check_eq("K4: no `verdict` column + a `reject` round word -> no refusal from this check",
                 run(row("TS-2", "TC-002", note=both), cols=no_col, a=row("TS-1", "TC-001", note=both), verdict="reject"), [])
        # E4: a merge row of three ids; one of three lacks a partner id
        three = [("TC-001, TC-002, TC-003", "merge", "one form")]
        allthree = carried("TC-001", "TC-002", "TC-003")
        findings(task, round_text(roll=[row("TS-1", "TC-001", note=allthree), row("TS-2", "TC-002", note=allthree),
                                        row("TS-3", "TC-003", note=carried("TC-001", "TC-003"))], merges=three))
        got = errors_of(task)
        check_eq("K4: a three-id merge, one note lacks a partner id -> one refusal, for that case", (len(got), bool(about(got, "TC-003"))), (1, True))
        findings(task, round_text(roll=[row("TS-1", "TC-001", note=allthree), row("TS-2", "TC-002", note=allthree),
                                        row("TS-3", "TC-003", note=allthree)], merges=three))
        check_eq("K4: ... each carries the two others -> clean", errors_of(task), [])
        # E23: the token with no merge row is no answer and is not read
        findings(task, round_text(roll=[row("TS-1", "TC-001", note=both), row("TS-2", "TC-002", "approve")]))
        check_eq("K4: the token with no merge row -> not read (no pair owed here)", errors_of(task), [])
    finally:
        cleanup(root)


def k5_older_rounds() -> None:
    root = temp_project("qa-merges-k5-")
    try:
        task = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-2", "Draft")})
        both = carried("TC-001", "TC-002")
        old = round_text(1, roll=[row("TS-1", "TC-001", note=both), row("TS-2", "TC-002", note=both)],
                         merges=[("TC-001, TC-002", "merge", "one form")])
        findings(task, round_text(2, "approve", roll=[row("TS-1", "TC-001", "approve")]), old)
        got = errors_of(task)
        check("K5: an older `merge`, the newest round lists only A as `approve` -> refusal for A", bool(about(got, "TC-001")), str(got))
        check_eq("K5: ... and none for B (the older round decides for it)", len(got), 1)
        findings(task, round_text(2, "approve", roll=[row("TS-3", "TC-003", "approve")]), old)
        check_eq("K5: the newest round lists neither -> clean (the older round decides)", errors_of(task), [])
        findings(task, round_text(2, "approve", roll=[row("TS-1", "TC-001", "approve")], merges=[("TC-001, TC-002", "keep", "P16: no")]), old)
        check_eq("K5: the newest round answers `keep | P16` -> clean (E6, it may change its mind in writing)", errors_of(task), [])
        arch = story(root, {"TC-001": ("R-1", "Archived"), "TC-002": ("R-2", "Draft")}, ticket="QA-2")
        findings(arch, round_text(2, "approve", roll=[row("TS-2", "TC-002", "approve")]), old)
        check_eq("K5: an Archived case in an OLDER merge row -> not form-checked", errors_of(arch), [])
        findings(arch, round_text(1, roll=[row("TS-2", "TC-002", note=both)], merges=[("TC-001, TC-002", "merge", "one form")]))
        got = errors_of(arch)
        check("K5: ... in the NEWEST round it is a form refusal naming the case", bool(about(got, "TC-001", "Archived")), str(got))
    finally:
        cleanup(root)


# --- K6 ----------------------------------------------------------------------------------------------------

def k6_level() -> None:
    root = temp_project("qa-merges-k6-")
    try:
        plan = {"rows": [{"id": "TS-1", "level": "e2e-ui", "disposition": "automate"},
                         {"id": "TS-2", "level": "api", "disposition": "manual-agent"},
                         {"id": "TS-3", "level": "e2e-ui", "disposition": "skip"},
                         {"id": "TS-4", "level": "component", "disposition": "automate"}]}
        task = story(root, {}, plan)

        def run(note, verdict="approve_with_concerns", plan_row="TS-1", reviewed="yes", cols=("plan_row", "case", "reviewed", "verdict", "note")):
            findings(task, round_text(roll=[row(plan_row, "TC-001", verdict, note, reviewed)], cols=cols))
            return errors_of(task)

        got = run("")
        check("K6: an e2e-ui row with no token -> refusal naming the plan row and the form",
              bool(about(got, "TS-1", "lower level:", "impossible")), str(got))
        check_eq("K6: `lower level: impossible - stand-only path` -> clean (even with `approve`)", run("lower level: impossible - stand-only path", "approve"), [])
        check("K6: `impossible` with no reason after the dash -> refusal", bool(run("lower level: impossible")))
        check("K6: `lower level: component - x` with `approve` -> refusal (it reaches the automator only as a concern)",
              bool(about(run("lower level: component - x", "approve"), "TS-1", "approve_with_concerns")))
        check_eq("K6: ... with `approve_with_concerns` -> clean", run("lower level: component - x"), [])
        check("K6: `lower level: e2e-ui - x` on an e2e-ui row -> refusal (E19)", bool(about(run("lower level: e2e-ui - x"), "no level below")))
        check_eq("K6: the plan row cell in backticks is still found", len(run("", plan_row="`TS-1`")), 1)
        check("K6: a manual row at `api` with `lower level: api - x` -> refusal", bool(about(run("lower level: api - x", plan_row="TS-2"), "TS-2")))
        check_eq("K6: ... with `unit - x` and `approve_with_concerns` -> clean", run("lower level: unit - x", plan_row="TS-2"), [])
        check_eq("K6: a `skip` row owes nothing", run("", plan_row="TS-3"), [])
        check_eq("K6: an automated component row owes nothing", run("", plan_row="TS-4"), [])
        check_eq("K6: an unreviewed row is not read here", run("", reviewed="no"), [])
        got = run("x", cols=("plan_row", "case", "reviewed", "verdict"))
        check("K6: a roll-call with no `note` column -> ONE refusal asking for the column", len(got) == 1 and "`note` column" in got[0], str(got))
        bare = story(root, {}, None, ticket="QA-2")
        findings(bare, round_text(roll=[row("TS-1", "TC-001")]))
        got, notes = CR.merge_candidate_errors(bare)
        check_eq("K6: no test-plan.json -> no refusal (E13)", got, [])
        check("K6: ... and a note says the level was not checked", any("level" in n and "not checked" in n for n in notes), str(notes))
        broken = story(root, {}, "{not json", ticket="QA-3")
        findings(broken, round_text(roll=[row("TS-1", "TC-001")]))
        got, notes = CR.merge_candidate_errors(broken)
        check("K6: an unreadable plan -> a note naming it, no refusal", got == [] and any("test-plan.json" in n for n in notes), str(notes))
    finally:
        cleanup(root)


# --- K7 ----------------------------------------------------------------------------------------------------

def k7_project_form() -> None:
    root = temp_project("qa-merges-k7-")
    try:
        cfg = root / "qa-factory" / "config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["case_id_form"] = "{ticket}_TC_{nnn}"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        a, b = "QA-1_TC_001", "QA-1_TC_002"
        task = story(root, {a: ("R-1", "Draft"), b: ("R-1", "Draft")})
        both = carried(a, b)
        findings(task, round_text(roll=[row("TS-1", a, note=both), row("TS-2", b, note=both)], merges=[(f"{a}, {b}", "merge", "one form")]))
        check_eq("K7: a project case-id form in the cells and after the token -> clean", errors_of(task), [])
        findings(task, round_text(roll=[row("TS-1", a, note=both), row("TS-2", b, "approve")], merges=[(f"{a}, {b}", "merge", "one form")]))
        check("K7: ... and the refusal names the project-form id", bool(about(errors_of(task), b)), str(errors_of(task)))
    finally:
        cleanup(root)


# --- K8 / K8b ----------------------------------------------------------------------------------------------

def k8_budget() -> None:
    root = temp_project("qa-merges-k8-")
    try:
        for label, plan, want in (("no plan file", None, None), ("the key absent", {"rows": []}, None),
                                  ("0", {"rows": [], "plan_case_budget": 0}, None), ("-1", {"rows": [], "plan_case_budget": -1}, None),
                                  ('"10"', {"rows": [], "plan_case_budget": "10"}, None), ("true", '{"rows": [], "plan_case_budget": true}', None),
                                  ("10.0", '{"rows": [], "plan_case_budget": 10.0}', None), ("an unreadable plan", "{nope", None),
                                  ("a plan that is a bare list", [], None), ("10", {"rows": [], "plan_case_budget": 10}, 10)):
            task = story(root, {}, plan, ticket=f"QA-{abs(hash(label)) % 9999}")
            check_eq(f"K8: plan_case_budget with {label}", BA.plan_case_budget(task), want)

        def cases(n, archived=0):
            return {f"TC-{i:03d}": (f"R-{i}", "Archived" if i <= archived else "Draft") for i in range(1, n + 1)}

        def run(n, extra=(), archived=0, ticket="QA-B"):
            task = story(root, cases(n, archived), {"rows": [], "plan_case_budget": 2}, ticket=ticket)
            findings(task, round_text(extra=extra))
            return errors_of(task)

        check_eq("K8: budget 2, 2 live cases -> nothing (count == n)", run(2, ticket="QA-B2"), [])
        got = run(3, ticket="QA-B3")
        check("K8: 3 cases -> a refusal holding `Over the plan case budget:` and both numbers", bool(about(got, "Over the plan case budget:", "3 cases", "is 2")), str(got))
        check_eq("K8: 3 cases + `Over the plan case budget: TC-3 needs its own fixture` -> clean",
                 run(3, ["Over the plan case budget: TC-3 needs its own fixture"], ticket="QA-B4"), [])
        check("K8: the prefix alone -> refusal", bool(run(3, ["Over the plan case budget:"], ticket="QA-B5")))
        check_eq("K8: 3 cases, one Archived -> nothing", run(3, archived=1, ticket="QA-B6"), [])
        task = story(root, cases(3), None, ticket="QA-B7")
        findings(task, round_text())
        got, notes = CR.merge_candidate_errors(task)
        check("K8: no budget -> no refusal, and a note says it was not held", got == [] and any("plan_case_budget" in n for n in notes), str(notes))
    finally:
        cleanup(root)


def k8b_brief_line() -> None:
    root = temp_project("qa-merges-k8b-")
    try:
        task = story(root, {}, {"rows": [], "plan_case_budget": 10})
        got = BP.s4_case_budget_line(task, "qa-case-critic")
        check("K8b: budget 10 -> one line holding 10 and the critic's line", len(got) == 1 and "10" in got[0] and "Over the plan case budget:" in got[0], str(got))
        check_eq("K8b: the designer gets it too", BP.s4_case_budget_line(task, "qa-case-designer"), got)
        none = story(root, {}, None, ticket="QA-2")
        check_in("K8b: no budget -> `not set`", "not set", BP.s4_case_budget_line(none, "qa-case-critic"))
        check_eq("K8b: another role gets no line", BP.s4_case_budget_line(task, "qa-automator"), [])
        real = BA.plan_case_budget

        def boom(*_a, **_k):
            raise OSError("disk gone")
        BA.plan_case_budget = boom
        try:
            check_eq("K8b: the reader raising -> no line (a courtesy never stops the brief)", BP.s4_case_budget_line(task, "qa-case-critic"), [])
        finally:
            BA.plan_case_budget = real
    finally:
        cleanup(root)


# --- K9 ----------------------------------------------------------------------------------------------------

def run_detector(task: Path) -> tuple:
    os.environ.pop(planning_contract.DETECTOR_STORY_ENV, None)
    real = planning_contract.running_story
    planning_contract.running_story = lambda *a, **k: task
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = CR.detector_main()
    finally:
        planning_contract.running_story = real
    return code, out.getvalue()


def pipeline_of(*matches) -> dict:
    return {"stage_overrides": [{"stage": "S4", "match": m, "decision": "go on", "at": "2026-11-02T10:00:00", "by": "human"} for m in matches]}


def k9_exit() -> None:
    root = temp_project("qa-merges-k9-")
    try:
        task = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-1", "Draft")})
        findings(task, round_text("1", "approve", roll=[row("TS-1", "TC-001", "approve"), row("TS-2", "TC-002", "approve")]))
        code, text = run_detector(task)
        parsed = DV.parse(code, text, "")
        check_eq("K9: an unanswered pair -> exit 1", code, 1)
        check("K9: ... the findings are read, none unmigrated", len(parsed["findings"]) >= 1 and not parsed["unmigrated"], str(parsed))
        check_in("K9: ... the person's door is printed", "waiver.py --task", text)
        check("K9: ... the budget-absent note comes BEFORE the REJECT head", 0 <= text.find("note: the S3 plan sets no case budget") < text.find("REJECT"), text)

        findings(task, round_text("1", "approve", roll=[row("TS-1", "TC-001", "approve"), row("TS-2", "TC-002", "approve")],
                                  merges=[("TC-001, TC-002", "keep", "P16: one red line tells them apart")]))
        code, text = run_detector(task)
        check_eq("K9: the pair answered -> exit 0 and `OK:`", (code, "OK:" in text), (0, True))
        check_in("K9: ... and the budget-absent note is printed", "note: the S3 plan sets no case budget", text)

        real = CR.merge_candidate_errors

        def boom(*_a, **_k):
            raise ValueError("own defect")
        CR.merge_candidate_errors = boom
        try:
            code, text = run_detector(task)
        finally:
            CR.merge_candidate_errors = real
        check_eq("K9: the check raising -> UNREADABLE, exit 3", (code, text.startswith(DV.UNREADABLE_PREFIX)), (DV.EXIT_UNREADABLE, True))

        # E11: a person's word passes ONLY this node's lines
        pair_task = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-1", "Draft")}, ticket="QA-3")
        findings(pair_task, round_text(roll=[row("TS-1", "TC-001"), row("TS-2", "TC-002")]))
        pair = errors_of(pair_task)
        plain = CR.findings_errors(task / "work" / "test-cases" / "area" / "critic-findings.md", "# Round\n\n## Roll-call\n\n| plan_row | case | reviewed |\n|---|---|---|\n| TS-1 | TC-001 | yes |\n")
        check("K9: the roll-call refusal exists (no `Verdict:` line)", bool(about(plain, "Verdict:")), str(plain))
        blocking, passed = waiver.split_overridden(pair + plain, pipeline_of("Merge candidates"), "S4")
        check_eq("K9: a word `Merge candidates` passes the pair refusal", (len(passed), blocking == plain), (len(pair), True))
        level_task = story(root, {}, {"rows": [{"id": "TS-1", "level": "e2e-ui", "disposition": "automate"}]}, ticket="QA-4")
        findings(level_task, round_text(roll=[row("TS-1", "TC-001")]))
        level = errors_of(level_task)
        check_eq("K9: a word `lower level` passes the level refusal and not the roll-call one",
                 (len(waiver.split_overridden(level, pipeline_of("lower level"), "S4")[1]), waiver.split_overridden(plain, pipeline_of("lower level"), "S4")[1]),
                 (len(level), []))
        budget_task = story(root, {f"TC-00{i}": (f"R-{i}", "Draft") for i in (1, 2, 3)}, {"rows": [], "plan_case_budget": 2}, ticket="QA-5")
        findings(budget_task, round_text())
        budget = errors_of(budget_task)
        check_eq("K9: a word `Over the plan case budget` passes the budget refusal (the `names_whole` right edge, m-4)",
                 (len(budget), len(waiver.split_overridden(budget, pipeline_of("Over the plan case budget"), "S4")[1])), (1, 1))
        check_eq("K9: ... and not the pair refusal", waiver.split_overridden(pair, pipeline_of("Over the plan case budget"), "S4")[1], [])
    finally:
        cleanup(root)


# --- K-CAL -------------------------------------------------------------------------------------------------

CAL_MERGES = (("TC-002, TC-003", "merge", "same When form"), ("TC-001, TC-011", "merge", "same When form"),
              ("TC-004, TC-005", "merge", "same When form"))
CAL_KEEPS = (("TC-005, TC-006", "keep", "P16: different branches"), ("TC-005, TC-014", "keep", "P19: another level"),
             ("TC-006, TC-010", "keep", "P16: different branches"), ("TC-008, TC-012", "keep", "P19: another level"),
             ("TC-011, TC-012", "keep", "P16: different branches"))
LOWER = "lower level: component - developers' component test"


def cal_rows(**over) -> list:
    """One roll-call row per plan row that has a case (TS-13 is a `skip`, no case). The word and note of a row can be overridden by `TS-n=(verdict, note)`."""
    base = {1: ("approve_with_concerns", carried("TC-001", "TC-011")), 2: ("approve_with_concerns", carried("TC-002", "TC-003")),
            3: ("approve_with_concerns", carried("TC-002", "TC-003")), 4: ("approve_with_concerns", carried("TC-004", "TC-005")),
            5: ("approve_with_concerns", carried("TC-004", "TC-005")), 6: ("approve", ""), 7: ("approve", ""),
            8: ("approve_with_concerns", LOWER), 9: ("approve_with_concerns", LOWER),
            10: ("approve", "lower level: impossible - needs the stand's UI"), 11: ("approve_with_concerns", carried("TC-001", "TC-011")),
            12: ("approve", "lower level: impossible - needs the stand's UI"), 14: ("approve", "lower level: impossible - no endpoint to call")}
    for key, value in over.items():
        base[int(key.split("_")[1])] = value
    return [row(f"TS-{n}", f"TC-{n:03d}", *base[n]) for n in sorted(base)]


def cal_story(root: Path, **kw) -> tuple:
    """The 12586 fixture copied into a temp project; its findings file REPLACED by the round of this test (the old round is not part of the key)."""
    task = root / "qa-factory" / "artifacts" / "TP1-12586"
    if not task.exists():
        shutil.copytree(FIX, task)
    merges = kw.get("merges", CAL_MERGES + CAL_KEEPS)
    if kw.get("drop"):
        merges = tuple(m for m in merges if m[0] != kw["drop"])
    rows = cal_rows(**kw.get("over", {}))
    path = findings(task, round_text(verdict=kw.get("verdict", "approve_with_concerns"), roll=rows, merges=list(merges)), area="integrations")
    return task, path


def kcal_calibration() -> None:
    root = temp_project("qa-merges-kcal-")
    try:
        plan = json.loads((FIX / "work" / "test-plan.json").read_text(encoding="utf-8-sig"))["rows"]
        by = {r["id"]: (r.get("level"), r.get("disposition")) for r in plan}
        check_eq("K-CAL: the plan rows the round answers are what the spec says",
                 [by[f"TS-{n}"] for n in (8, 9, 10, 12, 14)],
                 [("e2e-ui", "automate"), ("e2e-ui", "automate"), ("e2e-ui", "manual-agent"), ("e2e-ui", "manual-agent"), ("api", "manual-agent")])
        task, path = cal_story(root)
        cases = sorted((task / "work" / "test-cases" / "integrations").glob("TC-*.md"))
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in cases}
        statuses = {p.stem: C.case_status(p) for p in cases}
        got, _notes = CR.merge_candidate_errors(task)
        check_eq("K-CAL: the round the critic would write -> no refusal", got, [])
        data = path.read_bytes()
        concerns = CR.carried_concerns(data, hashlib.sha256(data).hexdigest())
        check_eq("K-CAL: concerns are carried for exactly TC-001..TC-005, TC-011, TC-008, TC-009",
                 sorted({c["case"] for c in concerns}), ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005", "TC-008", "TC-009", "TC-011"])
        partner = {"TC-001": "TC-011", "TC-011": "TC-001", "TC-002": "TC-003", "TC-003": "TC-002", "TC-004": "TC-005", "TC-005": "TC-004"}
        mine = {c["case"]: c["problem"] for c in concerns}
        check("K-CAL: each of the six merged cases' concern holds the token and its partner id",
              all(TOKEN in mine[a] and b in mine[a] for a, b in partner.items()), str(mine))
        check_eq("K-CAL: a merge changes no case: the files and their statuses are as they were",
                 ({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in cases}, {p.stem: C.case_status(p) for p in cases}), (before, statuses))

        got = CR.merge_candidate_errors(cal_story(root, drop="TC-006, TC-010")[0])[0]
        check("K-CAL: drop the TC-006/TC-010 row -> a refusal names TC-006, TC-010 and R-8", bool(about(got, "TC-006", "TC-010", "R-8")), str(got))
        got = CR.merge_candidate_errors(cal_story(root, over={"TS_3": ("approve", "")})[0])[0]
        check("K-CAL: TS-3 `approve` -> a refusal names TC-003", bool(about(got, "TC-003")), str(got))
        got = CR.merge_candidate_errors(cal_story(root, over={"TS_2": ("approve_with_concerns", carried("TC-002"))})[0])[0]
        check("K-CAL: TS-2's note without TC-003 -> a refusal names TC-002", bool(about(got, "TC-002")), str(got))
        got = CR.merge_candidate_errors(cal_story(root, over={"TS_8": ("approve_with_concerns", "a concern")})[0])[0]
        check("K-CAL: TS-8's note without the token -> a level refusal on TS-8", bool(about(got, "TS-8", "lower level:")), str(got))
        got = CR.merge_candidate_errors(cal_story(root, over={"TS_12": ("approve", "")})[0])[0]
        check("K-CAL: TS-12's note without the token -> a level refusal on TS-12", bool(about(got, "TS-12", "lower level:")), str(got))
        # the honest negative: no merge rows at all, the six rows `approve` -> the merge check has nothing to say
        plain = {f"TS_{n}": ("approve", "") for n in (1, 2, 3, 4, 5, 11)}
        got = CR.merge_candidate_errors(cal_story(root, merges=CAL_KEEPS, over=plain)[0])[0]
        check_eq("K-CAL: no merge rows and the six rows `approve` -> NO refusal from the merge check (the honest negative)", got, [])
    finally:
        cleanup(root)


# --- K-FIX (t-756 m-1..m-4b) -------------------------------------------------------------------------------

def kfix_verdict() -> None:
    root = temp_project("qa-merges-kfix-")
    try:
        # m-1: a cell naming TWO plan ids must not let an owed e2e-ui line pass (either order)
        plan = {"rows": [{"id": "TS-1", "level": "api", "disposition": "automate"}, {"id": "TS-8", "level": "e2e-ui", "disposition": "automate"}]}
        task = story(root, {}, plan)
        for cell in ("TS-8", "TS-1, TS-8", "TS-8, TS-1"):
            findings(task, round_text(roll=[row(cell, "TC-001", "approve_with_concerns", "")]))
            check(f"m-1: cell `{cell}`, no `lower level:` line -> a level refusal on TS-8", bool(about(errors_of(task), "TS-8", "lower level:")))
        findings(task, round_text(roll=[row("TS-1, TS-8", "TC-001", "approve_with_concerns", "lower level: impossible - stand only")]))
        check_eq("m-1: cell `TS-1, TS-8` with the line -> clean", errors_of(task), [])
        # m-2: keep reasons in ordinary spellings are accepted
        keep = story(root, {"TC-001": ("R-1", "Draft"), "TC-002": ("R-1", "Draft")}, ticket="QA-2")
        for reason in ("(P19) another level", "P19, another level", "P16. one red line", "P16: x", "**P16**: x", "`P16` x"):
            findings(keep, round_text(merges=[("TC-001, TC-002", "keep", reason)]))
            check_eq(f"m-2: keep reason `{reason}` -> clean", errors_of(keep), [])
        for reason in ("P160 x", "because P16", "P1 x"):
            findings(keep, round_text(merges=[("TC-001, TC-002", "keep", reason)]))
            check(f"m-2 (negative control): keep reason `{reason}` -> refused", bool(about(errors_of(keep), "neither P16 nor P19")))
        # m-3: a newer `keep` on A,B must not make A and B name each other after an older A,B,C merge
        grp = story(root, {f"TC-00{i}": ("R-1", "Draft") for i in (1, 2, 3)}, ticket="QA-3")
        old = round_text(1, roll=[row("TS-1", "TC-001", note=carried("TC-001", "TC-002", "TC-003")),
                                  row("TS-2", "TC-002", note=carried("TC-001", "TC-002", "TC-003")),
                                  row("TS-3", "TC-003", note=carried("TC-001", "TC-002", "TC-003"))],
                         merges=[("TC-001, TC-002, TC-003", "merge", "one form")])
        new = round_text(2, roll=[row("TS-1", "TC-001", note=carried("TC-001", "TC-003")), row("TS-2", "TC-002", note=carried("TC-002", "TC-003")),
                                  row("TS-3", "TC-003", note=carried("TC-001", "TC-002", "TC-003"))],
                         merges=[("TC-001, TC-002", "keep", "P16: x")])
        findings(grp, new, old)
        check_eq("m-3: newest `keep` on A,B over an older A,B,C merge, A and B name only C -> clean", errors_of(grp), [])
        findings(grp, new.replace(carried("TC-001", "TC-003"), "a concern"), old)
        check("m-3 (negative control): A names nobody -> refused", bool(about(errors_of(grp), "TC-001")))
        # m-4a: a plan that exists with no rows is not `no test-plan.json`
        empty = story(root, {}, {"rows": []}, ticket="QA-4")
        findings(empty, round_text(roll=[row("TS-1", "TC-001")]))
        got, notes = CR.merge_candidate_errors(empty)
        check("m-4a: a plan with no rows -> `the plan has no rows`, not `no test-plan.json`",
              got == [] and any("the plan has no rows" in n for n in notes) and not any("no test-plan.json" in n for n in notes), str(notes))
        bare = story(root, {}, None, ticket="QA-5")
        findings(bare, round_text(roll=[row("TS-1", "TC-001")]))
        check("m-4a (negative control): no plan file -> `no test-plan.json`", any("no test-plan.json" in n for n in CR.merge_candidate_errors(bare)[1]))
        # m-4b: the clean-exit budget note says it is the factory's gap and nothing for the role
        notes = CR.merge_candidate_errors(bare)[1]
        check("m-4b: the budget note names the S3 plan, SC5-6 and `nothing for the role to do`",
              any("the S3 plan sets no case budget yet" in n and "SC5-6" in n and "nothing for the role to do" in n for n in notes), str(notes))
        check("m-4b: ... and no longer says the count `was not held to one` as the role's problem", not any("not held to one" in n for n in notes))
    finally:
        cleanup(root)


def main() -> None:
    for step in (k0_records, k1_owed_pair, k2_form, k3_pairs, k3b_truncation, k4_concern, k5_older_rounds, k6_level, k7_project_form,
                 k8_budget, k8b_brief_line, k9_exit, kcal_calibration, kfix_verdict):
        step()
    finish("test_case_merges")


if __name__ == "__main__":
    main()
