"""t-1508 R7 on the stand run's own data: keys K-R7-S and K-R7-8 (fix round t-1556 F13, t-1561).

The triage row and the function of TC-003 are those of the fixture `run-12586-red-then` (the row verbatim, the function under the
stub of the product, `test-code/product_stub.py`). The round is driven through the real consumers, nothing is stubbed on this side:
  K-R7-S   a triage row `reorder: true` on TC-003 -> the form of `s7-analyst-to-automator` with `scope[].state: reorder`,
           `repairs[].kind: reorder`, `verdict: APP_BUG` passes `handoff_check`; the function with Then 3 and 4 above Then 2 is
           `variant_shape.moved` (nothing added, removed or outside); `s7_reorder.finish` carries the row to the new red attempt;
           `bind_triage` holds the row on it, `handoff_check` (claim of S7) and `check_delivery.triage_reasons` say no "no verdict",
           and the row still says APP_BUG (the verdict the delivery reads is the analyst's, the round never changes it)
  K-R7-4   the same function with a Then text changed is refused (`shape`), nothing carried
  K-R7-8   the stage statuses of S5 and S6 (the fixture's pipeline.json) and the controller state are byte-equal before and after
           the round: the bookkeeping writes only `work/triage.json` and `work/s7-reorder/`
Mutants: no `carried_attempts` condition in `_attempt_fits` -> K-R7-S (bind); no `variant_shape` in `finish` -> K-R7-4;
`start`/`finish` writing the pipeline -> K-R7-8; the form check ignoring `reorder` -> K-R7-S (the form).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

import check_delivery as CD  # noqa: E402
import contract as C  # noqa: E402
import handoff  # noqa: E402
import handoff_check as HC  # noqa: E402
import s7_reorder as R  # noqa: E402
import test_probe_binding as PB  # noqa: E402
import test_s7_null_outcome as N  # noqa: E402
import variant_shape as VS  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-red-then"
IID = "test_put_project_change_into_project_with_ms_teams_is_rejected"
CASE = "TC-003"
FILE = "tests/test_calc.py"
FIRST = "a96f5e653377735139aa"          # the attempt of the stand run that the triage row names
SECOND = "b2c3d4e5f60718293a4b"          # the attempt of the author's run on the moved bytes


def composed() -> str:
    return ((FIXTURE / "test-code" / "product_stub.py").read_text(encoding="utf-8")
            + (FIXTURE / "test-code" / "put_project_change_into_occupied_project.py").read_text(encoding="utf-8"))


def blocks(text: str) -> dict:
    """{n: (first line index, last line index)} of the five-line assert of each Then of the function (0-based, inclusive)."""
    lines = text.splitlines()
    out = {}
    for n in (1, 2, 3, 4):
        at = next(i for i, line in enumerate(lines) if f'"Then {n}' in line)
        out[n] = (at - 3, at + 1)
        assert lines[at - 3].strip() == "assert_that(" and lines[at + 1].strip() == ")", n
    return out


def reordered(text: str) -> str:
    """Then 4 and Then 3 above Then 2: the lines are those of the function, only their order changes. (Order 1, 3, 4, 2 is the same
    move, but `variant_shape` reads it as 'the Then 2 assert moved past the last statement' and answers `outside`: a finding of
    t-1561, in its report; this order is the one it reads as a move.)"""
    lines, b = text.splitlines(), blocks(text)
    part = lambda n: lines[b[n][0]:b[n][1] + 1]          # noqa: E731
    return "\n".join(lines[:b[2][0]] + part(4) + part(3) + part(2) + lines[b[4][1] + 1:]) + "\n"


def triage_row() -> dict:
    rows = json.loads((FIXTURE / "work" / "triage.json").read_text(encoding="utf-8"))["triage"]
    row = dict(next(r for r in rows if r["instance_id"] == IID))
    row.update(attempt_id=FIRST, reorder=True, blocked_thens=[
        {"then": 3, "blocking_check": "Then 2", "detail": "the target holds exactly one integration, whatever the refusal says"},
        {"then": 4, "blocking_check": "Then 2", "detail": "the source integration is unchanged, whatever the refusal says"}])
    return row


def result(attempt: str, purpose: str, sha: str) -> dict:
    return {"instance_id": IID, "test_id": f"tests.test_calc::{IID}", "status": "failed", "attempt_id": attempt, "purpose": purpose,
            "case_version_links": [{"case_id": CASE, "version": "cv_1"}], "instance_code_sha": sha,
            "reason": "AssertionError: Then 2: the rejection reason must not be the 'Project mismatch' text."}


def write_report(task: Path, rows: list) -> None:
    PB.write(task / "work" / "run-report.json", {"schema_version": 2, "execution_status": "failed", "results": rows,
                                                  "current_results": rows[-1:], "current_totals": {"failed": 1},
                                                  "current_manual_checks": []})


def code_sha(fx, iid: str) -> str:
    import proof_level as PL
    entry = C.load_json(fx.task / "work" / "automation-manifest.json")["tests"][0]
    PL._reset()
    return PL.instance_identity(entry, fx.task, fx.root)["instance_identity"]["instance_code_sha"]


def the_form(fx, *, state="reorder", kind="reorder") -> str:
    text = N.a_form(scope=(), nfr=[], window=IID)
    text = N.replace_section(text, "scope", "\n".join([
        "scope:", f"  - id: {IID}", f"    state: {state}", "    reason: Then 3 and 4 sit behind the red Then 2", f"    case: {CASE}",
        "    round: 1 of 2"]))
    return N.replace_section(text, "repairs", "\n".join([
        "repairs:", f"  - id: {IID}", f"    kind: {kind}", "    verdict: APP_BUG", "    evidence: evidence/runs/diagnostic-a5ba38dc.log",
        "    problem: the asserts of Then 3 and 4 sit behind the red Then 2 so the test cannot answer for them",
        "    expected: Then 3 and 4 are asserted before Then 2 and keep their lines and values",
        "    fix: move the asserts of Then 3 and 4 above the assert of Then 2", f"    check: run_suite.py --mine {CASE} --purpose repair_verify",
        "    then_lines: the Then lines read the same after the move"]))


def problems_of(fx, form: str) -> list:
    doc, _fixed, problems, _j, _d = HC.check(handoff.parse(form), N.CONTRACT, HC.Artifacts(fx.task), fix=False, use_judge=False)
    return problems


def the_world():
    fx = PB.Fixture({FILE: composed()}, [PB.row(IID, CASE, FILE, selector=f"{FILE}::{IID}")], scope=(CASE,))
    fx.job([CASE])                                                           # the author's run: the identity is measured from it
    PB.write(fx.task / "pipeline.json", (FIXTURE / "controller" / "TP1-12586" / "pipeline.json").read_text(encoding="utf-8"))
    PB.write(fx.task / "work" / "triage.json", {"schema_version": 2, "task_id": PB.TASK, "triage": [triage_row()]})
    write_report(fx.task, [result(FIRST, "initial", code_sha(fx, IID))])
    return fx


def statuses(task: Path) -> dict:
    stages = json.loads((task / "pipeline.json").read_text(encoding="utf-8")).get("stages") or {}
    return {s: (stages.get(s) or {}).get("status") for s in ("S5", "S6")}


def the_round_on_the_stand_runs_function() -> None:
    fx = the_world()
    try:
        task, root = fx.task, fx.root
        before_text = composed()
        check_in("the fixture row asks for the round and is sound", "reorder", json.dumps(triage_row()))
        check_eq("...the row is sound for the validator", C.triage_reorder_problems(triage_row()), [])
        S5S6 = statuses(task)
        check("K-R7-8 the fixture's pipeline holds a status for S5 and S6", all(S5S6.values()), str(S5S6))
        frozen = {name: (task / name).read_bytes() for name in ("pipeline.json", "state/controller.json")}

        # K-R7-S the form: before the round
        form = the_form(fx)
        check_eq("K-R7-S the form with state: reorder / kind: reorder / verdict: APP_BUG passes handoff_check",
                 [f"{p.path}: {p.text}" for p in problems_of(fx, form)], [])
        empty = N.verdict_of(N.a_form(scope=(), nfr=[(IID, "APP_BUG")]), fx.task)[2]
        check("...and the empty scope over the reorder row is refused (a reorder row IS a repair)",
              any(IID in p.text for p in empty), N.text_of(empty))

        # the function: Then 3 and 4 above Then 2 is a move, and nothing else
        moved = reordered(before_text)
        shape = VS.variant_shape(before_text, moved, IID)
        check("K-R7-S the function with Then 3 and 4 above Then 2: variant_shape sees only a move",
              shape["function_found"] and shape["moved"] and not (shape["added"] or shape["removed"] or shape["outside"]), str(shape))
        check_eq("...a move of the same lines (the text differs, the multiset of lines does not)",
                 (moved != before_text, sorted(moved.splitlines()) == sorted(before_text.splitlines())), (True, True))

        started = R.start(task, IID, root)
        check_eq("start: the snapshot of the fixture's function", (started["status"], started["function"], started["moved"]),
                 ("started", IID, [3, 4]))
        # K-R7-4 on the fixture: a changed Then text is a shape refusal, nothing carried
        PB.write(root / FILE, moved.replace("Then 3: the target must still hold exactly one", "Then 3: the target must hold one"))
        write_report(task, json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["results"]
                     + [result(SECOND, "repair_verify", code_sha(fx, IID))])
        try:
            R.finish(task, IID, root)
            refused = ""
        except R.ReorderRefused as exc:
            refused = exc.kind
        check_eq("K-R7-4 on the stand's function: a changed Then text is refused as `shape`", refused, "shape")
        check_not_in("...and nothing is carried", "carried_attempts", json.dumps(json.loads(
            (task / "work" / "triage.json").read_text(encoding="utf-8"))))

        # the clean move, its red run on the new bytes
        PB.write(root / FILE, moved)
        rows = [r for r in json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["results"]
                if r["attempt_id"] == FIRST]
        write_report(task, rows + [result(SECOND, "repair_verify", code_sha(fx, IID))])
        done = R.finish(task, IID, root)
        check_eq("K-R7-S finish carries the row to the red attempt of the moved bytes", (done["status"], done["attempt"]),
                 ("carried", SECOND))
        row = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"][0]
        check_eq("...the row keeps its verdict and its own attempt", (row["verdict"], row["attempt_id"], row["carried_by"]),
                 ("APP_BUG", FIRST, "s7_reorder"))
        report = C.load_json(task / "work" / "run-report.json")
        failures, _unnamed = C.triage_failures(report)
        bound = C.bind_triage(failures, [row])["matched"]
        check("K-R7-S bind_triage holds the row on the new red attempt", any(bound.values()), str(bound))
        plain = {k: v for k, v in row.items() if k != "carried_attempts"}
        check("...control: without carried_attempts the same row does not bind it",
              not any(C.bind_triage(failures, [plain])["matched"].values()))
        check_eq("K-R7-S handoff_check (the S7 form) still passes on the new attempt",
                 [f"{p.path}: {p.text}" for p in problems_of(fx, form)], [])
        reasons = CD.triage_reasons(task)
        check_not_in("K-R7-S check_delivery.triage_reasons: no 'has no verdict' for the failure", "has no verdict", "\n".join(reasons))
        check_not_in("...and no reason about the row's verdict", IID + " carries verdict", "\n".join(reasons))
        bare = {k: v for k, v in row.items() if k not in ("carried_attempts", "carried_by")}
        PB.write(task / "work" / "triage.json", {"schema_version": 2, "task_id": PB.TASK, "triage": [bare]})
        check_in("...control: the row without the carry reads as a failure with no verdict", "has no verdict",
                 "\n".join(CD.triage_reasons(task)))
        check_eq("K-R7-8 the statuses of S5 and S6 and the controller state are as before the round",
                 (statuses(task), {name: (task / name).read_bytes() for name in frozen}), (S5S6, frozen))
    finally:
        fx.close()


def main() -> None:
    the_round_on_the_stand_runs_function()
    finish("test_s7_reorder_fixture")


if __name__ == "__main__":
    main()
