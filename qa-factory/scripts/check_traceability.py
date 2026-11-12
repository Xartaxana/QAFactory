"""Requirement -> plan row -> case -> terminal outcome. Exit 1 on any requirement without one.

The chain the factory promises at gate B, walked by code:

  R-n in requirements-register.md
    -> one or more rows of test-plan.md whose R column names it
      -> the case(s) whose `Requirements:` header names it
        -> a terminal outcome: an executed automated test (automation-manifest.json +
           run-report.json), an executed manual-agent case, a manual-human case with an
           evidence package, or an explicit `pending_implementation` /
           `deferred_by_decision` — a decision, recorded, not a silence.

A requirement whose chain breaks anywhere is reported with the link that broke. There is no
"probably covered": an R that reaches no terminal outcome becomes a "not verified" row of
the checks ledger, and delivery_ready turns to no.

The one way a broken chain becomes terminal is a person: `pipeline.json`'s `gate_waivers[]`
(written by `waiver.py`) carries a gap the human accepted at a gate, with their own words,
and it reads here as `deferred_by_decision` with the gap still named beside it. Without that
record gate B recomputes a gap gate A already accepted and sends the whole pipeline round
again to ask the same question (TP2-2381, R-9).

Usage: check_traceability.py <artifacts-dir> [--json]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402

PASSED = ("passed", "pass")
FAILED = ("failed", "fail")


def _case_chain(case: str, row: dict, manifest: dict, report: dict, stricter=frozenset(), handed=frozenset(),
                cfg=None) -> tuple:
    """(outcome, detail, gap): ONE walk of the chain for a case, read by `outcome_for_case` and `gap_of_case` (C5: no
    twin). `outcome == ""` means the chain stops here, and `gap` then says where, as a typed WORD (t-305 N8): the
    delivery verdict is decided from the word, never from the detail's sentence (FR-12):
      `unresolved:<reason>`      the manifest's `unresolved[]` row for the case, with no decision attached
                                 (`no_reason` when the row has none);
      `result:<status>`          the run recorded a result that is not terminal (inconclusive, skipped, partial, ...);
      `manual_human_no_package`  a manual-human case with no evidence package;
      `unresolved:handed_to_person`  a manual-agent case the person took by hand at a refused stand (`handed`: the caller's
                                 set, from `check_delivery.person_check_rows`) and that has no run result: the person's line;
      `not_in_manifest`          neither in tests[] nor in unresolved[];
      `no_result`                an automated test the run has no result for.
    A case that reached an outcome has gap "". `cfg`: the project's case config, resolved once by the caller (`walk`); None =
    resolved per call (E-B5)."""
    cfg = C.case_config() if not isinstance(cfg, dict) else cfg
    results = C.run_results(report, cfg=cfg)          # once per call: it is a pure projection of the report
    for entry in C.manifest_unresolved(manifest):
        if not C.names_case(C.manifest_test_keys(entry, cfg=cfg), case, cfg):
            continue
        reason = str(entry.get("reason") or "")
        if reason == "pending_implementation":
            return ("pending_implementation", f"{case}: awaiting the implementation MR", "")
        if C.unresolved_decided(reason):
            return ("deferred_by_decision", f"{case}: {reason}", "")
        if reason == C.HANDED_TO_PERSON and C.case_lookup(results, case, cfg, exact_wins=False) in FAILED:
            # t-305 N8 attempt 2 (F1, P21): an observed failure outranks a hand-off - the case RAN and went red, so the
            # hand-off promises nothing about it; the failed result is the outcome (the ledger's `failed:*` row decides)
            return ("executed_failed", f"{case}: failed", "")
        if reason == "contradicts_requirement" and C.names_case(stricter, case, cfg) \
                and C.case_lookup(results, case, cfg, exact_wins=False) in FAILED:
            # HF2-18: the case RAN and went red, and its triage row carries the assert-stricter word with a well-formed
            # control experiment (`stricter`: the caller's set, from `contract.triage_control_problems`): the assert asks more
            # than the requirement does, so the red is the person's line in "Left with you" (the ledger's own failed row),
            # not a chain with no decision. Any other word, a malformed experiment, or an empty `stricter` (every
            # other caller) leaves the gap exactly as it was (FR-59, AR-28)
            return ("executed_failed", f"{case}: failed (the assert is stricter than the requirement)", "")
        return ("", f"{case}: unresolved ({reason or 'no reason'}) with no decision attached",
                "unresolved:" + (reason or "no_reason"))

    # S-3 (RD1-2): the impossible rows are a case -> reason mapping, looked up by identity, not by raw key
    impossible = C.run_impossible(report)
    why = C.case_lookup(impossible, case, cfg, rollup=False)
    if why is not None:
        return ("impossible", f"{case}: {why}", "")

    disposition = row.get("disposition", "")
    # S-2: the keys of `run_results` mix spellings; several matching keys roll up toward red (`contract.case_lookup`)
    result = C.case_lookup(results, case, cfg, exact_wins=False)      # D2-B3 Q2: red wins over a bare green row
    if result is not None:
        if result in PASSED:
            return ("executed_passed", f"{case}: passed", "")
        if result in FAILED:
            return ("executed_failed", f"{case}: failed", "")
        return ("", f"{case}: run result '{result}' is not terminal", f"result:{result or 'none'}")

    if disposition == "manual-human":
        evidence = C.manual_human_evidence(report)      # not `handed`: that is the caller's set of cases the person took by hand
        # D2-B2: the package is found by the identity match; only a NON-empty package counts, so a blank one beside a full
        # one under another spelling of the case never hides it (the filter comes first: no package is the safe side)
        package = C.case_lookup({k: v for k, v in evidence.items() if v}, case, cfg, rollup=False)
        if package:
            return ("evidence_for_human", f"{case}: evidence {package}", "")
        return ("", f"{case}: manual-human with no evidence package in run-report.json", "manual_human_no_package")

    if disposition == "manual-agent" and C.names_case(handed, case, cfg):      # S-4: the person's set is keyed as the caller spelled it
        # C5-4 (P21): the person chose to check this case by hand (`refused.by: person_checks`), so the requirement has its
        # outcome in "Left with you" - the word of the twin `handed` test (`delivery-verdict-kinds.json`: `after_checks`).
        # Below every observed result (a red or green run decided above: an observed failure is older than a hand-off) and
        # above `not_in_manifest`; only a manual-agent row of the plan reads it, any other lane keeps its gap (AR-28)
        return ("", f"{case}: taken by hand by the person", "unresolved:" + C.HANDED_TO_PERSON)

    test = next((t for t in C.manifest_tests(manifest) if C.names_case(C.manifest_test_keys(t, cfg=cfg), case, cfg)), None)
    if test is None:
        return ("", f"{case}: neither in automation-manifest tests[] nor unresolved[]", "not_in_manifest")
    return ("", f"{case}: automated as {test.get('file')} but run-report.json has no result for it", "no_result")


def outcome_for_case(case: str, row: dict, manifest: dict, report: dict, stricter=frozenset(), handed=frozenset(),
                     cfg=None) -> tuple:
    """(outcome, detail). outcome == "" means the chain stops here. `stricter` as in `walk` (t-1339 Q2: every reader of the
    chain takes the same set, so none reads a case the walk has already ended as still broken)."""
    outcome, detail, _gap = _case_chain(case, row, manifest, report, stricter, handed, cfg)
    return outcome, detail


def gap_of_case(case: str, row: dict, manifest: dict, report: dict, stricter=frozenset(), handed=frozenset(),
                cfg=None) -> str:
    """The typed word of the link that broke for this case (see `_case_chain`), "" when it reached an outcome."""
    return _case_chain(case, row, manifest, report, stricter, handed, cfg)[2]


def _handed_cases(artifacts: Path) -> frozenset:
    """The case keys the person took by hand (`check_delivery.person_check_rows`). Imported here as `main` does; an error is
    no case at all - the direction of `no` (the gap stays as it was)."""
    try:
        import check_delivery as D
        return frozenset(str(r["case"]) for r in D.person_check_rows(artifacts) if r.get("case"))
    except Exception:  # noqa: BLE001
        return frozenset()


def _open_gaps(rows: list, req: str, plan_for_req: list, artifacts: Path) -> bool:
    """A3: when the plan rows of `req` (all `skip` / `unverifiable`, no case) rest on a question that is not settled, append the
    unsettled row - outcome "", one `question_open` gap per question - and return True. The question comes from
    `work/test-plan.json` (the md row carries no `question_refs`), through `planning_contract.open_questions_of_plan_rows`.
    JSON or register present and unreadable: the same gap with `"question": ""` (unknown is no pass, FR-59). Nothing open and
    nothing unknown (also an older story with no JSON): False, the row reads as before."""
    import planning_contract as P
    state = P.open_questions_of_plan_rows(artifacts, [r["ts"] for r in plan_for_req])
    if state["unknown"]:
        gaps = [{"case": "", "gap": "question_open", "question": ""}]
        detail = f"the plan row rests on a question that could not be read: {state['unknown']}"
    elif state["open"]:
        gaps = [{"case": "", "gap": "question_open", "question": q["id"]} for q in state["open"]]
        detail = "the row waits for gate A question " + ", ".join(q["id"] for q in state["open"]) + ", not settled yet"
    else:
        return False
    rows.append({"requirement": req, "plan_rows": [r["ts"] for r in plan_for_req], "cases": [], "outcome": "",
                 "detail": detail, "gaps": gaps})
    return True


def walk(artifacts: Path, stricter=frozenset(), handed=None) -> dict:
    """`stricter`: the cases whose triage row is the assert-stricter word with a well-formed control experiment (the delivery check
    computes it, `check_delivery._stricter_cases`); empty = the chain as it always was. `handed`: the cases the person took by
    hand; None = computed here from `person_check_rows`, an empty set = none."""
    artifacts = Path(artifacts)
    if handed is None:
        handed = _handed_cases(artifacts)
    requirements = C.register_ids(C.artifact(artifacts, "requirements-register.md"))
    waivers = C.story_waivers(artifacts)
    plan_rows = C.parse_plan(C.artifact(artifacts, "test-plan.md"))
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    report = C.load_json(C.artifact(artifacts, "run-report.json"))
    cases = C.case_index(artifacts)
    cfg = C.case_config(artifacts)      # RD1-2: resolved once for the whole walk, handed down to every case (E-B5)

    rows = []
    for req in requirements:
        plan_for_req = [r for r in plan_rows if req in r.get("requirements", [])]
        if not plan_for_req:
            rows.append({"requirement": req, "plan_rows": [], "cases": [], "outcome": "",
                         "detail": "no row of test-plan.md names this requirement",
                         "gaps": [{"case": "", "gap": "no_plan_row"}]})
            continue

        skipped = [r for r in plan_for_req if r.get("disposition") in ("skip", "unverifiable")]
        cases_for_req = [cid for cid, meta in sorted(cases.items()) if req in meta.get("requirements", [])]
        # A2: a case that stayed on a row the plan excluded (an answer made it `skip` and nobody removed the case) and never
        # ran is set aside, not dropped silently: the row reads as it would with no case. The row is found EXACTLY by the case's
        # `Plan row:` (no fallback to the first row), and a case that ran is never set aside (`case_set_aside`).
        cases_for_req = [cid for cid in cases_for_req
                         if not (cases[cid].get("plan_row")
                                 and any(r["ts"] == cases[cid].get("plan_row")
                                         and C.case_set_aside(cid, r.get("disposition", ""), manifest, report)
                                         for r in plan_for_req))]
        if not cases_for_req:
            if len(skipped) == len(plan_for_req):
                # A3: a row that rests on a question nobody has settled is not a decision (AR-28, P21)
                if _open_gaps(rows, req, plan_for_req, artifacts):
                    continue
                rows.append({"requirement": req, "plan_rows": [r["ts"] for r in plan_for_req],
                             "cases": [], "outcome": "deferred_by_decision",
                             "detail": f"every row is {skipped[0].get('disposition')}: "
                                       f"{skipped[0].get('reason') or 'no reason given'}", "gaps": []})
                continue
            rows.append({"requirement": req, "plan_rows": [r["ts"] for r in plan_for_req],
                         "cases": [], "outcome": "",
                         "detail": "plan rows exist but no case carries `Requirements: " + req + "`",
                         "gaps": [{"case": "", "gap": "no_case"}]})
            continue

        outcomes, details, gaps = [], [], []
        for case in cases_for_req:
            row = next((r for r in plan_for_req if r["ts"] == cases[case].get("plan_row")), plan_for_req[0])
            outcome, detail, gap = _case_chain(case, row, manifest, report, stricter, handed, cfg)
            outcomes.append(outcome)
            details.append(detail)
            if not outcome:
                gaps.append({"case": case, "gap": gap})
        terminal = [o for o in outcomes if o]
        rows.append({
            "requirement": req,
            "plan_rows": [r["ts"] for r in plan_for_req],
            "cases": cases_for_req,
            "outcome": terminal[0] if len(terminal) == len(outcomes) else "",
            "detail": "; ".join(details),
            # the typed word of each case that reached no outcome (t-305 N8): what the delivery verdict reads
            "gaps": gaps,
        })

    # A gap the human accepted at a gate is a terminal outcome, whatever shape the gap took:
    # no plan row, no case, or a case that never reached one. The waiver carries their words
    # and the gap stays visible beside it — what it stops is asking the same person again at
    # the next gate, which on TP2-2381 cost a full second pass of the pipeline.
    for row in rows:
        if row["outcome"]:
            continue
        waiver = waivers.get(row["requirement"])
        if not waiver:
            continue
        row["outcome"] = "deferred_by_decision"
        row["waived_at"] = waiver.get("gate")
        was = row["detail"]
        row["detail"] = (f"accepted at gate {waiver.get('gate')}: {waiver.get('decision')}"
                         + (f" (the gap: {was})" if was else ""))

    missing = [r for r in rows if not r["outcome"]]
    return {"ticket": artifacts.name, "requirements": len(requirements), "rows": rows,
            "without_outcome": [r["requirement"] for r in missing], "ok": not missing and bool(requirements)}


def print_table(result: dict) -> None:
    print(f"TRACEABILITY {result['ticket']} — {result['requirements']} requirement(s)")
    print(f"  {'R':<6} {'plan rows':<16} {'cases':<20} {'outcome':<22} detail")
    for row in result["rows"]:
        print(f"  {row['requirement']:<6} {','.join(row['plan_rows'])[:15]:<16} "
              f"{','.join(row['cases'])[:19]:<20} {(row['outcome'] or 'NONE'):<22} {row['detail'][:80]}")
    if result["without_outcome"]:
        print("\nREQUIREMENTS WITHOUT A TERMINAL OUTCOME: " + ", ".join(result["without_outcome"]))
        print("Every one of them becomes a \"not verified\" row of the checks ledger — close the "
              "chain, or record the human's decision (deferred / pending implementation).")
    elif result["requirements"]:
        print("\nevery requirement reaches a terminal outcome")


def main() -> None:
    C.force_utf8()
    ap = argparse.ArgumentParser(description="Requirement -> plan row -> case -> outcome")
    ap.add_argument("artifacts", help="qa-factory/artifacts/<TICKET>/")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    artifacts = Path(args.artifacts)
    if not artifacts.exists():
        print(f"no such artifacts directory: {artifacts}", file=sys.stderr)
        sys.exit(1)
    # t-1339 F1: the CLI the driver prints at S8 and at the gate B recount answers like the delivery check does - the same
    # set of cases, from the one computation (`check_delivery._stricter_cases`). Imported here, not at the top: check_delivery
    # imports this module inside its functions, and a story folder `gather` cannot read simply has no such cases (the chain
    # stays as it always was - the direction of `no`)
    try:
        import check_delivery as D
        stricter = D._stricter_cases(D.gather(artifacts))
    except Exception:  # noqa: BLE001
        stricter = frozenset()
    result = walk(artifacts, stricter)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_table(result)
    if not result["requirements"]:
        print("no requirements-register.md, or it carries no R rows — nothing to trace", file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
