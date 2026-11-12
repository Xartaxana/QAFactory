"""RN1-16 (t-1698 D2-A): the "Because ..." of a `no` names the product's bug first.

`report_facts._verdict` builds the head from candidates; the order is now grouped by owner (1 confirmed bugs, 2 bug drafts,
3 product gaps, 4 reds the product owns, 5 unproven requirements, 6 tests the critic could not verify, 7 reds of the
environment or a review, 8 reds of the factory, 9 the residual). FR-35: only the ORDER of the head changes - every fixture
below asserts that the verdict WORD is the ledger's, unchanged (E-A10).

Mutation (named, NOT run; one killing file, this one):
  m1 report_facts._verdict: delete the line `ranked.sort(key=lambda pair: pair[0])`  -> K-A1, K-A2, K-A3, K-A5
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as CD  # noqa: E402
import report_facts as RF  # noqa: E402


def red(ref: str, verdict: str, owner: str | None = None) -> dict:
    row = {"ref": ref, "detail": "", "verdict": verdict}
    if owner is not None:
        row["owner"] = owner
    return row


def ledger(reds=(), gaps=(), word="no") -> dict:
    return {"word": word, "ready": word == "yes", "owners": {"product": 1}, "limit_windows": 0, "items": [],
            "reds": list(reds), "entities": [], "product_gaps": list(gaps), "factory_coverage": 0}


def draft(ident: str, state: str, reqs: list) -> dict:
    return {"id": ident, "title": "t " + ident, "state": state, "requirements": reqs, "cases": [], "homes": []}


def head(led=None, bugs=None, reqs=None, tests=None) -> dict:
    v = RF._verdict({"ledger": led, "requirements": reqs, "bugs": bugs, "tests": tests})
    if led is not None:       # E-A10 (FR-35): the word is the ledger's, whatever the order says
        check_eq(f"the word stays the ledger's ({led['word']})", (v["word"], v["ready"]), (led["word"], led["word"] == "yes"))
    return v


def req_item(ident: str) -> dict:
    return {"id": ident, "text": "x", "class": "unproven", "priority": 0, "bases": [], "cases": [], "partly": None}


def order_of_reds() -> None:
    # K-A1: a CASE_DEFECT red first in the ledger's own order, an APP_BUG red after it -> the product's red is named
    v = head(ledger([red("TS-1", "CASE_DEFECT", "factory"), red("TS-2", "APP_BUG", "product")]))
    check_in("K-A1: the APP_BUG red is named, not the CASE_DEFECT one before it", "TS-2", v["first_reason"])
    check_eq("K-A1: and it is a ledger failure", v["first_kind"], "ledger_failure")
    # the same without the `owner` field (a ledger facts block built before it): the table is asked, not a copy
    v = head(ledger([red("TS-1", "CASE_DEFECT"), red("TS-2", "APP_BUG")]))
    check_in("K-A1: a red with no owner field is owned through the delivery check's table", "TS-2", v["first_reason"])

    # K-A2: product, then environment/review, then factory (peel one candidate at a time: only the first is exposed)
    fac, env, rev, prod = red("TS-1", "TEST_BUG", "factory"), red("TS-2", "ENV_ISSUE", "environment"), \
        red("TS-3", "ENV_ISSUE", "review"), red("TS-4", "APP_CHANGED", "product")
    check_in("K-A2: product first", "TS-4", head(ledger([fac, env, rev, prod]))["first_reason"])
    check_in("K-A2: then the environment (before the factory)", "TS-2", head(ledger([fac, env, rev]))["first_reason"])
    check_in("K-A2: a review's red keeps its place beside the environment's", "TS-3", head(ledger([fac, rev]))["first_reason"])
    check_in("K-A2: the factory's last", "TS-1", head(ledger([fac]))["first_reason"])
    # an owner word outside the ledger's order is the factory's group (an unknown never outranks a product reason, E-A4)
    check_in("E-A4: an unknown owner word sits with the factory", "TS-4",
             head(ledger([red("TS-9", "WHATEVER", "nobody"), prod]))["first_reason"])

    # K-A4 / E-A2: only the factory's reds -> the first of them, in the ledger's order
    v = head(ledger([red("TS-1", "CASE_DEFECT", "factory"), red("TS-5", "TEST_BUG", "factory")]))
    check_in("K-A4: only factory reds -> the first one is named", "TS-1", v["first_reason"])
    check_not_in("K-A4: ... and not a later one", "TS-5", v["first_reason"])


def drafts_gaps_and_requirements() -> None:
    cased = ledger([red("TS-1", "CASE_DEFECT", "factory")])
    # K-A3: a draft with requirements beats a CASE_DEFECT red
    bugs = {"records": [draft("BUG-1", "unconfirmed", ["R-8", "R-9", "R-10"])]}
    v = head(cased, bugs)
    check_eq("K-A3: the head starts with the draft",
             v["first_reason_full"],
             "BUG-1 is a product bug found by this run, not confirmed yet (R-8, R-9, R-10): t BUG-1")
    check_eq("K-A3: its kind", v["first_kind"], "bug_draft")
    # ... and the CASE_DEFECT red is still a candidate: remove the draft and it is named
    check_in("K-A3: TS-1 is still a candidate, only not first", "TS-1", head(cased)["first_reason"])
    # a draft with NO requirements cannot claim the product (E-A3)
    v = head(cased, {"records": [draft("BUG-2", "unconfirmed", [])]})
    check_in("K-A3: a draft with no requirements is not a candidate", "TS-1", v["first_reason"])
    # gate B: a draft the person did not choose is no candidate; a chosen one, or gate B not decided yet, is
    chosen = dict(draft("BUG-4", "unconfirmed", ["R-4"]), gate_b_not_chosen=False)
    left_out = dict(draft("BUG-4", "unconfirmed", ["R-4"]), gate_b_not_chosen=True)
    check_in("gate B: a chosen draft (or no gate B yet: False) is a candidate", "BUG-4", head(cased, {"records": [chosen]})["first_reason"])
    v = head(cased, {"records": [left_out]})
    check_in("gate B: a draft not chosen is not a candidate (TS-1 is named)", "TS-1", v["first_reason"])
    check_not_in("gate B: ... and BUG-4 is nowhere in the head", "BUG-4", v["first_reason_full"])
    # a confirmed bug outranks a draft; a draft outranks a product gap, which outranks a product red
    both = {"records": [draft("BUG-2", "unconfirmed", ["R-2"]), draft("BUG-3", "confirmed", ["R-3"])]}
    check_in("order 1 before 2: the confirmed bug first", "BUG-3 is a confirmed product bug", head(cased, both)["first_reason"])
    gaps = [{"requirement": "R-7", "words": "the export is not built"}]
    withgap = ledger([red("TS-4", "APP_BUG", "product")], gaps)
    check_eq("order 3: a product gap (RN1-15) names the requirement and the person's words",
             head(withgap)["first_reason_full"], "R-7 is not implemented: the export is not built")
    check_eq("order 3 kind", head(withgap)["first_kind"], "product_gap")
    check_in("order 2 before 3: a draft before the gap", "BUG-2", head(withgap, {"records": [draft("BUG-2", "unconfirmed", ["R-2"])]})["first_reason"])
    check_in("order 3 before 4: with the gap removed the product red is named", "TS-4", head(ledger([red("TS-4", "APP_BUG", "product")]))["first_reason"])
    check_eq("a product gap with no words has no dangling colon", head(ledger(gaps=[{"requirement": "R-7", "words": ""}]))["first_reason_full"],
             "R-7 is not implemented")

    # K-A5: 4 (product red) before 5 (unproven requirement) before 7/8 (the factory's red)
    reqs = {"items": [req_item("R-5")], "counts": {}}
    v = head(ledger([red("TS-1", "CASE_DEFECT", "factory"), red("TS-4", "APP_BUG", "product")]), None, reqs)
    check_in("K-A5: the product's red before the unproven requirement", "TS-4", v["first_reason"])
    v = head(ledger([red("TS-1", "CASE_DEFECT", "factory")]), None, reqs)
    check_in("K-A5: an unproven requirement before the factory's red", "R-5", v["first_reason"])
    check_eq("K-A5: its kind", v["first_kind"], "requirement")
    v = head(ledger([red("TS-2", "ENV_ISSUE", "environment")]), None, reqs, {"unverified": 2})
    check_in("K-A5: the requirement before the tests the critic could not verify", "R-5", v["first_reason"])
    v = head(ledger([red("TS-2", "ENV_ISSUE", "environment")]), None, {"items": [], "counts": {}}, {"unverified": 2})
    check_in("K-A5: tests the critic could not verify (6) before the environment's red (7)", "2 tests could not be verified", v["first_reason"])


def empty_and_words() -> None:
    # E-A1: a `no` with no candidate -> the residual sentence (a `no` always names a reason)
    v = head(ledger())
    check_eq("E-A1: the residual", v["first_kind"], "residual")
    # E-A10: a `yes` and an `after_checks` keep their word whatever the head says; a draft is not a disagreement with a `yes`
    yes = head(ledger([], word="yes"), {"records": [draft("BUG-1", "unconfirmed", ["R-1"])]})
    check_eq("E-A10: a `yes` stays a `yes` beside a draft", (yes["word"], yes["ready"], yes["disagreement"]), ("yes", True, ""))
    after = head(ledger([red("TS-1", "CASE_DEFECT", "factory")], word="after_checks"))
    check_eq("E-A10: an `after_checks` stays one", (after["word"], after["ready"]), ("after_checks", False))
    # the disagreement keeps the old order: a red the ledger's `yes` does not hold, the first of the OLD candidate list
    odd = head(ledger([red("TS-1", "CASE_DEFECT", "factory"), red("TS-2", "APP_BUG", "product")], word="yes"))
    check_in("the disagreement is the first candidate of the old order, unchanged", "TS-1", odd["disagreement"])
    # no ledger at all: nothing breaks and no word is invented
    v = head(None, {"records": [draft("BUG-1", "unconfirmed", ["R-1"])]})
    check_eq("no ledger: no word", v["word"], None)


def owner_reader() -> None:
    # K-A4b
    check_eq("K-A4b: a word outside the table is the factory's", CD.triage_verdict_owner("NOT_IN_TABLE"), "factory")
    check_eq("K-A4b: APP_BUG", CD.triage_verdict_owner("APP_BUG"), "product")
    check_eq("K-A4b: the empty word", CD.triage_verdict_owner(""), "factory")
    check_eq("the table is read through the function (AR-13): same answer for every word of it",
             all(CD.triage_verdict_owner(w) == o for w, o in CD.OWNER_BY_TRIAGE_VERDICT.items()), True)
    # the report holds no copy of the table: its ledger facts carry the owner the function gave
    import ledger as L
    led = {"rows": [{"kind": "plan_row", "ref": "TS-1", "state": "failed:CASE_DEFECT", "detail": ""},
                    {"kind": "plan_row", "ref": "TS-2", "state": "failed:APP_BUG", "detail": ""},
                    {"kind": "plan_row", "ref": "TS-3", "state": "failed:MADE_UP", "detail": ""}],
           "delivery_ready": False, "delivery_verdict": "no", "reasons": [], "reason_records": [], "left_items": []}
    facts = RF._ledger_facts(led)
    check_eq("_ledger_facts: each red carries the owner from the delivery check's table",
             [(r["ref"], r["owner"]) for r in facts["reds"]], [("TS-1", "factory"), ("TS-2", "product"), ("TS-3", "factory")])
    check("the owner order the report ranks by is the ledger's own", tuple(L.OWNER_ORDER) == ("product", "environment", "review", "factory"))
    # RN1-15: the product gaps come from the TYPED part of the reason records
    led["reason_records"] = [{"kind": "product_gap", "requirements": ["R-7"], "words": "not built", "owner": "product",
                              "detail": "product gap: R-7 - x"},
                             {"kind": "red", "requirements": ["R-1"], "words": "ignored", "owner": "product", "detail": "y"}]
    check_eq("_ledger_facts: product_gaps are read from the typed record, not the sentence",
             RF._ledger_facts(led)["product_gaps"], [{"requirement": "R-7", "words": "not built"}])


def main() -> None:
    order_of_reds()
    drafts_gaps_and_requirements()
    empty_and_words()
    owner_reader()
    finish("test_verdict_reason_order")


if __name__ == "__main__":
    main()
