"""RN1-23 items 1 and 3 and the delivery side of RN1-15 (t-1698 D2-A): who owns a delivery reason.

* K-A5 / K-A5b..f: a reason that names ONLY cases whose current triage verdict is CASE_DEFECT is the factory's, whatever family its
  text starts with; every doubt (an older attempt, another area, a case with no verdict, a misspelt word, an unreadable triage record)
  leaves it under the product.
* K-A6: `coverage red: OB-n - none` (no cause at all) is `coverage:` (the factory's); a real gap text keeps `coverage red:`.
* K-A7: the product-gap carrier (`work/product-gaps.json`) - kind `product_gap`, owner product, verdict `no`; absent -> nothing,
  broken -> nothing plus a finding.
FR-35: every story below asserts that the verdict WORD is the one it had without the change (E-A10).

Mutations (named, NOT run; one killing file, this one):
  m2 check_delivery._owner_decided: move the CASE_DEFECT branch above the `failed:` branch   -> K-A5g
  m3 check_delivery._owner_decided: `later in (None, "product")` -> `True`                   -> K-A5h
  m4 check_delivery.case_defect_cases: `verdicts != {"CASE_DEFECT"}` -> `"CASE_DEFECT" not in verdicts` -> K-A5c (R-5 / mixed verdicts)
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import GOOD, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as D  # noqa: E402
import delivery_summary as DS  # noqa: E402
import report_facts as RF  # noqa: E402

# no requirement id in the unit texts: a named R-n resolves to ALL its cases (the passed ones too) and that is tested apart (K-A5c(c))
UNRESOLVED = "traceability: no terminal outcome ({cases}: unresolved (contradicts_requirement) with no decision attached)"


def reason(*cases: str) -> str:
    return UNRESOLVED.format(cases="; ".join(f"{c}" for c in cases))


def owner(text: str, defects, maps=None) -> str:
    return D.reason_owner(text, "", {"case_defect_cases": defects, "case_defect_maps": maps or {}, "cfg": {}})


def facts_of(manual: list, triage: list, index_keys=("TC-1",)) -> dict:
    """A hand-made `gather` result: the failures of the run report, the triage rows, the case index."""
    return {"report": {"current_manual_checks": manual}, "triage": triage, "manifest": {}, "cfg": {},
            "index": {k: {"case_id": k.split("/")[-1]} for k in index_keys}}


def fail(case: str, attempt: str = "a1") -> dict:
    return {"case": case, "result": "fail", "attempt_id": attempt}


def row(case: str, verdict: str, attempt: str = "a1") -> dict:
    return {"case": case, "verdict": verdict, "attempt_id": attempt}


def case_defect_set() -> None:
    # the set: a current CASE_DEFECT row binds, nothing else does
    check_eq("the set: one current CASE_DEFECT row", D.case_defect_cases(facts_of([fail("TC-1")], [row("TC-1", "CASE_DEFECT")])), ["TC-1"])
    # K-A5b: an old attempt CASE_DEFECT, the current attempt APP_BUG -> product
    f = facts_of([fail("TC-1", "a2")], [row("TC-1", "CASE_DEFECT", "a1"), row("TC-1", "APP_BUG", "a2")])
    check_eq("K-A5b: the set holds nothing (the old row binds nothing, the current one is APP_BUG)", D.case_defect_cases(f), [])
    check_eq("K-A5b: the reason stays product", owner(reason("TC-1"), D.case_defect_cases(f)), "product")
    # ... and two rows of DIFFERENT verdicts on one failure: mixed -> not a case defect
    f = facts_of([fail("TC-1")], [row("TC-1", "CASE_DEFECT"), row("TC-1", "APP_BUG")])
    check_eq("K-A5b: one failure with two verdicts is not a CASE_DEFECT case", D.case_defect_cases(f), [])
    # K-A5d: the word is compared exactly
    f = facts_of([fail("TC-1")], [row("TC-1", "case_defect")])
    check_eq("K-A5d: `case_defect` is no CASE_DEFECT", D.case_defect_cases(f), [])
    check_eq("K-A5d: ... so the reason stays product", owner(reason("TC-1"), D.case_defect_cases(f)), "product")
    # K-A5e: triage unreadable -> empty set -> product
    for bad in ({"triage": None}, {"triage": [row("TC-1", "CASE_DEFECT")], "report": None}, {}):
        f = dict(facts_of([fail("TC-1")], []), **bad)
        check_eq(f"K-A5e: an unreadable record ({sorted(bad)}) gives an empty set", D.case_defect_cases(f), [])
    root = temp_project("qa-owner-triage-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        (art / "work" / "triage.json").write_text("{not json", encoding="utf-8")
        check_eq("K-A5e: a triage.json that is not JSON gives an empty set", D.case_defect_cases(D.gather(art)), [])
        check_eq("K-A5e: ... and the owner is the product's", owner(reason("TC-1"), D.case_defect_cases(D.gather(art))), "product")
    finally:
        cleanup(root)
    # the area travels when the index spells it; a bare id under several areas is dropped (the failure cannot say which)
    f = facts_of([fail("web/TC-1")], [row("web/TC-1", "CASE_DEFECT")], ("web/TC-1",))
    check_eq("the area comes from the index", D.case_defect_cases(f), ["web/TC-1"])
    f = facts_of([fail("TC-1")], [row("TC-1", "CASE_DEFECT")], ("web/TC-1", "api/TC-1"))
    check_eq("a bare id under two areas is dropped", D.case_defect_cases(f), [])


def reason_owner_branch() -> None:
    both = ["TC-1", "TC-2"]
    check_eq("control: every case named is a CASE_DEFECT one -> factory", owner(reason("TC-1", "TC-2"), both), "factory")
    check_eq("control: ... with one case", owner(reason("TC-1"), ["TC-1"]), "factory")
    # E-A6: mixed
    check_eq("E-A6: one named case with another verdict (or none) keeps the family's owner", owner(reason("TC-1", "TC-2"), ["TC-1"]), "product")
    # E-A5: no id at all; E-A7: an empty set
    check_eq("E-A5: a reason that names no case is not lifted", owner("traceability: R-4 has no terminal outcome", both), "product")
    check_eq("E-A7: an empty set lifts nothing", owner(reason("TC-1"), []), "product")
    check_eq("E-A7: no context lifts nothing", D.reason_owner(reason("TC-1")), "product")
    # K-A5b/c adversarial inputs
    check_eq("K-A5c(b): web/TC-1 is the defect, the reason names api/TC-1 -> product",
             owner("traceability: no terminal outcome (api/TC-1: unresolved (contradicts_requirement) with no decision attached)",
                   ["web/TC-1"]), "product")
    check_eq("K-A5c(b) control: the reason names web/TC-1 -> factory",
             owner("traceability: no terminal outcome (web/TC-1: unresolved (contradicts_requirement) with no decision attached)",
                   ["web/TC-1"]), "factory")
    check_eq("K-A5c(b) control: a bare id names any area (the documented generosity) -> factory", owner(reason("TC-1"), ["web/TC-1"]), "factory")
    check_eq("a compound cell `TC-1/TC-2` is two cases, not an area -> factory when both are defects",
             owner("traceability: no terminal outcome (TC-1/TC-2: unresolved (contradicts_requirement))", both), "factory")
    check_eq("... and product when one of them is not", owner(
        "traceability: no terminal outcome (TC-1/TC-2: unresolved (contradicts_requirement))", ["TC-1"]), "product")
    check_eq("TC-1 is not TC-10", owner(reason("TC-10"), ["TC-1"]), "product")
    # K-A5c(c): a requirement whose cases are TC-1 (CASE_DEFECT) and TC-2 (no verdict) -> product; resolving to one defect -> factory
    maps = {"requirements": {"R-5": {"TC-1", "TC-2"}, "R-6": {"TC-1"}}, "plan_rows": {"TS-5": {"TC-1"}}}
    check_eq("K-A5c(c): R-5 -> TC-1 + TC-2 -> product", owner("traceability: R-5 has no terminal outcome", ["TC-1"], maps), "product")
    check_eq("K-A5c(c) control: R-6 -> TC-1 only -> factory", owner("traceability: R-6 has no terminal outcome", ["TC-1"], maps), "factory")
    check_eq("a plan row resolves the same way", owner("traceability: TS-5 x", ["TC-1"], maps), "factory")
    check_eq("an id that resolves to nothing leaves the owner alone", owner("traceability: R-9 x TC-1", ["TC-1"], maps), "product")
    # K-A5g: POSITION - a `failed:<verdict>` keeps its verdict's owner, the CASE_DEFECT branch answers after it
    check_eq("K-A5g: `failed:APP_BUG` stays the product's though its case is a CASE_DEFECT one",
             owner("ledger: TS-1 is `failed:APP_BUG` (TC-1)", ["TC-1"]), "product")
    check_eq("K-A5g: `failed:CASE_DEFECT` is the factory's by its own verdict", owner("ledger: TS-1 is `failed:CASE_DEFECT` (TC-1)", []), "factory")
    # K-A5h: DIRECTION - only product -> factory: an environment or review family is never turned into the factory's
    check_eq("K-A5h: an environment family stays", owner("handed to the person: TC-1 is taken by hand", ["TC-1"]), "environment")
    check_eq("K-A5h: a review family stays", owner("review: TC-1 has no critic verdict", ["TC-1"]), "review")
    rec = D.reason_record(reason("TC-1"), {"case_defect_cases": ["TC-1"], "cfg": {}})
    check_eq("the record says the owner was established (a finding, not a default)", (rec["owner"], rec["owner_established"]), ("factory", True))
    rec = D.reason_record(reason("TC-1"), {"case_defect_cases": [], "cfg": {}})
    check_eq("... and the unlifted one is the family's product", (rec["owner"], rec["owner_established"]), ("product", True))


def story_with_cases(root: Path, verdicts: dict) -> Path:
    """The good story plus a requirement R-4 (plan row TS-4) whose cases are `verdicts` = {case: triage verdict | None}: each case
    is a failed manual check, `unresolved` in the manifest as `contradicts_requirement`; a verdict gets a triage row."""
    art = root / "qa-factory" / "artifacts" / "QA-1"
    shutil.copytree(GOOD, art)
    work = art / "work"
    register = work / "requirements-register.md"
    register.write_text(register.read_text(encoding="utf-8").replace("ids: [R-1, R-2, R-3]", "ids: [R-1, R-2, R-3, R-4]").replace(
        "| R-3 | The coupon field keeps focus after a rejected submit | story | — | yes | — | expected-contract |",
        "| R-3 | The coupon field keeps focus after a rejected submit | story | — | yes | — | expected-contract |\n"
        "| R-4 | A coupon is refused for a closed cart | ac | — | yes | AC-4 | diff:src/app.py:30 |"), encoding="utf-8")
    plan = work.parent / "test-plan.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace(
        "\n\n## Recommended regression",
        "\n| TS-4 | a closed cart refuses a coupon | R-4 | state @ cart | money | P0 | diff:src/app.py:30 | requirement:R-4 | "
        "`manual-agent` - one-off check | — | api | state verification |\n\n## Recommended regression"), encoding="utf-8")
    text = (work / "test-cases" / "checkout" / "TC-001.md").read_text(encoding="utf-8")
    manifest = json.loads((work / "automation-manifest.json").read_text(encoding="utf-8"))
    report = json.loads((work / "run-report.json").read_text(encoding="utf-8"))
    triage = []
    for case, verdict in verdicts.items():
        (work / "test-cases" / "checkout" / f"{case}.md").write_text(
            text.replace("TC-001", case).replace("status: Automated", "status: Approved").replace("channel: auto", "channel: manual-agent")
            .replace("R-1", "R-4").replace("TS-1", "TS-4"), encoding="utf-8")
        manifest["unresolved"].append({"case": case, "plan_row": "TS-4", "reason": "contradicts_requirement", "detail": "x"})
        report["manual_checks"].append({"case": case, "result": "fail", "evidence": "evidence/tc-002-order-record.txt - x"})
        if verdict:
            triage.append({"case": case, "verdict": verdict, "evidence": "evidence/tc-002-order-record.txt"})
    (work / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (work / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
    (work / "triage.json").write_text(json.dumps({"triage": triage}), encoding="utf-8")
    return art


def traced(shown: dict, owner_word: str) -> list:
    """The summary's reasons of one owner that are the requirement R-4's traceability reason (the 13 unresolved rows)."""
    return [r for r in shown.get(owner_word, []) if "traceability: R-4" in r]


def thirteen_cases_end_to_end() -> None:
    root = temp_project("qa-owner-case-defect-")
    try:
        cases = {f"TC-{n}": "CASE_DEFECT" for n in range(101, 114)}
        art = story_with_cases(root, cases)
        doc = D.assess(art)
        check_eq("K-A5: the verdict stays `no` (FR-35)", (doc["delivery_verdict"], doc["delivery_ready"]), ("no", False))
        shown = DS.build(art)["reasons_by_owner"]
        check_eq("K-A5: no `traceability: R-4` reason (the 13 unresolved rows) is under the product", traced(shown, "product"), [])
        check_eq("K-A5: it is ONE reason, under the factory, and it names the cases", len(traced(shown, "factory")), 1)
        check_in("K-A5: ... naming the first of them", "TC-101", traced(shown, "factory")[0])
        check_in("K-A5: ... and the unresolved row", "unresolved (contradicts_requirement)", traced(shown, "factory")[0])
        check_eq("K-A5: the product block is empty (nothing else is the product's here)", shown.get("product", []), [])
        check_eq("K-A5: the CASE_DEFECT cases are found by the binding (13)", len(D.case_defect_cases(D.gather(art))), 13)
        # K-A5f / E-A6: one of them with another verdict -> the requirement's reason names a case that is not a CASE_DEFECT one -> product
        cases["TC-113"] = "APP_BUG"
    finally:
        cleanup(root)
    root = temp_project("qa-owner-case-mixed-")
    try:
        art = story_with_cases(root, cases)
        doc = D.assess(art)
        check_eq("K-A5f: the verdict stays `no`", doc["delivery_verdict"], "no")
        shown = DS.build(art)["reasons_by_owner"]
        check_eq("K-A5f: the requirement's reason (it resolves to an APP_BUG case too) stays under the product",
                 (len(traced(shown, "product")), traced(shown, "factory")), (1, []))
        check_eq("K-A5f: and the set holds the 12 others only", len(D.case_defect_cases(D.gather(art))), 12)
    finally:
        cleanup(root)
    root = temp_project("qa-owner-case-noverdict-")
    try:
        art = story_with_cases(root, {"TC-101": "CASE_DEFECT", "TC-102": None})
        doc = D.assess(art)
        check_eq("E-A6: a case with no triage row beside a defect one keeps the reason with the product",
                 (len(traced(DS.build(art)["reasons_by_owner"], "product")), doc["delivery_verdict"]), (1, "no"))
    finally:
        cleanup(root)


def coverage_without_a_cause() -> None:
    """K-A6 (RD1-21, E-A8): an obligation with NO cause at all is the coverage projection's gap; a real gap text keeps the red."""
    def reasons(obligation: dict) -> list:
        base = {"obligation_id": "OB-3", "execution_scope": "current_task", "verified": False, "person_debt": False}
        return D.coverage_reasons({"coverage": {"obligations": [dict(base, **obligation)]}})

    got = reasons({"gap": "none"})
    check("K-A6: `{gap: none}` with no state fields -> a `coverage:` reason", len(got) == 1 and got[0].startswith("coverage: OB-3"), str(got))
    check_not_in("K-A6: ... not `coverage red:`", "coverage red", got[0])
    check_in("K-A6: ... it names what is missing and where it comes from (FR-1)", "`execution_state` or `oracle_open` in coverage_contract.py", got[0])
    check_eq("K-A6: its owner is the factory's", D.reason_owner(got[0]), "factory")
    check_eq("K-A6: an empty gap with no state fields too", reasons({"gap": ""})[0].startswith("coverage: OB-"), True)
    check_eq("K-A6: no `gap` key and no state fields too", reasons({})[0].startswith("coverage: OB-"), True)
    check_eq("K-A6 (pins RD1-21): a real gap text with no state fields stays `coverage red:`",
             reasons({"gap": "assert on price"}), ["coverage red: OB-3 — assert on price"])
    check_eq("K-A6: an empty gap with a state is `coverage red:`", reasons({"gap": "", "execution_state": "failed"}), ["coverage red: OB-3 — "])
    check_eq("K-A6: `none` with an oracle field only is still decided by it (open oracle -> red)",
             reasons({"gap": "none", "oracle_open": True}), ["coverage red: OB-3 — none"])
    check_eq("K-A6: `none` with a green run and a closed oracle is `coverage:` as before",
             reasons({"gap": "none", "execution_state": "passed", "oracle_open": False}), ["coverage: OB-3 — none"])
    check_eq("K-A6: verified / person_debt / old scope are still no reason", [
        reasons({"gap": "none", "verified": True}), reasons({"gap": "none", "person_debt": True}),
        reasons({"gap": "none", "execution_scope": "earlier"})], [[], [], []])


def product_gap_carrier() -> None:
    """K-A7 (RN1-15, E-A9): absent -> nothing; one row -> a product reason, `no`, the head names R-n; broken -> [] + a finding."""
    root = temp_project("qa-owner-product-gap-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        base = D.assess(art)
        check_eq("control: the good story delivers", base["delivery_verdict"], "yes")
        check_eq("K-A7: no file -> no record", D.product_gap_records(art), [])
        check_eq("K-A7: ... and no finding (TEMPORAL: before the writer's first run nothing changes)", D.product_gap_findings(art), [])
        check_eq("K-A7: ... the verdict is the base one", D.assess(art)["delivery_verdict"], "yes")

        path = art / "work" / "product-gaps.json"
        path.write_text(json.dumps({"gaps": [
            {"requirement": "R-2", "words": "the total is not recalculated here", "words_ref": "pipeline.json#g1", "gate": "A"},
            {"requirement": "R-2", "words": "a duplicate row is dropped"}]}), encoding="utf-8")
        records = D.product_gap_records(art)
        check_eq("K-A7: one record per requirement", [(r["kind"], r["requirements"]) for r in records], [("product_gap", ["R-2"])])
        check_eq("K-A7: the reason text", records[0]["text"],
                 "product gap: R-2 — the person said the function is not implemented: the total is not recalculated here")
        doc = D.assess(art)
        check_eq("K-A7: the verdict is `no` (FR-21)", (doc["delivery_verdict"], doc["delivery_ready"]), ("no", False))
        recs = [r for r in doc["reason_records"] if r["kind"] == "product_gap"]
        check_eq("K-A7: the reason is under the product, typed", [(r["owner"], r["requirements"], r["words"]) for r in recs],
                 [("product", ["R-2"], "the total is not recalculated here")])
        check_in("K-A7: and in the summary's product block", "product gap: R-2", "\n".join(DS.build(art)["reasons_by_owner"].get("product", [])))
        head = RF._verdict({"ledger": RF._ledger_facts(doc), "requirements": None, "bugs": None, "tests": None})
        check_eq("K-A7: the report's head names R-n (group 3)", (head["first_kind"], head["first_reason_full"]),
                 ("product_gap", "R-2 is not implemented: the total is not recalculated here"))
        check_eq("K-A7: the head's word is the ledger's", head["word"], "no")

        path.write_text("{not json", encoding="utf-8")
        check_eq("K-A7: a broken file -> []", D.product_gap_records(art), [])
        found = D.product_gap_findings(art)
        check_eq("K-A7: ... plus ONE factory finding", [(f["code"], f["owner"]) for f in found], [("PRODUCT_GAPS_UNREADABLE", "factory")])
        check_in("K-A7: ... it names the file and the expected shape (FR-1)", "work/product-gaps.json could not be read whole", found[0]["detail"])
        broken = D.assess(art)
        check_eq("K-A7: the finding reaches the ledger", [f["code"] for f in broken["factory_findings"] if f["code"] == "PRODUCT_GAPS_UNREADABLE"],
                 ["PRODUCT_GAPS_UNREADABLE"])
        check_eq("K-A7: the broken file changes no word (the good story stays `yes`)", broken["delivery_verdict"], "yes")
        for text in ('{"gaps": 3}', '[]', '{"gaps": [{"requirement": "x"}, 5]}'):
            path.write_text(text, encoding="utf-8")
            check_eq(f"K-A7: {text} -> no record for the bad part", [r["requirements"] for r in D.product_gap_records(art)], [])
            check_eq(f"K-A7: {text} -> a finding", len(D.product_gap_findings(art)), 1)
        path.write_text('{"gaps": []}', encoding="utf-8")
        check_eq("K-A7: an empty list is an empty outcome, no finding", (D.product_gap_records(art), D.product_gap_findings(art)), ([], []))
        # data rows (AR-1): the kind and the family are read from the data files
        import delivery_verdict as DV
        check_eq("the kind is a data row: `no`, product", DV.load_kinds()[0]["kinds"]["product_gap"], {"verdict": "no", "owner": "product"})
        check_eq("the family is a data row", D.reason_family("product gap: R-2 — x")["owner"], "product")
    finally:
        cleanup(root)


def main() -> None:
    case_defect_set()
    reason_owner_branch()
    thirteen_cases_end_to_end()
    coverage_without_a_cause()
    product_gap_carrier()
    finish("test_delivery_owner_case_defect")


if __name__ == "__main__":
    main()
