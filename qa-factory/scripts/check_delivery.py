"""Delivery readiness — an aggregator, and nothing else.

It invents no check of its own. Every reason it prints comes from a check that already
exists somewhere else; this script's whole job is to run them all, in one place, and write
one verdict into ledger.json so the gate-B message, the PTR and the MR description all
quote the same sentence.

What it aggregates:
  - check_witness.py on automation-manifest.json (the manifest's own evidence contract)
  - manifest completeness: every `automate` plan row is in tests[] or in unresolved[] with
    a reason from the closed list
  - case lifecycle: a case whose test is approved and green says `Automated` in its own
    frontmatter (the transition the code critic owns)
  - check_traceability.py (requirement -> plan row -> case -> terminal outcome)
  - run-report.json `execution_status`: only `passed` or `failed` may deliver, and `failed`
    only when every failure carries a triage verdict
  - triage.json: a verdict per failure; a FLAKY verdict without `fix_result: fixed` means
    that test is not verified
  - a critic verdict per test (ledger.review_skipped)
  - environment blockers without a recorded decision
  - ledger.subtasks_open

Then it regenerates ledger.json/ledger.md through ledger.py and writes `delivery_verdict` (one of
`yes`, `after_checks`, `no`), `delivery_ready` (the bool: exactly `yes`), `reasons[]` and `left_items[]`
into them. Default is NO: a gap with no decision attached does not deliver.

THE THIRD VERDICT (t-305 N8, PROJECT.md P21). `after_checks` is "ready once you finish the checks left with
you": the factory found no bug and no gap of its own, but part of the checking is the person's (a handed test,
a manual-human case, a manual check that did not answer, a deferral they worded, a stand gap they accepted, a
test the code critic could not verify, an expectation nobody confirmed). It is decided from TYPED records, never
from a reason's text (FR-12): every record this module collects carries a KIND its producer fixes from typed
fields (a ledger state, a triage row's verdict and source, a traceability gap word, the person's recorded
answer), and `delivery_verdict.decide` reads `references/delivery-verdict-kinds.json`. A reason's TEXT only says
what a person reads; its OWNER is still decided by `reason_owner` and the families file.

Usage: check_delivery.py <artifacts-dir> [--json]  — exit 0 `yes`, 1 otherwise (`after_checks` is not `yes`).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import acceptance as AC  # noqa: E402  (the ONE reader of "red by the requirement", AR-13)
import contract as C  # noqa: E402
import delivery_verdict as DV  # noqa: E402
import detector_verdict  # noqa: E402  (the one reader of a detector's output: check_witness.py here)
import ledger as L  # noqa: E402
import proof_level as PL  # noqa: E402
import run_history as RH  # noqa: E402
import waiver  # noqa: E402  (the stand block's one name, and `split_overridden`, the reader of a person's word)

SCRIPTS = Path(__file__).resolve().parent
DELIVERABLE_STATUSES = ("passed", "failed")
# t-305 N8 attempt 2 (F3): the person's decision about a stand-gap `ENV_ISSUE` is read from ONE place: the pipeline's own
# record of their gate B answer (`env_decision`). triage.json is the analyst's file and holds no person's word: a
# `decision` field in it lifts nothing (it used to be a second source, which let a role lift a red test alone).


REASON_CODES = {
    "triage": "TRIAGE_IDENTITY_GAP", "ledger": "LEDGER_TERMINAL_GAP",
    "traceability": "TRACEABILITY_GAP", "coverage": L.COVERAGE_GAP_CODE, "coverage red": L.COVERAGE_GAP_CODE,
    "delivery manifest": "DELIVERY_MANIFEST_GAP", "manual evidence export": "MANUAL_EVIDENCE_GAP",
    "review": "REVIEW_GAP", "factory": "FACTORY_DEFECT",
    "handed to the person": "HANDED_TO_PERSON",
    "deferred without a decision": "DEFERRED_WITHOUT_DECISION",
    "not_executed not re-derived": "NOT_EXECUTED_NOT_RE_DERIVED",
}
# The ledger state of a test the person took over. It is inside the existing vocabulary on
# purpose: `not_executed` is exactly what happened, and the suffix says why — so a reader of
# an older ledger and a reader of this one mean the same thing by the same word. ONE spelling, the ledger's.
HANDED_LEDGER_STATE = L.HANDED_STATE
# Whose problem the typed code is, when the reason carries nothing more specific.
OWNER_BY_CODE = {
    "TRIAGE_IDENTITY_GAP": "factory", "FACTORY_DEFECT": "factory",
    "MANUAL_EVIDENCE_GAP": "factory", "DELIVERY_MANIFEST_GAP": "factory",
    "REVIEW_GAP": "review",
    # Not the product's and not a defect of ours: the environment this factory runs in has no
    # way to launch that profile, and the person said they would run those tests themselves.
    "HANDED_TO_PERSON": "environment",
}
# A ledger row says whose problem it is more exactly than any prefix can. Everything else —
# `not_executed`, `skipped`, `impossible`, `deferred_by_decision`, `subtask_in_progress` —
# is a product behaviour this delivery does not prove, and the person decides about it.
OWNER_BY_LEDGER_STATE = {
    "env_blocked": "environment", "review_skipped": "review", "review_rejected": "review",
    "not_verified_flaky": "factory",
    # `not_verified:oracle_on_refused_base` (TQ1-18): our own test proved nothing, so the unproven
    # thing is the factory's record, not the product (FR-19, AR-27). The prefix is `not_verified`.
    "not_verified": "factory",
    # A verdict the vocabulary does not hold is a defect of our own record, never the critic's
    # rejection (FR-19, FR-35) - and it blocks, like the record it stands for.
    "review_unrecognised": "factory",
    # The code critic could not verify it (D-0013): the person's debt, in the same owner the
    # tests handed to the person are (`HANDED_TO_PERSON`). It never blocks delivery, so no
    # reason carries this state today; the entry keeps the word owned if one ever does.
    "review_unverified": "environment",
}
# `failed:<verdict>` — our test broke, the stand broke, or the product did.
OWNER_BY_TRIAGE_VERDICT = {
    "APP_BUG": "product", "APP_CHANGED": "product",
    "TEST_BUG": "factory", "TEST_BUG:collection": "factory", "FLAKY": "factory",
    "untriaged": "factory", "ENV_ISSUE": "environment",
    "CASE_DEFECT": "factory",
    # The assert asks more than the requirement does, shown by the analyst's control experiment (HF2-18): the person's
    # call (remove the assert, or refine the requirement), in "Left with you" - the product owns the requirement it is
    # measured against, the same owner as the kind `assert_stricter` (references/delivery-verdict-kinds.json).
    "ASSERT_STRICTER": "product",
    # A `failed:NOT_EXECUTED` ledger row is one the delivery check could not place: a manual check that did not
    # answer is the person's debt and reaches the delivery as a TYPED kind (`not_executed_code`, never as a
    # `failed:` state), so a row that DOES read `failed:NOT_EXECUTED` is an analyst's row on a red result, or a forged
    # one - the factory's own defect (t-305 N8, FR-19: `person` is not a word of `contract.DELIVERY_REASON_OWNERS`,
    # and `ledger.reasons_by_owner` filed it under `product`).
    "NOT_EXECUTED": "factory",
    # The manual runner misread its own captures (HF8-19): the check is re-judged by the runner, not run again, and until a new
    # record replaces the result the red stays (`failed:RUNNER_MISREAD_EVIDENCE` -> `red`). A defect of the factory's own
    # reading, never the person's debt and never a product failure: no bug, no draft (FR-19, FR-35).
    "RUNNER_MISREAD_EVIDENCE": "factory",
    # An observation of a manual check that the analyst judged not a bug (P26): it is a row about a doubt, never about a failed
    # test, so it blocks nothing and is no product failure; the word is owned by the factory like every bookkeeping verdict.
    "NO_DEFECT": "factory",
}
LEDGER_STATE_IN_REASON = re.compile(r"is `([^`]+)`")


def triage_verdict_owner(verdict: str) -> str:
    """The owner of a triage verdict word (RN1-16): the ONE reader of `OWNER_BY_TRIAGE_VERDICT`, so the report reads the same
    table the delivery check does (AR-13). A word outside the table is the factory's - the default `_owner_decided` always had:
    an unknown word never outranks a product reason (E-A4)."""
    return OWNER_BY_TRIAGE_VERDICT.get(str(verdict), "factory")


# The owner of a whole family of reasons, by the words the reason always starts with. Data, not
# a phrase list in this file (FR-13): the family and the reason that produces it are written in
# one change, and `reason_owner` asks the table rather than growing a branch. See
# references/delivery-reason-owners.json.
REASON_OWNERS_FILE = "delivery-reason-owners.json"
REASON_REF_RE = re.compile(r"^(?:ledger|manifest record|manifest|blocked on the stand):\s*(\S+)")
# Phrases only the factory's own record-keeping produces. A case version link that went stale
# while the story ran, a proof this build could not re-verify, a row the reducer could not join:
# every one of them is a fact about our bookkeeping, and on TP1-15045 about twenty of them
# were printed to the person under "what blocks delivery on the product side".
FACTORY_BOOKKEEPING_PHRASES = (
    "stale case link", "not pinned by this story", "stale proof or review",
    "pinned caseversion proof", "instance_manifest_join_failed", "ambiguous_attempt_order",
)


def reason_owner_table() -> dict:
    """`references/delivery-reason-owners.json`, or an empty table if it cannot be read.

    An unreadable table means "no family is declared", so every reason falls to the default and
    says so in `classifier_findings` — never a jam and never a silent re-labelling.
    """
    global _REASON_OWNER_TABLE
    if _REASON_OWNER_TABLE is None:
        path = SCRIPTS.parent / "references" / REASON_OWNERS_FILE
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        families = [f for f in (loaded.get("families") or []) if isinstance(f, dict)]
        _REASON_OWNER_TABLE = {
            "default_owner": str(loaded.get("default_owner") or "product"),
            # Longest first: `traceability: requirements-register.md has no r rows` is ours,
            # while `traceability:` on its own is the product's.
            "families": sorted(families, key=lambda f: -len(str(f.get("text_starts") or ""))),
        }
    return _REASON_OWNER_TABLE


_REASON_OWNER_TABLE: dict | None = None


def reason_family(reason: str) -> dict | None:
    """The declared family of this reason text, or None — which is a defect of the classifier."""
    text = str(reason).strip().lower()
    for entry in reason_owner_table()["families"]:
        start = str(entry.get("text_starts") or "").lower()
        if start and text.startswith(start) and entry.get("owner") in C.DELIVERY_REASON_OWNERS:
            return entry
    return None


def classifier_findings(reasons: list) -> list:
    """Reasons no declared family matches: FR-19 calls that a defect of the classifier.

    The owner printed for them is the default, which is a guess; saying so beside the reasons is
    the difference between an honest default and a silent one (FR-41). These findings do not
    block delivery — there is nothing here for the person to repair.
    """
    default = reason_owner_table()["default_owner"]
    out = []
    for reason in reasons:
        text = str(reason)
        if reason_family(text) is not None:
            continue
        out.append({"code": "REASON_OWNER_UNCLASSIFIED",
                    "entity": text.split(":", 1)[0].strip()[:60] or "task",
                    "owner": "factory",
                    "detail": f"factory: no owner family in references/{REASON_OWNERS_FILE} "
                              f"matches \"{text[:120]}\", so it is reported as `{default}` by "
                              "default — add its family there in the change that writes it"})
    return out


def reason_owner(reason: str, code: str = "", context: dict | None = None) -> str:
    """Whose problem this delivery reason is, from `C.DELIVERY_REASON_OWNERS`.

    `delivery_ready: no` used to be one flat list, so "our reducer could not join two of its
    own records" and "this behaviour of the product is unproven" arrived at the person in
    the same voice, and the factory's own defect read as the product not being ready (0.6.0
    feedback on TP2-2530, item 3). The default is `product`, because an unexplained
    gap is a behaviour we did not prove — never a claim that somebody else's tooling failed.

    `context` carries the facts a reason text cannot state about itself: which cases the
    unresolved row that produced them was marked STALE by its own writer, which refs the
    reducer failed to join (both were read as product gaps until 0.7.12), and which CASES have
    nothing left but the reducer's own doubt (`case_ownership`, R-208.6).

    The case-level lift is applied LAST and only to an owner that came out `product`: it may
    turn a product reason into the factory's, never the reverse and never an `environment`,
    `review` or `person` owner into anything (direction: factory where product is the one
    forbidden error, because it would tell the person "not yours" about a behaviour nobody proved).
    """
    owner = _owner_before_lift(reason, code, context)
    if owner == "product" and lifted_cases(reason, context):
        return "factory"
    return owner


def _owner_before_lift(reason: str, code: str = "", context: dict | None = None) -> str:
    """The owner a reason has before the case-level lift; `product` when nothing established one (the safe side)."""
    return _owner_decided(reason, code, context) or "product"


def _owner_decided(reason: str, code: str = "", context: dict | None = None) -> str | None:
    """The owner some rule of the classifier named, or None when the reason fell through every rule (RD1-21, F-3)."""
    text = str(reason)
    lowered_all = text.lower()
    if any(phrase in lowered_all for phrase in FACTORY_BOOKKEEPING_PHRASES):
        return "factory"
    context = context or {}
    factory_refs = context.get("factory_refs") or set()
    ref = REASON_REF_RE.match(text)
    if ref and ref.group(1).strip("`") in factory_refs:
        return "factory"
    # "run result 'partial' is not terminal" is the reducer describing its own join failure,
    # not the product behaving badly — but only when the ref it names is one of ours.
    if ("is not terminal" in lowered_all or "`partial`" in text) and any(
            re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) for name in factory_refs):
        return "factory"
    state = LEDGER_STATE_IN_REASON.search(text)
    if state:
        prefix = C.ledger_state_prefix(state.group(1))
        if prefix == "failed":
            verdict = state.group(1).split(":", 1)[1] if ":" in state.group(1) else ""
            return triage_verdict_owner(verdict)
        if prefix in OWNER_BY_LEDGER_STATE:
            return OWNER_BY_LEDGER_STATE[prefix]
    # RN1-23 (1): a reason that names ONLY cases whose current triage verdict is CASE_DEFECT is the factory's, whatever family
    # its text starts with (`traceability: ... unresolved (contradicts_requirement) with no decision attached` is the product's
    # by family, yet the case's own defect is the factory's: LOCAL-1 printed 13 of them under the product). POSITION: after the
    # ledger-state branch (a `failed:<verdict>` keeps its verdict's owner, which answered above) and before the family table.
    # INVARIANT: this branch only moves product -> factory, and only on evidence (E-A5/E-A6/E-A7): what the family table and
    # the code table below would say is read first, and only `product` (or nothing) is lifted - an environment or review
    # family is never turned into the factory's.
    later = _owner_by_family(text, code)
    if later in (None, "product") and _names_only_case_defects(text, context):
        return "factory"
    return later


def _owner_by_family(text: str, code: str) -> str | None:
    """The owner the family table, the typed code and the last word hints name, or None (the tail of `_owner_decided`)."""
    # The family the text declares is what the person reads, and it is the same answer whether
    # the typed code travels with the reason or not: before this table, `delivery manifest: …`
    # resolved to `factory` through `OWNER_BY_CODE` and to `product` when only the text was
    # handed over, and fourteen of forty-two literals answered differently on the two roads.
    family = reason_family(text)
    if family:
        return str(family["owner"])
    if code in OWNER_BY_CODE:
        return OWNER_BY_CODE[code]
    lowered = text.lower()
    if "env_issue" in lowered or "blocked_by_env" in lowered or "env_blocked" in lowered:
        return "environment"
    if "flaky" in lowered or "test_bug" in lowered:
        return "factory"
    if "critic verdict" in lowered:
        return "review"
    return None


def _reason_code(text: str) -> str:
    return REASON_CODES.get(text.split(":", 1)[0].strip().lower(), "DELIVERY_CONTRACT_GAP")


def reason_record(reason: str, context: dict | None = None) -> dict:
    """Stable typed identity beside the verbatim human reason; no causal link is guessed."""
    text = str(reason)
    code = _reason_code(text)
    entity = text.split(":", 1)[1].strip().split(" ", 1)[0] if ":" in text else text.split(" ", 1)[0]
    owner = reason_owner(text, code, context)
    # F-3: `product` stays the owner of a reason no rule placed, but the record says it was a default and not a finding.
    established = _owner_decided(text, code, context) is not None or owner != "product"
    return {"code": code, "entity": entity or "task", "detail": text,
            "owner": owner, "owner_established": established, "refs": reason_refs(text, context)}


def reason_refs(text: str, context: dict | None = None) -> list:
    """The ids a reason names, typed (HF8-17, M-F, FR-12: presence of an id, never wording): its case ids (the project's own form),
    the plan rows (`TS-n`), the requirements (`R-n`) and any instance of the factory's own set (`factory_refs`) it names as a whole
    word. The `entity` of a record is only the first word after the colon (`approved`, `test`, `its`), so it cannot say which
    requirement a factory reason is about; the report reads THIS (`report_facts._count_bookkeeping`, AR-22)."""
    context = context or {}
    found = list(C.case_ids(text, cfg=context.get("cfg")))
    found += TS_IN_TEXT.findall(text) + REQ_IN_TEXT.findall(text)
    found += [name for name in sorted(context.get("factory_refs") or ())
              if name and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text)]
    return list(dict.fromkeys(found))


def factory_owned_refs(artifacts: Path) -> set:
    """The cases and instances whose delivery reason is our bookkeeping, not the product.

    Two sources, both written by the factory about itself: an `unresolved[]` row its own
    writer marked STALE (on TP1-15045 "TC-014 blocked_by_env" was stale the moment it was
    written, and the person was asked to decide about it anyway), and every result row the
    reducer could not join to a manifest instance — which is what turned eighteen green tests
    into fourteen `partial` rows nobody could act on.
    """
    from traceability import is_stale_unresolved
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    report = C.load_json(C.artifact(artifacts, "run-report.json"))
    refs = {str(entry.get("case") or "") for entry in C.manifest_unresolved(manifest)
            if is_stale_unresolved(entry)}
    for finding in report.get("factory_findings") or []:
        if isinstance(finding, dict) and str(finding.get("code") or "").startswith("INSTANCE_MANIFEST_JOIN"):
            refs.add(str(finding.get("entity") or ""))
    for row in C.current_instance_results(report).values():
        if str(row.get("current_reason") or "") in REDUCER_REASONS:
            refs.add(str(row.get("instance_id") or ""))
    refs.discard("")
    return refs


# The reducer's own words for "I could not decide this from my own records".
REDUCER_REASONS = ("instance_manifest_join_failed", "ambiguous_attempt_order", "invalidated_evidence")
JOIN_FAILED = REDUCER_REASONS[0]  # the one reason whose row also keeps `raw_status` (finalize_task, R-208.3)

# --- the owner of a reason, lifted to the case level (t-109 R-208.6) ---------------------------------
#
# `factory_owned_refs` answers for an INSTANCE a reason names, but a reason names a plan row, a case
# or a requirement: on cmp1 a case whose only non-green rows were ghosts the reducer could not join
# (8 of them, all under TC_002) still read `product`, so the person was asked about a behaviour whose
# only gap was our own bookkeeping. The ids are read where they stand in the text (a presence check,
# FR-12); what they map to comes from the story's own records, never from wording:
#   plan row -> cases : the `Plan row:` line of each case file (the map `completeness_reasons` walks),
#                       and `plan_row` of the manifest's `unresolved[]`;
#   requirement -> cases : the `Requirements:` line of each case file (the map `check_traceability`
#                       walks), and the cases of the plan rows whose R column names it;
#   case -> its rows : `current_results[]` (and `current_manual_checks[]`) by the row's `case`, the
#                       case ids inside its identity, its `case_version_links` and the manifest's
#                       links of its instance. TWIN of finalize_task._ghost_cases: a change to one
#                       names the other.
# Direction: a case is the factory's only when that is PROVEN; every doubt leaves it `product`.
TS_IN_TEXT = re.compile(r"(?<![\w-])TS-\d+(?![\w-])")
REQ_IN_TEXT = re.compile(r"(?<![\w-])R-\d+(?![\w-])")


def _case_rows(report: dict, manifest: dict, cfg: dict) -> tuple:
    """`(current, history)`: `{case: [{"status", "reason", "row"}]}` for the rows that decide now, and
    `{case: [row]}` for every product row the reducer kept (superseded ones included)."""
    links = C.manifest_instance_links(manifest, cfg)

    def cases_of(row: dict) -> set:
        identity = str(row.get("instance_id") or row.get("test_instance_id") or "")
        return (set(C.case_ids(row.get("case"), cfg=cfg)) | set(C.case_ids(identity, cfg=cfg))
                | set(C.manifest_test_links(row, cfg)) | links.get(identity, set()))

    current: dict = {}
    for row in C.current_instance_results(report).values():
        for case in cases_of(row):
            current.setdefault(case, []).append(
                {"status": C.result_status(row), "reason": str(row.get("current_reason") or ""), "row": row,
                 "manual": False})
    manual = report.get("current_manual_checks") if isinstance(report.get("current_manual_checks"), list) \
        else report.get("manual_checks") or []
    for row in manual:
        if isinstance(row, dict) and row.get("case"):
            for case in set(C.case_ids(row.get("case"), cfg=cfg)) | {str(row["case"])}:
                current.setdefault(case, []).append(
                    {"status": C.result_status({"status": row.get("result")}),
                     "reason": str(row.get("current_reason") or ""), "row": row, "manual": True})
    history: dict = {}
    for row in C.product_result_rows(report):
        for case in cases_of(row):
            history.setdefault(case, []).append(row)
    return current, history


def _case_map(artifacts: Path, manifest: dict, cfg: dict) -> tuple:
    """`(plan_rows, requirements, cases, plan)`: `{TS: {cases}}`, `{R: {cases}}`, `{case: its index
    entry}`, and the plan's rows. Both maps come from the story's records (see the block above)."""
    index = C.case_index(artifacts)
    plan = C.parse_plan(C.artifact(artifacts, "test-plan.md"))
    cases = {str(meta.get("case_id") or key): meta for key, meta in index.items()}
    plan_rows: dict = {}
    requirements: dict = {}
    for cid, meta in cases.items():
        if meta.get("plan_row"):
            plan_rows.setdefault(str(meta["plan_row"]), set()).add(cid)
        for req in meta.get("requirements") or []:
            requirements.setdefault(str(req), set()).add(cid)
    for entry in C.manifest_unresolved(manifest):
        if entry.get("plan_row"):
            plan_rows.setdefault(str(entry["plan_row"]), set()).update(C.manifest_test_links(entry, cfg))
    for row in plan:
        for req in row.get("requirements") or []:
            requirements.setdefault(str(req), set()).update(plan_rows.get(str(row.get("ts")), set()))
    return plan_rows, requirements, cases, plan


def _world_gaps(report: dict, manifest: dict, cfg: dict, cases: dict, plan: list) -> set:
    """Cases whose "not proven" is NOT only the reducer's doubt: an impossible or environment-blocked
    row, an unresolved row nobody marked stale, a manual-human case with no evidence package."""
    from traceability import is_stale_unresolved
    gaps = set(C.run_impossible(report))
    for entry in C.manifest_unresolved(manifest):
        if not is_stale_unresolved(entry):
            gaps |= set(C.manifest_test_links(entry, cfg))
    for row in report.get("current_env_blocked") or []:
        if isinstance(row, dict):
            gaps |= set(C.case_ids(row.get("case"), cfg=cfg))
    evidence = C.manual_human_evidence(report)
    handed = {str(row.get("ts")) for row in plan if row.get("disposition") == "manual-human"}
    gaps |= {cid for cid, meta in cases.items() if str(meta.get("plan_row") or "") in handed and not evidence.get(cid)}
    return gaps


def case_ownership(artifacts: Path) -> dict:
    """`{"factory_cases": {case: [reducer reasons]}, "plan_rows", "requirements", "cfg", "notes"}`.

    A case is the factory's when ALL of these hold (R-208.6 with the critic's override, factory-fixes
    P2): it has at least one current row that is not passed, and every such row carries a reducer reason
    (`REDUCER_REASONS`); a join-failed row also carries `raw_status`, and that is not red (an old report
    has none: never lifted); nothing in the story says the case is a gap of the world (`_world_gaps`);
    and no row that ever belonged to the case holds a red by the ONE red rule (`run_history.red_blocks`,
    t-108 R5/R5a) - an answered red does not count as answered here, which only widens "product".
    A case with no current row at all is NOT lifted: nothing says the reducer is why it has none.

    Nothing raises: a record that cannot be read leaves every owner as it was and adds a NOTE, which
    `assess` files as a finding the person reads (FR-41). Writes nothing (FR-45)."""
    artifacts = Path(artifacts)
    out = {"factory_cases": {}, "plan_rows": {}, "requirements": {}, "cfg": {}, "notes": []}
    try:
        _fill_case_ownership(artifacts, out)
    except Exception as exc:
        out["factory_cases"] = {}
        out["notes"] = ["the factory could not work out which cases are only its own bookkeeping "
                        f"({type(exc).__name__}: {str(exc)[:160]}), so every reason keeps the owner it had"]
    return out


def _fill_case_ownership(artifacts: Path, out: dict) -> None:
    cfg = out["cfg"] = C.case_config(artifacts)
    report = C.load_json(C.artifact(artifacts, "run-report.json"))
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    current, history = _case_rows(report, manifest, cfg)
    passed = ("passed", "pass")
    # Cheap first: a story with no reducer row pays for nothing else and owes no note.
    candidates = sorted(case for case, rows in current.items()
                        if any(r["status"] not in passed and r["reason"] in REDUCER_REASONS for r in rows))
    if not candidates:
        return
    out["plan_rows"], out["requirements"], cases, plan = _case_map(artifacts, manifest, cfg)
    if not cases and not plan:
        out["notes"].append("the story has no test plan and no case files, so nothing maps a plan row, a case "
                            "or a requirement to its cases, and every reason keeps the owner it had")
        return
    gaps = _world_gaps(report, manifest, cfg, cases, plan)
    survivors = {}
    for case in candidates:
        if C.names_case(gaps, case, cfg):
            continue
        doubt = [r for r in current[case] if r["status"] not in passed]
        if any(r["reason"] not in REDUCER_REASONS for r in doubt):
            continue  # a genuine partial / failed / not_run / skipped row: the product's until proven otherwise
        if any(r["reason"] == JOIN_FAILED and ("raw_status" not in r["row"]
                                               or C.result_status({"status": r["row"]["raw_status"]}) in RH.RED_STATUSES)
               for r in doubt):
            continue  # an old report (no `raw_status`) or a red the join overwrote
        survivors[case] = sorted({r["reason"] for r in doubt})
    if not survivors:
        return
    # The history, once, through the ONE block reader and the ONE red rule. A block the reader cannot
    # read may hold the red: that is "history unreadable" (a note). A row that names no test function
    # cannot be looked up: that case stays `product`, which is today's answer.
    try:
        blocks, unreadable = RH.read_run_blocks(artifacts)
        if unreadable:
            raise ValueError("run blocks that are not a readable JSON object: " + ", ".join(unreadable[:3]))
        raw_reports: dict = {}
        for case in list(survivors):
            keys = {RH.function_key(row.get("test_id"), row.get("instance_id") or row.get("test_instance_id"))
                    for row in history.get(case, []) + [r["row"] for r in current[case] if not r["manual"]]}
            if "" in keys or any(RH.red_blocks(artifacts, key, blocks, raw_reports) for key in keys):
                del survivors[case]
    except Exception as exc:
        out["notes"].append("the factory could not read the story's run history "
                            f"({type(exc).__name__}: {str(exc)[:160]}), so no reason was re-labelled as its own "
                            "bookkeeping and every reason keeps the owner it had")
        return
    out["factory_cases"] = survivors


def _named_cases(text: str, maps: dict, cfg, with_areas: bool = False) -> list | None:
    """F6 (t-1753): every case a reason text names, directly or through a plan row (`TS-n`) / requirement (`R-n`) it names,
    resolved by `maps` (`{"plan_rows": {TS: {cases}}, "requirements": {R: {cases}}}`). None when an id resolves to nothing (the
    owner is then left alone, E-A5/E-A6); a text naming no id gives []. `with_areas`: the direct cases keep the area the text
    spells before them (`_case_keys_in`), else they are bare ids. The ONE id-resolution loop of `lifted_cases` and
    `_names_only_case_defects`."""
    named: list = []
    for pattern, table in ((TS_IN_TEXT, maps.get("plan_rows") or {}), (REQ_IN_TEXT, maps.get("requirements") or {})):
        for ident in pattern.findall(text):
            if not table.get(ident):
                return None
            named += sorted(table[ident])
    return named + (_case_keys_in(text, cfg) if with_areas else list(C.case_ids(text, cfg=cfg)))


def lifted_cases(reason: str, context: dict | None) -> list:
    """The cases that make this reason the factory's (sorted), or [] when they do not.

    Every id the text names (plan row, requirement, case) resolves to its cases and ALL of them must be
    in `case_ownership`'s `factory_cases`; an id that resolves to nothing, or no id at all, leaves the
    owner alone. A `failed:<verdict>` ledger state is a verdict somebody passed on the product: never
    lifted."""
    lift = (context or {}).get("case_lift")
    if not isinstance(lift, dict) or not lift.get("factory_cases"):
        return []
    text = str(reason)
    state = LEDGER_STATE_IN_REASON.search(text)
    if state and C.ledger_state_prefix(state.group(1)) == "failed":
        return []
    cfg = lift.get("cfg") or {}
    found = _named_cases(text, lift, cfg, with_areas=True)
    named = set(found or ())
    # F6 (t-1753, RD1-2): a named case is the factory's by the identity match, not by raw equality (a bare `TC-1` against the
    # factory case `web/TC-1` is one case; two areas never match)
    return sorted(named) if named and all(C.names_case(lift["factory_cases"], n, cfg) for n in named) else []


def case_defect_cases(facts: dict) -> list:
    """RN1-23 (1): the case keys whose CURRENT triage verdict is `CASE_DEFECT` and no other (sorted), else [].

    One binding, no new triage reader: every verdict word of `triage.json` goes through `_triage_binding`
    (`contract.bind_triage` - the attempt rule included: a row of an older attempt binds nothing). A case is in the list only
    when EVERY row bound to any of its failures says exactly `CASE_DEFECT` (the word is compared exactly). The key carries the
    case's area when the story's case index spells it (`web/TC-1`); a bare id the index spells under several areas is dropped,
    because the failure cannot say which one it was. ERROR DIRECTION (advice -> owner gate): every doubt leaves the case out,
    which leaves its reason under the product; a triage record or an index that cannot be read gives []."""
    try:
        by_case: dict = {}
        for verdict in sorted({str(row.get("verdict") or "") for row in facts["triage"]}):
            for _row, cases, _keys in _triage_binding(facts, verdict):
                for case in cases:
                    by_case.setdefault(case, set()).add(verdict)
        keys: dict = {}
        for key in facts["index"]:
            keys.setdefault(_bare(key), []).append(str(key))
        out = []
        for case, verdicts in by_case.items():
            if verdicts != {"CASE_DEFECT"} or len(keys.get(case, [])) > 1:
                continue
            out.append(keys[case][0] if case in keys else case)
        return sorted(out)
    except Exception:  # noqa: BLE001
        return []


def case_defect_maps(artifacts: Path, facts: dict, lift: dict | None = None) -> dict:
    """`{"plan_rows": {TS: {cases}}, "requirements": {R: {cases}}}` for the reasons that name a plan row or a requirement
    instead of a case; {} when the story's records cannot be read (such a reason is then never lifted). `lift` is
    `case_ownership`'s result: when it already holds the two maps they are reused, not built a second time (F6 t-1753)."""
    if isinstance(lift, dict) and (lift.get("plan_rows") or lift.get("requirements")):
        return {"plan_rows": lift["plan_rows"], "requirements": lift["requirements"]}
    try:
        plan_rows, requirements, _cases, _plan = _case_map(artifacts, facts["manifest"], facts["cfg"])
        return {"plan_rows": plan_rows, "requirements": requirements}
    except Exception:  # noqa: BLE001
        return {}


def _case_keys_in(text: str, cfg) -> list:
    """The cases a text names, each with the area the text spells before it (`api/TC-1` -> `api/TC-1`), else bare. A compound
    cell `TC-1/TC-2` is not an area (`contract.split_case_key` refuses it)."""
    keys = []
    for cid in C.case_ids(text, cfg=cfg):
        key = cid
        hit = re.search(r"(?<![\w./\\-])((?:[\w.-]+/)+)" + re.escape(cid) + r"(?![\w-])", text)
        if hit and C.split_case_key(hit.group(1) + cid, cfg=cfg)[0]:
            key = hit.group(1) + cid
        keys.append(key)
    return keys


def _names_only_case_defects(text: str, context: dict | None) -> bool:
    """True when the reason names at least one case (directly, or through a plan row / requirement it names) and EVERY one of
    them is in `context["case_defect_cases"]` by `contract.case_matches`, in both directions. No id at all, an id that
    resolves to nothing, one case with another verdict or none, an empty list: False (E-A5, E-A6, E-A7)."""
    context = context or {}
    defects = context.get("case_defect_cases")
    if not defects:
        return False
    cfg = context.get("cfg") or {}
    named = _named_cases(text, context.get("case_defect_maps") or {}, cfg, with_areas=True)
    return bool(named) and all(
        any(C.case_matches(d, n, cfg=cfg) and C.case_matches(n, d, cfg=cfg) for d in defects) for n in named)


def owner_lift_findings(reasons: list, context: dict) -> list:
    """The interim "the person is told, not asked" (R-208.6, FR-3): one finding per case whose reasons
    were re-labelled as the factory's, and the notes of a lift that could not be made. They go through
    the findings road (`doc["factory_findings"]`) until the report says it in its own verdict block (P7).
    They block nothing: the reasons themselves still stand in `reasons[]`, so the requirement stays
    not proven."""
    lift = context.get("case_lift") or {}
    out = [{"code": "OWNER_LIFT_NOTE", "entity": "task", "owner": "factory", "detail": "factory: " + note}
           for note in lift.get("notes") or []]
    count: dict = {}
    for reason in reasons:
        if _owner_before_lift(reason, _reason_code(str(reason)), context) == "product":
            for case in lifted_cases(reason, context):
                count[case] = count.get(case, 0) + 1
    for case, number in sorted(count.items()):
        out.append({"code": "OWNER_LIFTED_TO_FACTORY", "entity": case, "owner": "factory",
                    "detail": f"factory: {case} is not proven, and the reason is ours: every result of it that is "
                              "not green is one the factory's own reducer could not settle, and no run of it ever "
                              f"failed. {number} delivery reason(s) that name it are listed under the factory's "
                              "defects and are not put to you as a product question; the behaviour stays unproven "
                              f"until its test is run again (`run_suite.py --mine {case}`)"})
    return out


def delivery_manifest_reasons(artifacts: Path, finalized: bool = False) -> list:
    """Validate an S8 compact-record manifest when one was prepared.

    S8 prepares this list before S9 exists, so a preliminary manifest must not claim a
    future retro.  The explicit final-delivery mode requires that later S9 addition and
    verifies its hash like every other selected record.

    A row the build marked `volatile` is checked for presence and canonical path and not for
    its hash: `state/events.jsonl`, the ledger and the reduced reports are rewritten by
    acceptance, waivers and the reducer AFTER the manifest was assembled, and on
    TP2-2553 that arrived at the person as four tampering findings against records the
    factory had just written itself. Everything else still answers for its bytes.
    """
    artifacts = Path(artifacts).resolve()
    path = artifacts / "state" / "delivery-manifest.json"
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"delivery manifest: unreadable ({type(exc).__name__}: {exc})"]
    rows = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return ["delivery manifest: files must be a list"]
    from delivery_manifest import build
    try:
        approved = {row["path"] for row in build(artifacts).get("files", [])}
    except (ValueError, OSError) as exc:
        return ["delivery manifest: " + str(exc)]
    reasons, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            reasons.append("delivery manifest: file entry must be an object")
            continue
        raw = row.get("path")
        if not isinstance(raw, str) or not raw or "\\" in raw:
            reasons.append(f"delivery manifest: invalid path {raw!r}")
            continue
        target = (artifacts / raw).resolve()
        normalized = target.relative_to(artifacts).as_posix() if target.is_relative_to(artifacts) else ""
        if normalized != raw or raw in seen:
            reasons.append(f"delivery manifest: non-canonical or duplicate path {raw!r}")
            continue
        seen.add(raw)
        if raw not in approved:
            reasons.append(f"delivery manifest: {raw} is raw evidence or not an approved compact record; "
                           f"rebuild it: delivery_manifest.py --task-root {artifacts} --output {artifacts}/state/delivery-manifest.json")
            continue
        if not target.is_file():
            reasons.append(f"delivery manifest: selected file is missing: {raw}")
            continue
        if row.get("volatile") is True or raw in C.DELIVERY_VOLATILE_PATHS:
            continue
        actual = __import__("hashlib").sha256(target.read_bytes()).hexdigest()
        if row.get("sha256") != actual:
            reasons.append(f"delivery manifest: stale hash for {raw}")
    if finalized and "retro.md" not in seen:
        reasons.append("delivery manifest: finalized delivery requires current retro.md from S9")
    return reasons


def witness_reasons(artifacts: Path) -> list:
    manifest = C.artifact(artifacts, "automation-manifest.json")
    if not manifest.exists():
        return ["automation-manifest.json is missing — S5 produced no manifest to check"]
    try:
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_witness.py"), str(manifest)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=120)
    except Exception as e:
        return [f"check_witness.py could not be run ({type(e).__name__}: {e})"]
    if out.returncode == 0:
        return []
    lines = detector_verdict.flatten(detector_verdict.parse(out.returncode, out.stdout, out.stderr))
    return ["manifest witness: " + ln for ln in lines] or ["manifest witness: check_witness.py rejected it"]


def _completeness(artifacts: Path) -> list:
    """`[(sentence, kind, case)]`: the manifest-and-plan contract of our own record. The KIND is fixed here, by the
    field that produced the sentence (never read back from it, FR-12): `env_undecided` for a `blocked_by_env` row,
    `impossible` for an `impossible` one, `factory_record` for everything else (R1)."""
    plan_rows = C.parse_plan(C.artifact(artifacts, "test-plan.md"))
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    cases = C.case_index(artifacts)
    cfg = C.case_config(artifacts)
    # Every case an instance proves, not only its singular `case`: a consolidated test names
    # its second and third case in `covers[]` (TP1-13797: `covers: ["TC-001", "TC-007"]`),
    # and reading `case` alone called those cases untested beside a green test of them.
    # RD1-2 (S-5): the keys keep the area a writer knew (`manifest_test_keys`), so an area case is not "tested" by another
    # area's test: `manifest_test_links` strips it and `web/TC-7` would meet the test of `api/TC-7`
    tested = {case for t in C.manifest_tests(manifest) for case in C.manifest_test_keys(t, cfg)}
    unresolved = {str(u.get("case")): str(u.get("reason") or "") for u in C.manifest_unresolved(manifest)}
    out = []
    for reason_case, reason in unresolved.items():
        if not C.unresolved_reason_ok(reason):
            out.append((f"manifest record: {reason_case} unresolved with reason '{reason}' "
                        f"outside {list(C.UNRESOLVED_REASONS)} + deferred_by_decision:<gate>", "factory_record", ""))
        elif reason == "blocked_by_env":
            out.append((f"blocked on the stand: {reason_case} is held by the stand and waits for your answer on its stand-gap card at gate B",
                        "env_undecided", reason_case))
        elif reason == "impossible":
            out.append((f"manifest: {reason_case} is impossible and carries no gate decision",
                        "impossible", reason_case))
    for row in plan_rows:
        if row.get("disposition") != "automate":
            continue
        row_cases = [cid for cid, meta in cases.items() if meta.get("plan_row") == row["ts"]]
        if not row_cases:
            out.append((f"plan {row['ts']} is `automate` but no case names it as its plan row", "factory_record", ""))
            continue
        for case in row_cases:
            # RD1-2 (S-5, B-357): `case` is a `case_index` key (`web/TC-002` with an area), `tested` holds bare ids and an
            # `unresolved[]` row may carry either spelling - the identity match (`contract.case_matches`), not raw
            # membership, which called an area case "neither in tests[] nor in unresolved[]" beside its own test. A blank
            # case matches nothing (E-B1).
            if not (C.names_case(tested, case, cfg) or C.names_case(unresolved, case, cfg)):
                out.append((f"plan {row['ts']}: case {case} is `automate` but is neither in "
                            "automation-manifest tests[] nor in unresolved[]", "factory_record", ""))
    return out


def completeness_reasons(artifacts: Path) -> list:
    return [text for text, _kind, _case in _completeness(artifacts)]


def completeness_records(artifacts: Path, facts: dict | None = None) -> list:
    """`completeness_reasons` as typed records (t-305 N8). Every sentence is the manifest-and-plan contract of our own
    record (R1: `factory_record`), with ONE exception: a `blocked_by_env` row ("blocked on the stand: ... waits for your answer on its stand-gap card at gate B") stays open until the person
    gives the stand gap a CLOSED answer (`env_decision`: change, myself, run, accept). That answer IS the gate decision the
    sentence asks for, so with it the row is no reason at all - the ledger and the traceability table already carry the
    third verdict's kind for it (`env_accepted`, `handed`, `env_change_pending`); without it the row is an undecided
    stand gap (`env_undecided`), which says `no`. An `impossible` row stays a reason (L9).

    B-361: the answer may be the person's gate A `accept` carried under the case key. When it no longer covers the case
    (a red run, a build change, runs that cannot be read, a later word - `facts["changed"]`, from `gather`), the
    `env_undecided` sentence says so in its own words, so the person is told what changed instead of "no decision"."""
    facts = facts or gather(artifacts)
    changed = facts.get("changed") if isinstance(facts.get("changed"), dict) else {}
    out = []
    for text, kind, case in _completeness(artifacts):
        if kind == "env_undecided" and env_option_of_case(_bare(case), facts):
            continue
        if kind == "env_undecided" and changed.get(_bare(case)):
            text += f" - your answer at gate A no longer covers it: {changed[_bare(case)]}"
        out.append({"text": text, "kind": kind, "case": "", "ref": "", "source": "check"})
    return out


def _cases_held(artifacts: Path, manifest: dict) -> set:
    """The cases (bare ids) the stamp cannot give `Automated` to: at least one LIVE manifest instance of the case has a non-empty
    `case_stamp.instance_hold` - not green, red in the run (t-416), no green run row of its own (HF3-1: the manifest's green is
    the automator's word before the run), or not approved. The SAME predicate the stamp and the coverage map ask (AR-13, AR-15;
    `case_stamp.run_rows_of` builds the index with the live entries, so the legacy join is alive). A case is held whole - one
    held instance holds the case, as it holds its stamp. A dead row (`SUPERSEDED DUPLICATE`) neither holds nor demands.
    RAISES when the join cannot be built (a build that cannot load it, a broken predicate): the caller names what it could not
    establish (`lifecycle_reasons`, critic t-1254 M1) - holding every case or none would be a guess in the gate's own words."""
    import case_stamp as CS
    return CS.held_case_links(manifest, CS.run_rows_of(Path(artifacts), manifest), C.case_config(Path(artifacts)))


def _pinned_proof_reasons(cid: str, test: dict, version: str) -> list:
    """A pinned case keeps its reviewed frontmatter; its proof is the manifest's exact CaseVersion link on the test."""
    links = [item for item in test.get("case_version_links") or [] if isinstance(item, dict)]
    if any(str(item.get("case_id")) == cid and str(item.get("version")) == version for item in links):
        return []
    return [f"case {cid}: approved green test lacks current pinned CaseVersion proof"]


def _stamp_transition_reasons(cid: str, meta: dict) -> list:
    """A legacy mutable case whose test is approved and green must read `Automated` in its frontmatter."""
    status = C.case_status(meta["path"])
    if status == C.CASE_AUTOMATED:
        return []
    return [f"case {cid}: its test is approved and green, but the case file still says "
            f"`{status or 'no status'}` — the Draft -> Automated transition "
            "(qa-code-critic, step 8b) never happened, and the coverage map counts "
            "automated cases from that frontmatter"]


def lifecycle_reasons(artifacts: Path) -> list:
    """An approved green test needs exact lifecycle evidence for its case version.

    Immutable pinned cases retain their reviewed frontmatter and use an exact manifest
    CaseVersion proof. Legacy mutable cases use the `Draft -> Automated` transition. The
    state machine in validate_artifacts.py guards its SHAPE (`Automated` needs `red_probe`
    and `automated_by`) — but nothing required the transition to happen at all. On
    TP2-2386 fifteen of sixteen cases were automated, approved and green while every
    case file still read `Draft`, so the coverage map, which counts this frontmatter,
    reported zero automated cases beside a passing suite. Two documents disagreeing about
    the same fact is exactly what this aggregator exists to refuse.

    The stamp is demanded only of a case the stamp can give (`_cases_held`, `case_stamp.instance_hold`, HF3-1): a case with a
    held instance asks nothing here, because its own reason lives elsewhere (ledger `failed:*` / `not_executed:` / `review_*`).
    When the hold cannot be computed, ONE reason says so (FR-59) instead of guessing for every case."""
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    cases = C.case_index(artifacts)
    cfg = C.case_config(artifacts)      # F8 (t-1753, RD1-2): handed / pinned / held are read by the identity match, not the raw key
    pinned = {str(link.get("case_id")): str(link.get("version")) for link in C.story_case_links(artifacts)}
    handed = {key for row in handed_rows(artifacts)
              for key in (row["case"], row.get("case_id") or row["case"])}
    from traceability import live_tests   # lazy: a dead row (`SUPERSEDED DUPLICATE`) neither holds a case nor demands its stamp
    try:
        held, not_read = _cases_held(artifacts, manifest), ""
    except Exception as exc:   # the join could not be built: name it below, hold neither every case nor none (FR-59)
        held, not_read = None, f"{type(exc).__name__}: {exc}"
    undecided = False
    reasons = []
    for test in live_tests(manifest):
        verdict = str(test.get("critic_verdict") or "")
        green = str(test.get("status") or "") == "green"
        if verdict not in ("approved", "approved_with_fixes") and not green:
            continue
        if L.is_unverified(test):
            # D-0013: the critic could not complete the proof, so no receipt exists to stamp the
            # case Automated (`case_stamp`). That is the person's debt (`review_unverified`, listed
            # in "Left with you"), not a lifecycle contradiction that blocks delivery.
            continue
        for cid in C.manifest_test_links(test):
            if C.names_case(handed, cid, cfg):
                # `Automated` in a case's front matter means a green test with a red probe
                # behind it. A handed case has neither and must not claim otherwise.
                continue
            meta = C.case_lookup(cases, cid, cfg, rollup=False)
            if not meta:
                continue
            pin = C.case_lookup(pinned, cid, cfg, rollup=False)
            if pin is not None:
                reasons += _pinned_proof_reasons(cid, test, pin)
                continue
            if held is None:
                # the join is unbuilt: whether the stamp can be given is unknown, so no stamp is demanded here and the
                # gap is named once below - never a pass in silence, never a stamp the stamp may not give
                undecided = True
                continue
            if C.names_case(held, cid, cfg):
                # t-416 / HF3-1: `case_stamp` does not stamp a case while any of its instances is held (`instance_hold`: not
                # green, a red run - the run outranks the manifest's word -, no green run row of its own, not approved), so
                # the stamp this reason asks for cannot be given until that is repaired - the sentence would be false and its
                # door shut (FR-2, FR-5). The hold is never dropped, each kind has its carrier: a red run is its own `no`
                # reason (a `failed:*` ledger row, a triage gap, a non-terminal result); an unrun test is a `not_executed:`
                # ledger row; an unapproved one a `review_*`. A `skipped` row is the exception (A-1, critic t-1276): the ledger
                # reads it `skipped:` (kind `decided_elsewhere`, verdict `none`), so what keeps the verdict `no` is the trace
                # chain (`result:skipped` -> `chain_broken`), pinned by test_check_delivery (A-K5).
                continue
            reasons += _stamp_transition_reasons(cid, meta)
    if undecided:
        reasons.append("case lifecycle not checked: the run join could not be read "
                       f"({not_read}); the package install is broken - repair it, then run gate B again")
    return reasons


def _sensitivity_state(test: dict, manifest: dict, artifacts: Path) -> tuple:
    """`(issues, obligation_id)` after looking in BOTH places a probe may have written.

    `red_sandbox.py --probe` of 0.7.9 published the receipt as `obligation_bindings[].
    probe_receipt_ref` and nothing else, while this aggregator read
    `tests[].sensitivity_proof.receipt_ref`. Four hash-bound receipts sat on disk and gate B
    of TP2-2553 asked the person for four waivers over `product`-owned missing proof.
    The binding names a file; it does not vouch for it, so the receipt is validated either
    way. The obligation id comes back so the reason — or the factory finding, when the
    receipt is good — can name where the proof actually was.

    What a receipt is, which of two is better and whether it is for these bytes is
    `proof_level.reached` (FR-17): this function only adds the obligation that names the
    binding's place. A higher level than the one required is never a reason."""
    binding = C.binding_receipt_ref(manifest, test, artifacts)
    obligation = str(binding.get("obligation_id") or "") if binding else ""
    issues = PL.reached(test, manifest, artifacts)["issues"]
    if issues:
        return issues, obligation
    # Valid: the obligation is named only when the binding is the only place that proves it.
    if obligation and PL.reached(test, {}, artifacts)["issues"]:
        return [], obligation
    return [], ""


def binding_proof_findings(artifacts: Path) -> list:
    """Instances whose sensitivity is proven, but only through the obligation binding.

    That is a defect of the probe's publishing, not of the test and not of the product: the
    proof ran, the receipt is current and hash-bound, and the only thing missing is the row
    the probe should have written beside it. It is surfaced with `owner: factory` and it does
    NOT block delivery — nothing here is the person's to repair."""
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    out = []
    for test in C.manifest_tests(manifest):
        # The one predicate: a handed test is never required, an unchanged one neither.
        if not PL.proof_required(test, manifest):
            continue
        issues, obligation = _sensitivity_state(test, manifest, artifacts)
        if issues or not obligation:
            continue
        instance = C.test_instance_id(test)
        out.append({"code": "FACTORY_DEFECT", "entity": instance, "owner": "factory",
                    "detail": f"factory: test instance {instance} proves its sensitivity through "
                              f"obligation binding {obligation} only — the probe did not write "
                              "tests[].sensitivity_proof"})
    return out


def case_version_reasons(artifacts: Path) -> list:
    """Pinned CaseVersions are evidence, not a convenient pointer to mutable case text."""
    reasons = list(C.case_link_issues(artifacts))
    links = C.story_case_links(artifacts)
    if not links:
        return reasons  # legacy story: readable, but it has no versioned delivery contract
    pinned = {str(link.get("case_id")): str(link.get("version")) for link in links}
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    # HF2-3 (FB-3 (a), N3, N9): a test that is RED against a requirement (a `contradicts_requirement` row names it and its
    # CURRENT result in the run report is `failed`) is the product's bug, not a test short of a live check: it gets no
    # "requires current sensitivity proof" line (F9). ONE call of the reader before the loop, from the same report
    # `ledger.build` reads (source (v-a)); a report that cannot be read, a current `passed`, a red with no row and a row
    # about another instance are all "not red", i.e. the line stays - the allowed error direction (FR-59).
    red = AC.red_by_requirement(manifest, [{"instance_id": C.test_instance_id(t)} for t in C.manifest_tests(manifest)],
                                AC.story_scope(manifest), artifacts,
                                report=C.load_json(C.artifact(artifacts, "run-report.json")))
    for test in C.manifest_tests(manifest):
        for cid in C.manifest_test_links(test):
            if cid not in pinned:
                reasons.append(f"test instance {C.test_instance_id(test)} links case {cid} not pinned by this story")
        for link in test.get("case_version_links") or []:
            if not isinstance(link, dict):
                continue
            cid, version = str(link.get("case_id") or ""), str(link.get("version") or "")
            if cid and pinned.get(cid) != version:
                reasons.append(f"test instance {C.test_instance_id(test)} has stale case link {cid}/{version}")
        # A live check is a RUN, and nothing here can run a handed one. Asking for the proof
        # anyway would print the factory's own missing toolchain as the person's debt; the
        # pinning and staleness checks above still apply to the code that WAS written. That
        # exemption lives in `proof_required`, the one predicate (D-0012: an unchanged test is
        # exempt too).
        # An unverified test (D-0013, which wins over "an absent live check blocks") has no proof
        # to ask for: it is the person's debt, listed in "Left with you", and never a reason here.
        if PL.proof_required(test, manifest) and not L.is_unverified(test) and C.test_instance_id(test) not in red:
            issues, obligation = _sensitivity_state(test, manifest, artifacts)
            where = (f" (looked in tests[].sensitivity_proof and in obligation binding "
                     f"{obligation})" if obligation else "")
            for issue in issues:
                reasons.append(f"test instance {C.test_instance_id(test)} requires current "
                               f"sensitivity proof{where}: {issue}")
        # A stale REQUIRED live check is refused just above (`PL.reached`). The former manifest-flag reader that
        # stood here, removed in RH1-9, read stored fields nothing in the factory wrote; whether a review is still
        # current at delivery after an edit outside the scope is an open finding (E8), not a stored flag.
    return reasons


def handed_rows(artifacts: Path) -> list:
    """`[{case, profile, what}]` — the tests this story handed to the person, from the
    manifest's own `unresolved[]` rows. One list, read by the ledger, the summary and gate B."""
    try:
        return C.handed_tests(C.load_json(C.artifact(artifacts, "automation-manifest.json")))
    except Exception:
        return []


PERSON_CHECKS = "person_checks"


def person_check_rows(artifacts: Path) -> list:
    """`[{case, case_id, detail, what}]` - the manual-agent cases whose `request.json` carries `refused.by: person_checks`: the
    person chose to check them by hand when the stand could not be reached (C1-6b writes the key), so they are handed in the
    same sense a manifest `handed_to_person` row is (P21's third outcome). The detail is the refusal's own words. A case whose
    request says another `by`, or none, is not here: its row keeps the kind it has. Never raises."""
    try:
        import manual_capture as MC
        index = C.case_index(artifacts)
    except Exception:
        return []
    out = []
    for key in index:
        try:
            refused = C.load_json(MC.case_root(artifacts, key) / "request.json").get("refused")
        except ValueError:     # a case id the evidence folder cannot be named for
            continue
        if isinstance(refused, dict) and refused.get("by") == PERSON_CHECKS:
            said = " - ".join(" ".join(str(refused.get(part) or "").split()) for part in ("reason", "door")
                              if str(refused.get(part) or "").strip())
            out.append({"case": key, "case_id": _bare(key), "detail": said or "check it by hand",
                        "what": said or "check it by hand"})
    return out


def mark_handed(doc: dict, artifacts: Path) -> dict:
    """Restate every ledger row of a handed case as `not_executed:handed_to_person`, with what
    the person runs as its detail.

    The row is never PASS and never reads as an unproven product behaviour: nothing about the
    product was in question, the factory simply had no way to launch it here. The detail
    carries the file and the command, so the one place a reader looks for "what is left" is
    also the place that says how to do it (TP2-2536). A case the person took by hand at a refused
    stand (`person_check_rows`) is restated the same way, once: a row already handed is left as it is."""
    rows = person_check_rows(artifacts) + handed_rows(artifacts)   # the manifest's own row, which names a command, wins a tie
    if not rows:
        return doc
    what = {}
    for row in rows:
        for key in {row["case"], row.get("case_id") or row["case"]}:
            what[key] = row["detail"] or row["what"]
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    cfg = C.case_config(artifacts)
    by_instance = {}
    for test in C.manifest_tests(manifest):
        for case in set(C.manifest_test_links(test)) | {str(test.get("case") or "")}:
            if C.names_case(what, case, cfg):
                by_instance[C.test_instance_id(test)] = case
    for row in doc.get("rows") or []:
        ref = str(row.get("ref") or "")
        case = by_instance.get(ref) or (ref if ref in what else "")
        detail = str(row.get("detail") or "")
        if not case:
            case = next((c for c in what if c and c in detail), "")
        # t-305 N8 attempts 2-3 (F1, G1, P21): a hand-off is a promise about a check NOBODY RAN, so it restates only a row
        # that says exactly that: an ALLOW-list, state prefix `not_executed`. Every observed result and every review
        # verdict (`failed*`, `partial`, `error`, `review_rejected`, `review_unrecognised`, `not_verified_flaky`,
        # `passed_green`, `waived*`, and any state not known today) keeps its own state and so its own kind. INVARIANT: no row of
        # kind `no` becomes kind `handed`.
        if not case or C.ledger_state_prefix(row.get("state", "")) != "not_executed":
            continue
        row["state"] = HANDED_LEDGER_STATE
        row["detail"] = f"{case}: {what[case]}"
    return doc


def handed_reasons(artifacts: Path) -> list:
    """One delivery reason for the whole handover, with the exact list to run.

    One reason and not N: the person already decided this, and repeating it per test would
    read as N new problems. `delivery_ready` still says no — nothing proved those behaviours."""
    rows = handed_rows(artifacts)
    if not rows:
        return []
    listed = "; ".join(f"{row['case']}: {row['detail'] or row['what'] or 'no command recorded'}"
                       for row in rows)
    return [f"handed to the person: {len(rows)} test(s) nothing here could run — {listed}"]


def _stricter_cases(facts: dict) -> frozenset:
    """The bare case ids whose triage row is ASSERT_STRICTER AND carries a well-formed control experiment
    (`contract.triage_control_problems` empty - the same reader as the validator): the traceability chain lets such a red
    that the automator handed over with `contradicts_requirement` end in its failed result, whose ledger row is the person's
    line (HF2-18). ERROR DIRECTION: anything unreadable or malformed is simply not in the set - the chain stays broken (`no`)."""
    try:
        return frozenset(c for row, cases, _keys in _triage_binding(facts, "ASSERT_STRICTER")
                         if not C.triage_control_problems(row, facts["artifacts"]) for c in cases)
    except Exception:
        return frozenset()


# The kind a `failed:ASSERT_STRICTER` ledger row falls back to when no case of it holds the word with a well-formed experiment
# (`delivery-verdict-kinds.json`: verdict `no`): the red reads as the product failure it would be without the word.
RED_KIND = "red"


def _stricter_scope(cases: list, stricter: frozenset) -> list:
    """The cases of a `failed:ASSERT_STRICTER` ledger row that really are the word's: those in `stricter`
    (`_stricter_cases`, the one computation). The ledger gives a PLAN row the verdict of its first failed case and
    `row_cases` lists every case of the row, so a green, handed or differently triaged neighbour is not the word's."""
    return [c for c in cases if c in stricter]


def _red_cases(doc: dict, facts: dict, stricter: frozenset, kinds_doc: dict) -> set:
    """The bare case ids of the ledger's observed failures (any `failed:*` row but the stand's ENV_ISSUE): a whole-case
    `handed` record of such a case is dropped by `assess` (F1, P21). t-1339 B1: of a `failed:ASSERT_STRICTER` row only the
    word's own cases (`_stricter_scope`) went red BECAUSE of it, so a handed neighbour on the same plan row keeps its item;
    a row with no case holding the word is a plain red - all its cases, as before."""
    red: set = set()
    for row in doc.get("rows") or []:
        if C.ledger_state_prefix(row.get("state", "")) != "failed" or row.get("state") == "failed:ENV_ISSUE":
            continue
        cases = row_cases(row, facts)
        if DV.kind_of_state(row.get("state"), kinds_doc) == "assert_stricter":
            cases = _stricter_scope(cases, stricter) or cases
        red.update(cases)
    return red


def _code_row_ok(case: str, facts: dict) -> tuple:
    """`(True, "")` when the manual check of this case did not answer AND code's own triage row for it is exactly what S7
    would write again; else `(False, why)` naming which condition failed (t-305 N8, F2; the three conditions hold for
    the SAME row):
      1. the triage row bound to the case's manual failure has `source == "code"` (exact equality, as
         `s7_pretriage.is_code_row` reads it) and `verdict == "NOT_EXECUTED"`;
      2. its binding (`contract.bind_triage`) is to a MANUAL failure whose current result is `inconclusive`;
      3. `s7_pretriage.rederives` is true from the live record.
    ERROR DIRECTION: False is the only wrong answer - `no` plus a finding that names the row."""
    import s7_pretriage as S7
    report, manifest, rows = facts["report"], facts["manifest"], facts["triage"]
    failures, _unnamed = C.triage_failures(report)
    bound = C.bind_triage(failures, rows)["matched"]
    bare = _bare(case)
    keys = [k for k in failures if k[0] == "manual" and (bare in {_bare(n) for n in failures[k]["names"]})]
    if len(keys) != 1:
        return False, "no single manual failure of the run report names the case"
    answers = bound.get(keys[0]) or []
    if len(answers) != 1:
        return False, "no single triage row answers its manual check" if not answers else \
            f"{len(answers)} triage rows answer its manual check"
    row = answers[0]
    if len([k for k, rows_ in bound.items() if any(r is row for r in rows_)]) != 1:
        return False, "the row names more than one failure"
    if not S7.is_code_row(row):
        return False, "the row is not code's own (`source` is not exactly `code`)"
    if str(row.get("verdict") or "") != "NOT_EXECUTED":
        return False, "the row's verdict is not NOT_EXECUTED"
    _list, failing = S7.failing_manual_rows(report)
    checks = failing.get(keys[0]) or []
    if not checks or any(C.result_status({"status": r.get("result") or r.get("status")}) != "inconclusive"
                         for r in checks):
        return False, "the manual check did not end inconclusive"
    if not S7.rederives(row, report, manifest, rows):
        return False, "S7's code would not write this row again from the record (the evidence, the attempt, a " \
                      "contradicts_requirement row or an analyst's row says otherwise)"
    return True, ""


def _question_open_to_check(artifacts: Path, requirement: str, qid: str) -> str:
    """A3: what the person is left with when a plan row waits for a gate A question: `answer Q3 (R-13): <the question, first
    120 characters>`. With no question id (the plan or the register could not be read) it says so by name (FR-41): nothing is
    invented. The text is the register's own `question` field, read here, never composed from wording."""
    if not qid:
        return f"the plan or its questions could not be read for {requirement}"
    text = ""
    try:
        import question_register as QR
        for question in QR.load(artifacts).get("questions") or []:
            if isinstance(question, dict) and str(question.get("id") or "").strip() == qid:
                text = " ".join(str(question.get("question") or "").split())[:120]
                break
    except Exception:  # noqa: BLE001
        text = ""
    return f"answer {qid} ({requirement})" + (f": {text}" if text else "")


def traceability_records(artifacts: Path, facts: dict | None = None) -> list:
    """The traceability gaps as typed records: `[{text, kind, case, ref, requirements, source}]`. One record per
    requirement that reaches no terminal outcome: when EVERY case of it without an outcome is a kind that says
    `after_checks` (a handed test, a manual-human case, an expectation nobody confirmed, a stand gap the person
    answered, a manual check code can prove did not answer), the row is the person's debt and carries no reason
    (one item per case); any other case makes the row's reason a `no` kind, with the sentence a person reads (T1-T8).
    The register with no R rows is its own `no`."""
    from check_traceability import walk
    facts = facts or gather(artifacts)
    result = walk(artifacts, _stricter_cases(facts))
    if not result["requirements"]:
        return [{"text": "traceability: requirements-register.md has no R rows — nothing was traced",
                 "kind": "chain_broken", "case": "", "ref": "register", "requirements": [], "source": "traceability"}]
    doc = DV.load_kinds()[0]
    out = []
    for row in result["rows"]:
        if row["outcome"]:
            continue
        text = f"traceability: {row['requirement']} has no terminal outcome ({row['detail'][:120]})"
        kinds, entries = [], []
        for gap in row.get("gaps") or []:
            case, word = _bare(gap.get("case") or ""), str(gap.get("gap") or "")
            option = env_option_of_case(case, facts) if case else ""
            code_ok, why = False, ""
            if word == "result:inconclusive" and case:
                code_ok, why = _code_row_ok(case, facts)
            kind = DV.kind_of_gap(word, doc, env_option=option, code_row=code_ok)
            if kind is None:
                kind = f"trace_gap:{word}"      # a gap word the file does not hold: `decide` reads it as `no` and says so
            kinds.append(kind)
            entries.append((case, word, kind, option))
            if kind == "not_executed_unproven" and case:
                # F2: a check that did not answer and that code could not prove it would close - said by name, owned
                # by the factory (`not_executed not re-derived:` family), beside the requirement's own reason below
                out.append({"text": f"not_executed not re-derived: {case} did not answer, and {why}; it is not shown as "
                                    "'the person will check'", "kind": "not_executed_unproven", "case": case,
                            "ref": case, "requirements": [row["requirement"]], "source": "traceability"})
        if not kinds:
            kinds = ["trace_gap:none"]
            entries = [("", "none", "trace_gap:none", "")]
        if all(DV.verdict_of_kind(k, doc) == "after_checks" for k in kinds):
            for (case, word, kind, option), gap in zip(entries, row.get("gaps") or [None] * len(entries)):
                record = {"text": "", "kind": kind, "case": case, "ref": case or row["requirement"],
                          "requirements": [row["requirement"]], "source": "traceability",
                          "gap": word, "option": option}
                if word == "question_open":
                    record["to_check"] = _question_open_to_check(artifacts, row["requirement"], (gap or {}).get("question") or "")
                out.append(record)
        else:
            bad = next(k for k in kinds if DV.verdict_of_kind(k, doc) != "after_checks")
            out.append({"text": text, "kind": bad, "case": "", "ref": row["requirement"],
                        "requirements": [row["requirement"]], "source": "traceability"})
    return out


def run_reasons(artifacts: Path) -> list:
    report = C.load_json(C.artifact(artifacts, "run-report.json"))
    if not report:
        return ["run-report.json is missing — S6 produced no run to deliver"]
    status = str(report.get("execution_status") or "")
    if status not in C.EXECUTION_STATUS:
        return [f"run-report.json: execution_status '{status}' outside {list(C.EXECUTION_STATUS)}"]
    if status not in DELIVERABLE_STATUSES:
        if status == "not_executed" and _s6_closed_by_code(artifacts):
            # t-305 N8 (Q19, R3): S6 closed on a code-only receipt - there was nothing to execute, or everything was
            # handed to a person - and `not_executed` is what S6 left on purpose. The run decides nothing here: the
            # cases decide, each through its own typed kind (a handed case is the third verdict, a plan row nobody
            # answers is `no`). Without that receipt the status is the refusal it always was.
            return []
        return [f"run-report.json: execution_status is '{status}' — only "
                f"{list(DELIVERABLE_STATUSES)} can deliver"]
    return []


def _s6_closed_by_code(artifacts) -> bool:
    """S6's own receipt (`stages.S6.code_only` of the controller), read by the one reader S7 uses. A controller that
    cannot be read is False: a doubt never lets a run that did not execute through."""
    try:
        import s7_pretriage
        return bool(s7_pretriage.s6_closed_by_code(artifacts))
    except Exception:
        return False


def _triage_failures(report: dict) -> tuple:
    """`({(kind, name): {"names", "attempts"}}, [notes])` - every failure that needs a verdict. A thin call of
    `contract.triage_failures` (t-323 A1: the reading moved to the contract, so every reader binds the same units)."""
    return C.triage_failures(report)


def _bind_triage(failures: dict, rows: list) -> tuple:
    """`({failure: [rows]}, [(row names, [failures])])` - which row is the verdict of which failure. A thin call of
    `contract.bind_triage`, the ONE binding S7, the reducer, the ledger, the traceability table and the dashboard
    read too (t-323 A1; the ladder and its invariant are written there)."""
    got = C.bind_triage(failures, rows)
    return got["matched"], got["ambiguous"]


# --- the typed facts the verdict is decided from (t-305 N8) ----------------------------------------------------------

def gather(artifacts) -> dict:
    """The records every typed reader below shares, read once: manifest, run report, triage rows, the pipeline's own
    words (waivers and the stand-gap answers), the plan, the case index. Nothing here is a reading of anybody's wording
    (FR-12): fields, ids and closed words. A record that cannot be read is `{}`/`[]`, which every reader treats as
    "nothing is known", the direction of `no`."""
    artifacts = Path(artifacts)
    pipeline = C.load_json(artifacts / "pipeline.json")
    try:
        index = C.case_index(artifacts)
    except Exception:
        index = {}
    try:
        cfg = C.case_config(artifacts)
    except Exception:
        cfg = {}
    plan = C.parse_plan(C.artifact(artifacts, "test-plan.md"))
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    # B-361 (D-0026, FR-7, FR-10): a gate A `accept` carried under the case key (stage S5) settles the case only while
    # nothing recorded since says otherwise - the SAME rules the gate B card applies (`stand_gaps.delivery_decisions`);
    # `changed` = {bare case id: what changed} for the sentence. A view that cannot be built drops every S5 record: the
    # case is read as undecided, as it was before the carry existed - never a pass.
    changed: dict = {}
    try:
        import stand_gaps
        decisions, changed = stand_gaps.delivery_decisions(artifacts, pipeline, manifest)
    except Exception:
        decisions = {k: v for k, v in C.stand_gap_decisions(pipeline).items() if str(v.get("stage") or "") != "S5"}
    return {"artifacts": artifacts, "pipeline": pipeline, "cfg": cfg, "index": index, "plan": plan,
            "dispositions": {str(r.get("ts")): str(r.get("disposition") or "") for r in plan},
            "manifest": manifest,
            "report": C.load_json(C.artifact(artifacts, "run-report.json")),
            "triage": C.triage_rows(C.load_json(C.artifact(artifacts, "triage.json"))),
            "decisions": decisions, "changed": changed}


def _bare(case) -> str:
    try:
        return C.split_case_key(str(case))[1] or str(case)
    except Exception:
        return str(case)


def _decisions_for_case(case: str, decisions: dict, cfg=None) -> list:
    """The stand-gap answers (`contract.stand_gap_decisions`: {gap key: {option, words, at}}) that are about this case:
    the key is the case's own key (`area/TC-007`) or the bare id the key ends in. Several gaps may share a number; the
    caller decides what disagreement means."""
    bare = _bare(case)
    return [entry for key, entry in (decisions or {}).items()
            if key == case or _bare(key) == bare or C.case_matches(key, bare, cfg=cfg)]


def env_decision(case_key: str, decisions: dict, cfg=None) -> str:
    """The CLOSED answer (`apply`, `theirs`, `handed`, `accept`) the person recorded about the stand gap of this case,
    else "" (t-305 N8, F5; attempt 2, F3). ONE source: the gate B waiver of the case (`stand gap: <key>`, written by
    `story_run.take_stand_gap_answers` - the pipeline's own record of the person's answer): its `option` is the first
    word of the answer when that word is one of `contract.STAND_GAP_OPTIONS`; prose in `authorization_source` is never
    read. B-361 [meaning]: the one source is still the case-KEY record, and `gather` is what puts it there - the gate B
    waiver of the case, or the gate A answer the driver carried under the case key (`stand gap: <case>`, stage S5) while
    `stand_gaps.carried_change` finds nothing that moved since the person gave it. A precondition id (`PC-1`) never
    names a case: this function does not read the gate A gap record itself. The triage row's `decision` field is NOT a source: triage.json is the analyst's file, not the person's.
    ERROR DIRECTION: "" ("undecided") is the only wrong answer this may give. Gaps of one case that disagree, or a case
    that two gaps share with only one answered, are "" too."""
    found = _decisions_for_case(case_key, decisions, cfg)
    options = {str(e.get("option") or "") for e in found}
    if found and len(options) == 1 and options <= set(C.STAND_GAP_OPTIONS):
        return next(iter(options))
    return ""


def _failure_cases(key: tuple, failure: dict, facts: dict) -> list:
    """The bare case ids a failure of `contract.triage_failures` stands for: a manual check's own `case` name; a result
    failure's instance names looked up in the manifest (an alias or the `test` of a test, whose links are the cases) and in
    the run report's own failed rows (their `case`, `case_version_links`). Ids, never wording."""
    names = set(failure["names"])
    cases: list = []
    report = facts["report"] if isinstance(facts["report"], dict) else {}
    if key[0] == "manual":
        checks = report.get("current_manual_checks") or report.get("manual_checks")
        for row in checks if isinstance(checks, list) else []:
            if isinstance(row, dict) and names & {str(row.get(k) or "") for k in ("case", "instance_id", "test")}:
                cases.append(_bare(row.get("case") or ""))
    for test in C.manifest_tests(facts["manifest"]):
        if names & (set(C.instance_id_aliases(test)) | {str(test.get("test") or "")}):
            cases += [_bare(c) for c in C.manifest_test_links(test, facts["cfg"])] + [_bare(test.get("case") or "")]
    for row in report.get("current_results") if isinstance(report.get("current_results"), list) else \
            list(C.current_instance_results(report).values()):
        if isinstance(row, dict) and names & {str(row.get(k) or "") for k in ("instance_id", "test_instance_id", "test_id", "test")}:
            cases += [_bare(c) for c in C.manifest_test_links(row, facts["cfg"])] + [_bare(row.get("case") or "")]
    return [c for c in dict.fromkeys(cases) if c]


def _triage_binding(facts: dict, verdict: str) -> list:
    """`[(triage row, [bare case ids], [failure keys])]` for every row of triage.json whose verdict is `verdict`
    (`ENV_ISSUE`: the stand gap's cards; `ASSERT_STRICTER`: its item of "Left with you", HF2-18), bound to the failures
    of the run report by `contract.bind_triage` - THE binding (F2, FR-7/FR-57): a gate B answer recorded for a case is
    found for every row that binding gives the case, whatever fields the row carries (`case`, an alias, a `test`). A row the
    binding gives no failure has no cases: the caller says it could not be matched, never a silent pass."""
    failures, _unnamed = C.triage_failures(facts["report"])
    bound = C.bind_triage(failures, facts["triage"])["matched"]
    out = []
    for row in facts["triage"]:
        if str(row.get("verdict") or "") != verdict:
            continue
        keys = [k for k, rows in bound.items() if any(r is row for r in rows)]
        cases = [c for k in keys for c in _failure_cases(k, failures[k], facts)]
        out.append((row, [c for c in dict.fromkeys(cases) if c], keys))
    return out


def env_option_of_case(case: str, facts: dict) -> str:
    return env_decision(case, facts["decisions"], facts["cfg"])


def row_cases(row: dict, facts: dict) -> list:
    """The bare case ids a ledger row stands for: a plan row's cases (the case files that name it, and the manifest
    entries that point at it), a test row's links. Ids, never wording."""
    ref = str(row.get("ref") or "")
    cases: list = []
    if row.get("kind") == "plan_row":
        for key, meta in facts["index"].items():
            if str(meta.get("plan_row") or "") == ref:
                cases.append(str(meta.get("case_id") or _bare(key)))
        for entry in C.manifest_tests(facts["manifest"]) + C.manifest_unresolved(facts["manifest"]):
            if str(entry.get("plan_row") or "") == ref:
                cases += [_bare(c) for c in C.manifest_test_links(entry, facts["cfg"])]
    else:
        for test in C.manifest_tests(facts["manifest"]):
            if ref and ref in C.instance_id_aliases(test):
                cases += [_bare(c) for c in C.manifest_test_links(test, facts["cfg"])] + [_bare(test.get("case") or "")]
    return [c for c in dict.fromkeys(cases) if c]


def triage_reasons(artifacts: Path) -> list:
    report = C.load_json(C.artifact(artifacts, "run-report.json"))
    triage = C.load_json(C.artifact(artifacts, "triage.json"))
    facts = gather(artifacts)
    reasons = []
    failures, unnamed = _triage_failures(report)
    matched, ambiguous = _bind_triage(failures, C.triage_rows(triage))
    competing = {key for _names, keys in ambiguous for key in keys}
    for (kind, name), rows in matched.items():
        if kind == "result" and len(rows) > 1:
            # t-323 F1: more than one row for ONE failure is its own refusal (it used to read "no verdict", the wrong
            # reason): the same words S7 uses
            reasons.append(f"triage: {len(rows)} rows answer the failure {name} in triage.json; keep one")
            continue
        if (kind == "result" and len(rows) != 1) or (kind == "manual" and not rows):
            if not rows and (kind, name) in competing:
                continue   # the row that names it twice speaks below; this failure is not "unjudged", it is unassigned
            # t-319 (t-311 Q1): a manual check nobody judged is the review's to settle, not the factory's own
            # bookkeeping - the one `triage:` reason that has the person's side in it, so its own family prefix
            # (`references/delivery-reason-owners.json`, `triage:manual:` -> review); every other `triage:` stays factory.
            reasons.append(("triage:manual:" if kind == "manual" else "triage:")
                           + f" the failure {name} has no verdict in triage.json"
                           + (" (a row answers it when it names it exactly, or the same id with or without its "
                              "`[param]` group, and carries its attempt - a row with no attempt answers only the "
                              "latest attempt of the instance, never an older one)" if kind == "result" else ""))
    # P26 / RN1-10 (AR-28): an observation of a manual check (`<case>#obs<n>`, whatever its check's result) with no verdict is a
    # factory-side gap of its own - never a pass, and never the person's to settle; the analyst answers it with a row
    for (kind, name), rows in matched.items():
        if kind == "observation" and not rows and (kind, name) not in competing:
            reasons.append(f"triage: the observation {name} of a manual check has no verdict in triage.json (a row answers it "
                           "when it names it exactly, `<case>#obs<n>`; the analyst judges it like a failed Then)")
    for row in facts["triage"]:
        for problem in C.triage_no_defect_problems(row, report, artifacts):
            reasons.append(f"triage: {row.get('instance_id') or row.get('test') or row.get('case') or '?'}: {problem}")
    manual_notes = C.triage_targets(report)["unnamed_manual"]
    for note in unnamed:
        if note in manual_notes:
            reasons.append(f"triage:manual: a failed or inconclusive manual check has no verdict in triage.json - {note}, "
                           "so no row can name it")
        else:
            reasons.append(f"triage: a failed result row has no verdict in triage.json - {note}, so no row can name it")
    for names, keys in ambiguous:
        reasons.append(f"triage: the row {' / '.join(names) or '?'} names {len(keys)} failures "
                       f"({', '.join(sorted(name for _kind, name in keys))}) and is a verdict for none of them; "
                       "write one row per failure, under that failure's own instance id")
    for row in facts["triage"]:      # the SAME row objects `_triage_binding` binds (identity, not equality)
        test = str(row.get("instance_id") or row.get("test") or row.get("case") or "?")
        verdict = str(row.get("verdict") or "")
        if verdict not in C.TRIAGE_VERDICTS:
            reasons.append(f"triage: {test} carries verdict '{verdict}' outside the matrix")
        if verdict == "FLAKY" and row.get("fix_result") != "fixed":
            reasons.append(f"triage: {test} is FLAKY and was not fixed "
                           f"(fix_result: {row.get('fix_result') or 'none'}) — it is not verified; "
                           "quarantine is a human decision at gate B, with a debt and a trigger")
        if verdict == "ASSERT_STRICTER":
            # the word lowers the delivery from `no` to a line left with the person, so it travels only with its own
            # experiment: without it the red reads as a product failure (the direction of `no`; the same reader as the
            # validator, `contract.triage_control_problems`, so the two never disagree about the form)
            problems = C.triage_control_problems(row, artifacts)
            if problems:
                reasons.append(f"triage: {test} is ASSERT_STRICTER without its control experiment ({problems[0]}); "
                               "until the row carries it the red reads as a product failure")
        if verdict == C.TRIAGE_MISREAD_VERDICT:
            # the word keeps the red and sends a paid re-judge, so it travels only with its own block (the same reader as the
            # validator and the S7 re-judge, `contract.triage_contradiction_problems`); a refused row is a plain red
            problems = C.triage_contradiction_problems(row, artifacts)
            if problems:
                reasons.append(f"triage: {test} is {C.TRIAGE_MISREAD_VERDICT} without its contradiction ({problems[0]}); "
                               "until the row carries it the red stands as the runner recorded it")
        if verdict == "ENV_ISSUE":
            state = _env_row_state(row, facts)
            if state == "unbound":
                reasons.append(f"triage: {test} is ENV_ISSUE, and the row could not be matched to a case of the run (it "
                               "names no failing test the run recorded), so the answer to its stand gap cannot be found")
            elif state == "undecided":
                reasons.append(f"triage: {test} is ENV_ISSUE with no recorded decision "
                               f"(the closed answers are {_env_words()})")
        # the fields of the red-then chain (R4 `diagnostic`, R6 `blocked_thens`/`blocking_check`): the SAME readers as the
        # validator (AR-13), so the form the analyst was told is the form the delivery reads; a bad block is a factory
        # record and the Then it names is not shown as waiting (`triage_blocked_rows` skips a malformed entry)
        for problem in C.triage_diagnostic_problems(row, artifacts):
            reasons.append(f"triage: {test}: {problem}")
        for problem in C.triage_blocked_problems(row, artifacts, facts["triage"], report):
            reasons.append(f"triage: {test}: {problem}")
    # a manifest row that records a Then behind a check although that Then ran and failed (the run and the manifest tell
    # two stories about one Then, FR-10): the person is never shown "check after X" beside a `failed` of the same Then
    try:
        stale = C.red_blocked_rows(facts["manifest"], report, facts["cfg"] or None)
    except Exception:
        stale = []
    for row in stale:
        reasons.append(f"triage: the manifest records Then {row.get('then')} of {row.get('case')} behind a check, but it ran "
                       f"and failed on {row.get('instance_id')}; the author drops the `blocked_by_check` row of that Then")
    return reasons


def _env_words() -> str:
    """The card's words (`stand_gap_words`), as the data file lists them - for the sentence that asks."""
    try:
        import gate_brief
        words = [row["word"] for row in gate_brief.stand_gap_words()]
    except Exception:
        words = []
    return ", ".join(words) if words else "the words of the stand-gap card"


def _env_row_state(row: dict, facts: dict) -> str:
    """`decided`, `undecided` or `unbound` for one ENV_ISSUE triage row (F2): the cases `contract.bind_triage` gives the row
    (`_triage_binding`), each looked up for the person's recorded gate B answer. `unbound` = the binding gives the row no
    failure or no case: nothing can be looked up, which is `no` with a reason that says so - never a silent pass."""
    cases = next((cs for r, cs, _keys in _triage_binding(facts, "ENV_ISSUE") if r is row), [])
    if not cases:
        return "unbound"
    return "decided" if all(env_decision(case, facts["decisions"], facts["cfg"]) for case in cases) else "undecided"


def factory_finding_reasons(artifacts: Path) -> list:
    """The reducer's own defect list — which until 0.7.5 nothing read.

    `finalize_task.py` records what IT could not do: a result row it could not join to a
    manifest instance, a duplicate identity. That is our defect, not the product's, and it
    was written into `run-report.json` and then dropped on the floor — it reached neither
    this aggregator, nor the ledger, nor the report, nor gate B. It surfaces here
    with `owner: factory`, so the person sees it and is asked for nothing."""
    report = C.load_json(C.artifact(artifacts, "run-report.json"))
    out = []
    for finding in report.get("factory_findings") or []:
        if not isinstance(finding, dict):
            continue
        # A join failure a later terminal rerun of the same case answered is history, not a
        # gap: printing it would ask the person about a row the factory already replaced
        # (TP2-2553). It stays in the report, marked, for whoever reads the run.
        if finding.get("superseded_by"):
            continue
        out.append("factory: " + str(finding.get("entity") or "the reducer") + " — "
                   + str(finding.get("code") or "FACTORY_DEFECT") + ": "
                   + str(finding.get("detail") or "no detail recorded"))
    return out


def _env_owner_of(facts: dict) -> str:
    """The owner word of an environment block (`ledger._env_owner`'s reading of the run report), "user" when it names none."""
    return L._env_owner(facts.get("report") or {})


def _limit_suffix(row: dict) -> str:
    """C1-5c: a window that closed over this rejection says why its rounds ended, in the same words the report prints
    (`ledger.limit_words`); a row no window covers adds nothing."""
    limit = row.get("repair_limit")
    if not isinstance(limit, dict):
        return ""
    return "; " + L.limit_words(limit.get("reason"), limit.get("counted"), limit.get("cap"))


# The stages whose `stage_overrides[]` carry the person's word about the stand block: the stages the driver gates on a stand
# (`story_run.Driver.STAND_STAGES`, and the `stages` of that name's row in `references/block-names.json`; a test holds the three equal).
STAND_WORD_STAGES = ("S5", "S6")


def stand_word(facts: dict | None) -> bool:
    """Is the person's word that passes the stand block recorded (and not taken back) for this story (HF2-11 11c, `stand_word` of
    `references/delivery-verdict-kinds.json`)? THE reader is `waiver.split_overridden`, the one the driver's own stand check
    asks (`Driver.stand_check`) with the one constant (`waiver.STAND_NOT_CONFIRMED_BLOCK`): a revoked word reads False, as it
    does there. No pipeline, no word. ERROR DIRECTION: False is `no`/factory (a test the factory did not run again on a
    stand it had); True lets the delivery go to the person, so only a recorded, live override of S5/S6 reads True."""
    pipeline = (facts or {}).get("pipeline") or {}
    return any(waiver.split_overridden([waiver.STAND_NOT_CONFIRMED_BLOCK], pipeline, stage)[1] for stage in STAND_WORD_STAGES)


def ledger_records(ledger: dict, facts: dict | None = None) -> list:
    """The ledger's rows as typed records `[{text, kind, case, ref, requirements, tests, words, source, ...}]` (t-305 N8).

    The KIND of a row comes from its STATE through `references/delivery-verdict-kinds.json` (L1-L20), plus what only
    the record can say: the plan row's disposition (a `not_executed` row of a `manual-human` row is that case's debt, not a
    failure to run), the person's recorded stand-gap answer for the row's case (an `ENV_ISSUE`/blocked row), the
    gate waiver words carried on the row (`waived:<inner>`). `facts` (`gather`) holds them; with none the rows are read
    by their state alone, which is today's behaviour for every `no` kind. A state the file does not hold is a kind
    named `ledger_state:<state>`, which `decide` reads as `no` and says so (never a silent pass).
    The TEXT is what a person reads for a `no` kind; `review_skipped` and `subtask_in_progress` rows carry none of
    their own (the flag and `subtasks_open` below say it once), and a kind that is not `no` carries none at all."""
    doc = DV.load_kinds()[0]
    facts = facts or {"dispositions": {}, "decisions": {}, "cfg": {}, "index": {}, "manifest": {}, "triage": [],
                      "plan": []}
    out = []
    if ledger.get("review_skipped"):
        skipped = [r["ref"] for r in ledger.get("rows") or [] if r.get("state") == "review_skipped"]
        out.append({"text": "review: no critic verdict for " + (", ".join(skipped) or "at least one test"),
                    "kind": "review_gap", "case": "", "ref": "review", "source": "ledger"})
    for sub in ledger.get("subtasks_open") or []:
        out.append({"text": f"subtask {sub.get('key')} is still {sub.get('status')} — the story's own "
                            "scope is not closed", "kind": "subtask_open", "case": "", "ref": str(sub.get("key")),
                    "source": "ledger"})
    blocked = {_bare(u.get("case") or "") for u in C.manifest_unresolved(facts["manifest"])
               if str(u.get("reason") or "") == "blocked_by_env"}
    stand = stand_word(facts)
    stricter = _stricter_cases(facts)
    for row in ledger.get("rows") or []:
        state = str(row.get("state") or "")
        prefix = C.ledger_state_prefix(state)
        ref = str(row.get("ref") or "")
        disposition = (facts.get("dispositions") or {}).get(ref, "") if row.get("kind") == "plan_row" else ""
        words = any(isinstance(d, dict) and str(d.get("words") or "").strip() for d in (row.get("decision") or []))
        cases = row_cases(row, facts)
        env_row = prefix == "env_blocked" or state == "failed:ENV_ISSUE"
        lookup = state
        if prefix == "not_executed" and state != HANDED_LEDGER_STATE and cases and all(c in blocked for c in cases):
            # a test (or row) the stand stopped before it could run: the manifest's own `blocked_by_env` row names its case, so
            # it is the stand gap's - decided by the person's answer to the card, like the plan row of the same case - and
            # not a `not_executed` nobody explained
            env_row, lookup = True, "env_blocked:" + _env_owner_of(facts)
        picks = [(c, env_option_of_case(c, facts)) for c in cases] if (env_row and cases) else [("", "")]
        for case, option in picks:
            kind = DV.kind_of_state(lookup, doc, disposition=disposition, env_option=option, words=words, stand_word=stand)
            if kind is None:
                kind = f"ledger_state:{state}"
            rec_cases = cases
            if kind == "assert_stricter":
                # B1 (t-1338): the kind belongs to the cases whose triage row is the word with a well-formed experiment, not to
                # every case of the plan row (the ledger gives a plan row the verdict of its first failed case): a green or
                # handed neighbour gets no "remove this check" item, a failed neighbour keeps its own row. No such case on
                # the row = nothing holds the word: the red reads as a product failure (the direction of `no`)
                rec_cases = _stricter_scope(cases, stricter)
                if not rec_cases:
                    kind, rec_cases = RED_KIND, cases
            verdict = DV.verdict_of_kind(kind, doc)
            text = ""
            if verdict == "none":
                continue            # a kind that decides nothing (passed, a plan skip, ...) leaves no record
            if verdict in ("no", None) and prefix not in ("review_skipped", "subtask_in_progress"):
                if kind == "deferred_undecided":
                    text = (f"deferred without a decision: {ref} is `{state}`, and no word of yours is recorded "
                            f"for it ({row.get('detail') or 'no detail'})")
                else:
                    text = f"ledger: {ref} is `{state}` ({row.get('detail') or 'no detail'})"
                    text += _limit_suffix(row)
            rec = {"text": text, "kind": kind, "case": case or (rec_cases[0] if len(rec_cases) == 1 else ""),
                   "cases": rec_cases, "ref": ref, "row_kind": row.get("kind"), "state": state, "source": "ledger",
                   "option": option, "decision": row.get("decision") or []}
            out.append(rec)
    return out


def ledger_reasons(ledger: dict, facts: dict | None = None) -> list:
    """The sentences of the ledger rows that BLOCK delivery (kind `no`), in the ledger's order - the text half of
    `ledger_records`, kept for every caller that asks only for the reasons. `review_unverified` is deliberately not
    one (D-0013): the critic could not complete the proof, which is the person's debt. `review_unrecognised` is: a
    verdict our vocabulary lacks is our own defect (FR-19). A handed row is not one - `handed_records` says it once, in
    words the person can act on, instead of once per row in the ledger's own shorthand."""
    return [rec["text"] for rec in ledger_records(ledger, facts) if rec["text"]]


def handed_plan_rows(artifacts: Path) -> frozenset:
    """C5-4 (F-1): the plan rows (`TS-n`) whose cases are ALL taken by hand by the person (`person_check_rows`, the set the
    traceability walk reads): at least one case names the row and every case that names it is handed. Their obligations are
    "Left with you", not a coverage reason. Unreadable plan, cases or hand-off set = no row at all: the reason stays and is
    never lifted on an unknown (FR-59, AR-28)."""
    try:
        handed = {str(r["case"]) for r in person_check_rows(artifacts) if r.get("case")}
        by_row: dict = {}
        for key, meta in C.case_index(artifacts).items():
            by_row.setdefault(str(meta.get("plan_row") or ""), []).append(str(key))
        return frozenset(row for row, keys in by_row.items() if row and handed and all(k in handed for k in keys))
    except Exception:  # noqa: BLE001
        return frozenset()


def coverage_reasons(doc: dict, handed_rows_of_plan: frozenset = frozenset()) -> list:
    """One reason per current-task obligation the coverage projection does not verify.

    `person_debt`: the only test that covers it is one the critic could not verify (D-0013) -
    shown in the coverage report in words, listed in "Left with you", never a delivery reason.
    C5-4 (F-1): an obligation of a plan row in `handed_rows_of_plan` (`handed_plan_rows`) is the person's line too, unless its
    run is red (`execution_state` `failed`, or absent - the unsafe direction): a hand-off does not hide an observed failure."""
    # RD1-21: a red run or an open oracle is the product's question (`coverage red:`); missing evidence with a green run
    # and a closed oracle is the factory's (`coverage:`). A field that is absent reads RED: the unsafe error is a red
    # obligation labelled the factory's, so the missing key falls to the product's side.
    out = []
    for obligation in doc.get("coverage", {}).get("obligations", []):
        if (obligation.get("execution_scope") != "current_task" or obligation.get("verified")
                or obligation.get("person_debt")):
            continue
        if obligation.get("plan_row") in handed_rows_of_plan and obligation.get("execution_state", "failed") != "failed":
            continue
        # RN1-23 (3): an obligation that carries NO cause at all - neither state field and a `gap` that is empty or exactly
        # `none` - is the coverage projection's own gap, not a behaviour in question (LOCAL-1 printed `coverage red: OB-n -
        # none` under the product). Narrow on purpose (E-A8, the RD1-21 safe side): an absent state beside a real `gap` text
        # still reads `coverage red:`. It still blocks; only the owner (family `coverage:`, the factory) and the words change.
        gap = str(obligation.get("gap") or "").strip()
        if "execution_state" not in obligation and "oracle_open" not in obligation and gap in ("", "none"):
            out.append(f"coverage: {obligation['obligation_id']} — the coverage projection recorded no cause for this "
                       "obligation (no `gap`, `execution_state` or `oracle_open` in coverage_contract.py's row for it)")
            continue
        said = obligation["obligation_id"] + " — " + obligation["gap"]
        if obligation.get("execution_state", "failed") == "failed" or obligation.get("oracle_open", True):
            out.append("coverage red: " + said)
        else:
            out.append("coverage: " + said)
    return out


PRODUCT_GAPS_FILE = "product-gaps.json"
REQ_WHOLE = re.compile(r"R-\d+")


def _read_product_gaps(artifacts: Path) -> tuple:
    """`([{"requirement", "words", "words_ref"}], problem)`: the requirements the person called not implemented (RN1-15), from
    `work/product-gaps.json` `{"gaps": [{"requirement", "words", "words_ref", "gate"}]}` - the carrier the t-1697 writer owns.
    TEMPORAL: before the writer's first run the file does not exist -> ([], "") and nothing changes. A file that cannot be read
    as that shape -> ([], <what is wrong>); a row that names no `R-n` is left out and counted in the problem. One row per
    requirement (the first). Reads only (FR-45); the words are carried whole, never read (FR-12)."""
    try:
        path = C.artifact(artifacts, PRODUCT_GAPS_FILE)
        if not path.is_file():
            return [], ""
        gaps = json.loads(path.read_text(encoding="utf-8-sig"))["gaps"]
        if not isinstance(gaps, list):
            raise ValueError("`gaps` is not a list")
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {str(exc)[:120]}"
    rows: dict = {}
    bad = 0
    for gap in gaps:
        req = str(gap.get("requirement") or "").strip() if isinstance(gap, dict) else ""
        if not REQ_WHOLE.fullmatch(req):
            bad += 1
            continue
        rows.setdefault(req, {"requirement": req, "words": " ".join(str(gap.get("words") or "").split()),
                              "words_ref": str(gap.get("words_ref") or "").strip()})
    return list(rows.values()), (f"{bad} row(s) name no requirement `R-n`" if bad else "")


def product_gap_records(artifacts: Path, facts: dict | None = None, read: tuple | None = None) -> list:
    """RN1-15, the delivery side: one record per requirement the person said the product does not implement - kind
    `product_gap` (`delivery-verdict-kinds.json`: `no`, owner product; FR-21), the reason under the family `product gap:`.
    `requirements` and `words` travel typed on the record, so the report names the gap without reading the sentence (AR-22).
    No carrier -> []; an unreadable one -> [] and `product_gap_findings` says so (the requirement stays unproven in
    traceability, so the verdict cannot become `yes` through this - AR-28). `read`: `_read_product_gaps`'s result when the caller
    already has it (one read per `assess`, F10 t-1753)."""
    out = []
    for row in (read if read is not None else _read_product_gaps(artifacts))[0]:
        said = row["words"] or (f"their words are recorded at {row['words_ref']}" if row["words_ref"]
                                else "no words were recorded")
        out.append({"text": f"product gap: {row['requirement']} — the person said the function is not implemented: {said}",
                    "kind": "product_gap", "case": "", "ref": row["requirement"], "source": "check",
                    "requirements": [row["requirement"]], "words": row["words"] or said})
    return out


def product_gap_findings(artifacts: Path, read: tuple | None = None) -> list:
    """The factory finding for a carrier `product_gap_records` could not read whole (E-A9): what is wrong, what is expected."""
    problem = (read if read is not None else _read_product_gaps(artifacts))[1]
    if not problem:
        return []
    return [{"code": "PRODUCT_GAPS_UNREADABLE", "entity": "task", "owner": "factory",
             "detail": f"factory: work/{PRODUCT_GAPS_FILE} could not be read whole ({problem}); it is expected to be "
                       "{\"gaps\": [{\"requirement\": \"R-n\", \"words\": ..., \"words_ref\": ..., \"gate\": ...}]}. "
                       "The requirements it names are not listed as product gaps by this check; each of them stays "
                       "unproven in the traceability"}]


def handed_records(artifacts: Path) -> list:
    """One record per test the person took over (R5, T1): kind `handed` - the third verdict, never a reason. What they
    run comes from the manifest's own row (`contract.handed_tests`, the ONE list); a row that names no command is
    carried as `no_command` and gets a finding (Q18): the factory's gap, not the person's."""
    out = []
    for row in handed_rows(artifacts):
        case = str(row.get("case_id") or _bare(row.get("case") or ""))
        command = " ".join(str(row.get("detail") or row.get("what") or "").split())
        out.append({"text": "", "kind": "handed", "case": case, "ref": case, "source": "handed",
                    "how": command, "no_command": not command})
    # GW1-14: a Then the person took beside the case's green test is a `handed` record too, carrying the Then, its part
    # and its owner (`contract.handed_tests(thens=True)`, the same list the ledger branch reads). `handed_rows` and
    # `mark_handed` stay whole-case: they restate ledger rows of cases nothing ran.
    try:
        manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
        then_rows = [r for r in C.handed_tests(manifest, thens=True) if r.get("then")]
    except Exception:
        then_rows = []
    for row in then_rows:
        case = str(row.get("case_id") or _bare(row.get("case") or ""))
        command = " ".join(str(row.get("detail") or row.get("what") or "").split())
        out.append({"text": "", "kind": "handed", "case": case, "ref": case, "source": "handed",
                    "how": command, "no_command": not command, "then": row["then"], "part": row.get("part") or "",
                    "owner": row.get("owner") or ""})
    return out


def unprepared_records(ledger: dict) -> list:
    """One record per manual case the factory failed to prepare and the manual agent walked without a result (F5(e) 3, AR-27):
    kind `unprepared_walk` (`after_checks`, owner factory) - the case is a "Left with you" item under its own name, with the
    reason as what is left to check. The ONE reader of the ledger's `unprepared_walks` (the list `ledger.build` writes from
    `manual_evidence.unprepared_rows`); a ledger without the key has none. The walk never proves a requirement: coverage
    keeps `verified` False and the requirement keeps its own kind (Fork 13 A, AR-28). The record carries no `requirements`: the
    walk row holds none, and `build_left_items` fills the item's from the case index."""
    out = []
    for walk in (ledger or {}).get("unprepared_walks") or []:
        if not isinstance(walk, dict) or not walk.get("case"):
            continue
        case = str(walk["case"])
        reason = str(walk.get("reason") or "no reason recorded")
        if walk.get("walked") is False:      # t-1955 N3: derived from the recorder's files, never the runner's word
            to_check = ("the factory could not prepare this check and it was not walked either - not walked: "
                        + str(walk.get("not_walked") or "no reason recorded") + "; the factory's reason: " + reason)
        else:
            to_check = "the factory could not prepare this check and the agent walked it without a result: " + reason
        out.append({"text": "", "kind": "unprepared_walk", "case": case, "ref": case,
                    "to_check": to_check,
                    "source": "ledger"})
    return out


def _check_after_words(blocker_cases: list, facts: dict) -> str:
    """T3 (HF2-3 D8, `human_text`-checked): `check after {case} ({case title}) is fixed` - the "Left with you" words of a
    blocked Then whose row carries no `detail`. `{case}` is each case `ledger.blocker_cases` names (several joined by `and`,
    each with its own title; an instance id is never printed); a case whose title cannot be read is
    `the check this one depends on ({case})` as a whole, the id ONCE (what `traceability` prints); no case at all reads
    `the check this one depends on`."""
    if not blocker_cases:
        return "check after the check this one depends on is fixed"
    parts = []
    for case in blocker_cases:
        title = ""
        for key, meta in facts["index"].items():
            if str(meta.get("case_id") or _bare(key)) == _bare(case) and meta.get("path"):
                try:
                    title = " ".join(C.case_title(Path(meta["path"])).split())
                except Exception:
                    title = ""
                break
        parts.append(f"{case} ({title})" if title else f"the check this one depends on ({case})")
    return "check after " + " and ".join(parts) + " is fixed"


def blocked_records(artifacts: Path, facts: dict | None = None) -> list:
    """One record per Then that stands behind a red check (`blocked_by_check`, HF2-3 FA-9): kind `blocked_by_check` - the
    third verdict (`after_checks`), never a reason - read from the manifest's own `then_bindings` rows
    (`contract.then_remainders(..., reasons=(BLOCKED_BY_CHECK,))`, the ONE list). The record carries the Then and the
    blocking check; `how` is the author's `detail` verbatim (FR-8), else the T3 words (`_check_after_words`). A case the
    ledger reads `not_executed:blocked_by_check` for a COVERED Then (no row to read here) reaches "Left with you" through
    the ledger record of the same kind. An unreadable manifest has no rows: `[]`, and the ledger record stands alone."""
    facts = facts or gather(artifacts)
    manifest = facts["manifest"]
    try:
        # R6: the Thens the CURRENT triage names as waiting join the manifest's (one list, one reader)
        rows = C.then_remainders(manifest, facts["cfg"] or None, reasons=(C.BLOCKED_BY_CHECK,),
                                 triage=facts["triage"], report=facts["report"])
        red = L.red_instances(manifest, facts["report"]) if rows else {}
    except Exception:
        return []
    out = []
    for row in rows:
        case = str(row.get("case_id") or _bare(row.get("case") or ""))
        how = row["detail"] or _check_after_words(L.blocker_cases(row["blocking_check"], manifest, red), facts)
        how += L.diagnostic_words(row)
        out.append({"text": "", "kind": C.BLOCKED_BY_CHECK, "case": case, "ref": case, "source": "blocked", "how": how,
                    "then": row["then"], "blocking_check": row["blocking_check"]})
    return out


def _owes_factory_judgment(artifacts: Path, test: dict) -> bool:
    """True when the probe's record of THIS test's current bytes is `incomplete` with `cause: judgment`, judged or not
    (`proof_level.probe_owes_judgment`, t-1968 N2: `unjudged` or `cannot_judge`). The bytes are read under the project the story
    sits in (the nearest ancestor of `artifacts` carrying the marker; none: the process's own project), never under a guess; a
    test file that is gone gives an empty hash and False (FR-41: an unknown is not upgraded to a typed claim). ALSO False when
    `proof_level.probe_plain_call_owed` is True for the record (t-2064 fix round G, R2): the state "models owed / rows not selected"
    is the critic's work (`review_unverified`), never "the cause is the factory's" (FR-19, AR-27)."""
    try:
        from runtime_paths import nearest_project
        sha = PL.current_test_sha(test, nearest_project(artifacts))
        if PL.probe_plain_call_owed(artifacts, C.test_instance_id(test), sha):
            return False
        return PL.probe_owes_judgment(artifacts, C.test_instance_id(test), sha) != ""
    except Exception:
        return False


def unverified_records(artifacts: Path, facts: dict | None = None) -> list:
    """One `review_unverified` record per manifest test the code critic could not verify (D-0013, Q5 ii): the person's debt,
    read from the manifest's OWN verdict - a typed field - and not from a ledger state. A row a triage verdict turned green
    (a fixed FLAKY) is `passed_green` in the ledger and still carries the debt (`delivery_summary` always said so), so the
    ledger row alone would lose it and the verdict would read `yes` over an unverified test. A test whose probe failed at the
    mutated line on a text the factory cannot read and no judgment proved it (E15, `cause: judgment`) is the same debt under the
    kind `review_unverified_factory`: the person may still check it, the cause is the factory's (`factory_data_gap_findings` says so)."""
    from traceability import is_dead_test
    facts = facts or gather(artifacts)
    out = []
    for test in C.manifest_tests(facts["manifest"]):
        if not L.is_unverified(test) or is_dead_test(test):
            continue
        links = [_bare(c) for c in C.manifest_test_links(test, facts["cfg"])] or [_bare(test.get("case") or "")]
        kind = "review_unverified_factory" if _owes_factory_judgment(artifacts, test) else "review_unverified"
        for case in [c for c in dict.fromkeys(links) if c]:
            out.append({"text": "", "kind": kind, "case": case, "ref": case, "source": "ledger"})
    return out


def factory_data_gap_findings(artifacts: Path, facts: dict | None = None) -> list:
    """One factory finding per unverified manifest test whose probe failed at the mutated line on a text the factory could not
    read and which no judgment proved (RN1-9, E15; t-1968 N2, `cause: judgment`): `code: PROBE_NOT_JUDGED`, `entity` the instance
    id, `owner: factory`. THE ONE WRITER (AR-14) of that finding on every road (the report's Factory defects block and the findings
    of `doc`); no stage writes it by hand. The same set of tests as `unverified_records` gives the kind
    `review_unverified_factory`."""
    from traceability import is_dead_test
    facts = facts or gather(artifacts)
    out = []
    for test in C.manifest_tests(facts["manifest"]):
        if not L.is_unverified(test) or is_dead_test(test) or not _owes_factory_judgment(artifacts, test):
            continue
        iid = C.test_instance_id(test)
        out.append({"code": "PROBE_NOT_JUDGED", "entity": iid, "owner": "factory",
                    "detail": f"factory: the probe of {iid} failed at the mutated line with a text the factory could not read, "
                              "and no judgment proved it; the test is left with you unprobed"})
    return out


def not_executed_findings(artifacts: Path, facts: dict | None = None) -> list:
    """One factory finding per triage row that says `NOT_EXECUTED` and is not exactly what S7's code writes (F2): the
    forbidden direction is a red test, or a check code would not close, shown to the person as "you will check this".
    `code: NOT_EXECUTED_NOT_RE_DERIVED`, `entity`: the row's name, and the detail says which of the three conditions of
    `_code_row_ok` failed. A row that holds all three has no finding."""
    facts = facts or gather(artifacts)
    out = []
    for row in facts["triage"]:
        if str(row.get("verdict") or "") != "NOT_EXECUTED":
            continue
        name = str(row.get("instance_id") or row.get("test") or row.get("case") or "?")
        ok, why = _code_row_ok(str(row.get("case") or row.get("instance_id") or row.get("test") or ""), facts)
        if not ok:
            out.append({"code": "NOT_EXECUTED_NOT_RE_DERIVED", "entity": name, "owner": "factory",
                        "detail": f"factory: triage row {name} says NOT_EXECUTED, but {why}: a red test or a check "
                                  "code would not close is never shown as 'the person will check'"})
    return out


def regression_record(artifacts: Path) -> tuple:
    """`(row, findings)`: the plan's `## Recommended regression` as ONE row of `left_items`, ALWAYS in Left with you and
    NEVER counting toward the verdict (F3). Verbatim lines (FR-49: code never composes the list). A section that is
    absent or blank is `regression_missing` with a finding and the gap line - never a block (Q13 a-2, FR-57)."""
    try:
        text = C.read_text(C.artifact(artifacts, "test-plan.md"))
    except Exception:
        text = ""
    lines = DV.regression_lines(text)
    if lines:
        return {"kind": "regression", "ref": "regression", "case": "", "requirements": [], "tests": [], "lines": lines,
                "to_check": "", "how": "", "words": "", "source": "plan", "counts": False}, []
    return ({"kind": "regression_missing", "ref": "regression", "case": "", "requirements": [], "tests": [],
             "lines": [DV.GAP_LINE], "to_check": "", "how": "", "words": "", "source": "plan", "counts": False},
            [{"code": "REGRESSION_SCOPE_MISSING", "entity": "test-plan.md", "owner": "factory",
              "detail": "factory: " + DV.GAP_LINE + " (test-plan.md has no `## Recommended regression` section, or it is "
                        "blank); Left with you says so, and the delivery is not held for it"}])


def _function_name(test: dict) -> str:
    return str(test.get("marker") or test.get("test_function") or C.function_name(C.test_instance_id(test))
               or test.get("file") or "")


def _unconfirmed_to_check(case: str, facts: dict) -> str:
    """P20/FR-58: "confirm the expectation: was <before value, or 'not recorded'> / is <what the binding observed>" from
    the manifest's own `then_bindings` row of the case - a field, never wording."""
    for row in facts["manifest"].get("then_bindings") or []:
        if (isinstance(row, dict) and str(row.get("reason") or "") == C.EXPECTATION_UNCONFIRMED
                and str(row.get("status") or "") != "covered" and C.names_case([row.get("case") or ""], case, facts.get("cfg"))):
            was = " ".join(str(row.get("before") if row.get("before") is not None else "").split()) or "not recorded"
            now = " ".join(str(row.get("observed") if row.get("observed") is not None else "").split()) or "not recorded"
            return f"confirm the expectation: was {was} / is {now}"
    return "confirm the expectation: was not recorded / is not recorded"


def _stricter_control(case: str, facts: dict) -> dict:
    """The `control` block of the ASSERT_STRICTER triage row bound to `case` (the binding `_triage_binding` gives), `{}` when
    no such row binds or the facts cannot be read - the item then says "not recorded" (FR-41), never invents."""
    try:
        for row, cases, _keys in _triage_binding(facts, "ASSERT_STRICTER"):
            if case in cases and isinstance(row.get("control"), dict):
                return row["control"]
    except Exception:
        pass
    return {}


def _stricter_thens(case: str, facts: dict) -> list:
    """The Then numbers the manifest's `contradicts_requirement` rows of `case` name as red (`thens`, read by
    `contract.then_number`); `[]` when none names one - the item then names the case, no number is invented (FR-41)."""
    numbers: set = set()
    for row in C.manifest_unresolved(facts["manifest"]):
        thens = row.get(C.UNRESOLVED_THENS_KEY)
        if str(row.get("reason") or "") == "contradicts_requirement" and C.names_case([row.get("case") or ""], case, facts.get("cfg")) \
                and isinstance(thens, list):
            numbers |= {C.then_number(n) for n in thens}
    return sorted(n for n in numbers if n)


def _assert_stricter_to_check(case: str, meta: dict, facts: dict, control: dict) -> str:
    """N5 (FR-6, FR-20): WHICH assert the person decides about and what the same action showed without this story's change:
    the Then(s) the red names, in the case's own words (`_blocked_to_check`; the case alone when no Then is named), and the
    analyst's `control.observed` - a field, never wording code reads. `control` is the case's block (`_stricter_control`,
    bound once per item by the caller)."""
    seen = " ".join(str(control.get("observed") or "").split()) or "not recorded"
    return f"{_blocked_to_check(meta, _stricter_thens(case, facts)) or case} - without this story's change it showed: {seen}"


def _assert_stricter_how(item: dict, control: dict) -> str:
    """The default `how` of an `assert_stricter` item (A3): the person's two ways out, the requirement(s) of the case (R-n,
    from the item), and - F2 (b) - the seed's own gap when the analyst recorded `control.given_gap` on the same row."""
    reqs = f" ({', '.join(item['requirements'])})" if item["requirements"] else ""
    how = (f"Decide: remove this check from the test, or refine the requirement it goes beyond{reqs} - the same action "
           "without this story's change gives the same result"
           # RD1-19 (B-4): the person's words reach the conductor, who lays out the options with their cost; no command is named
           # (FR-6) and no outcome is promised (a repair of a Then after gate A is not the factory's to promise, FR-9)
           "; tell the delivery gate in your own words which one you want, and the factory lays out what it can do, at what cost")
    gap = " ".join(str(control.get("given_gap") or "").split())
    return how + (f"; the test's data was also weaker than the case's Given: {gap}" if gap else "")


# The default `how` of an item that carries no words of its own, by the kind that needs one (t-1339 Q4: one table where four
# branches stood). Each entry takes `(key, item, facts, control)`; the first kind of the item that has an entry decides.
_DEFAULT_HOW = (
    ("assert_stricter", lambda key, item, facts, control: _assert_stricter_how(item, control)),
    ("env_accepted", lambda key, item, facts, control:
        f"Needed: a stand where {_missing_of(key, facts)}; you said: {item['words'] or 'not recorded'}"),
    ("env_change_pending", lambda key, item, facts, control:
        "How: run " + (", ".join(item["tests"]) or key) + " again after the change"),
    # the test changed after its run and you said there is no stand: the door is the ordinary run, on a stand (FR-1, FR-2)
    ("changed_unrun", lambda key, item, facts, control:
        f"How: run `run_suite.py --mine {item['case'] or '<case>'}` on a stand - the test changed after its last run and no "
        "stand was confirmed here, so the factory could not run it again"),
    # t-2181 PC-5 (S15): a green that met a side which was not real is run again where that side is real (E-R1: a red there is the
    # side's bug, and goes back to the factory as a rework). The sides named are the ones THIS case's proof missed (typed, from the
    # ledger's own units); only when it names none does the story's current record stand in; with none left the door is the plain re-run.
    ("on_substitute", lambda key, item, facts, control:
        "How: run " + (", ".join(item["tests"]) or key) + " again where " + _unreal_sides_words(key, facts)
        + " (relaunch the story with `--side <name>=real` once the code or the real service is there)"),
    ("sides_unknown", lambda key, item, facts, control:
        "How: run " + (", ".join(item["tests"]) or key) + " again - it ran while the project's record of its sides could not be read, "
        "so what it proved is not known"),
    # t-2277 J-C7 (PC-5 fix round): a green on an open first-look placeholder proves nothing; the door is the run against the real element
    ("placeholder_open", lambda key, item, facts, control:
        "How: run " + (", ".join(item["tests"]) or key) + " again once the product has the element - the marked locator gets settled "
        "by that run (a green against the real element, then the placeholder row is settled with the run as its evidence)"),
)


def _unreal_sides_words(case: str, facts: dict) -> str:
    """`<sides> is real` / `<a> and <b> are real` for the how-line of an `on_substitute` item: the sides THIS case's unproven units
    missed (`ledger.missed_sides`, typed - never parsed from a row's detail), else the sides of the story that are not `real` now
    (`contract.story_sides`, the one reader - it never raises by its own contract), else `the side it met is real` (a side that
    became real after the run, or an unreadable record)."""
    names = L.missed_sides(facts.get("manifest") or {}, facts.get("report") or {}, case, facts.get("cfg") or None)
    if not names:
        names = [n for n, s in C.story_sides(facts.get("pipeline") or {}).items() if s.get("reality") != "real"]
    if not names:
        return "the side it met is real"
    return " and ".join(names) + (" is real" if len(names) == 1 else " are real")


def build_left_items(records: list, facts: dict, doc: dict | None = None) -> list:
    """`left_items` (F9, F10, N-5): ONE row per case whose kind counts toward `after_checks` - `{kind, kinds, ref, case,
    requirements, tests, to_check, how, words, source, counts}` - read by the report's completeness check, the gate B
    block, the head's count, the dashboard and nobody else (nobody else lists items). A record with no case (a debt bound
    to a requirement only) is keyed by its R-n. Typed data only: the scribe words the items, code checks they are there."""
    doc = DV.load_kinds()[0] if doc is None else doc
    items: dict = {}
    then_recs: dict = {}      # case key -> [(Then number, part)] of the Thens a person took (GW1-14)
    whole_handed: set = set()  # case keys the manifest hands WHOLE: every Then of such a case is the person's
    blocked_thens: dict = {}   # case key -> [Then number] behind a red check (`blocked_by_check` rows of the manifest)
    for rec in records:
        if DV.verdict_of_kind(rec.get("kind"), doc) != "after_checks":
            continue
        cases = [c for c in (rec.get("cases") or ([rec["case"]] if rec.get("case") else [])) if c]
        # TQ1-20: a record that names its own `item_key` (a branch, a part of the ticket text, a file) is keyed by it when it has no
        # case, BEFORE its requirement: two branches of one R-n are two items. Any other record keeps the key it always had.
        keys = cases or [rec.get("item_key") or (rec.get("requirements") or [rec.get("ref") or "?"])[0]]
        for key in keys:
            if rec.get("source") == "handed":
                if rec.get("then"):
                    then_recs.setdefault(key, []).append((rec["then"], str(rec.get("part") or "")))
                else:
                    whole_handed.add(key)
            if rec.get("source") == "blocked" and rec.get("then"):
                blocked_thens.setdefault(key, []).append(rec["then"])
            item = items.get(key)
            if item is None:
                item = items[key] = {"kind": rec["kind"], "kinds": [], "ref": key, "case": key if cases else "",
                                     "requirements": [], "tests": [], "to_check": "", "how": "", "words": "",
                                     "source": rec.get("source") or "ledger", "counts": True}
            if rec["kind"] not in item["kinds"]:
                item["kinds"].append(rec["kind"])
            for req in rec.get("requirements") or []:
                if req not in item["requirements"]:
                    item["requirements"].append(req)
            if rec.get("how") and not item["how"]:
                item["how"] = rec["how"]
            if rec.get("to_check") and not item["to_check"]:
                item["to_check"] = rec["to_check"]        # the second pass below never overwrites it: an item with no case has no `meta`
            if rec.get("lines") and not item.get("lines"):
                item["lines"] = list(rec["lines"])         # the full list of parts of the ticket text (the report shows the first ones)
            if rec.get("no_command"):
                item["how"] = "no command recorded — the factory's gap"
            kind = rec["kind"]
            if kind in ("env_accepted", "env_change_pending", "handed") and rec.get("option") and cases:
                entries = _decisions_for_case(key, facts["decisions"], facts["cfg"])
                if entries:
                    item["words"] = entries[0].get("words") or item["words"]
                    item["source"] = "gate_b"
            if kind == "deferred_with_words":
                said = [d for d in rec.get("decision") or [] if isinstance(d, dict) and d.get("words")]
                item["words"] = " | ".join(f"{d['words']}" for d in said) or item["words"]
                if any(d.get("gate") == "B" for d in said):
                    item["source"] = "gate_b"
    for key, item in items.items():
        meta = {}
        for k, m in facts["index"].items():
            if str(m.get("case_id") or _bare(k)) == key:
                meta = m
                break
        for req in meta.get("requirements") or []:
            if req not in item["requirements"]:
                item["requirements"].append(str(req))
        for test in C.manifest_tests(facts["manifest"]):
            links = {_bare(c) for c in C.manifest_test_links(test, facts["cfg"])} | {_bare(test.get("case") or "")}
            if key in links and _function_name(test) not in item["tests"]:
                item["tests"].append(_function_name(test))
        person_thens = _person_thens(item["kinds"], blocked_thens.get(key, []), then_recs.get(key, []), key in whole_handed)
        control = _stricter_control(key, facts) if "assert_stricter" in item["kinds"] else {}
        if "unconfirmed_expectation" in item["kinds"] and item["case"]:
            # a question-open item has no case (it is keyed by its R-n): its `to_check` came with the record (A3)
            item["to_check"] = _unconfirmed_to_check(key, facts)
        elif "assert_stricter" in item["kinds"]:
            item["to_check"] = _assert_stricter_to_check(key, meta, facts, control)
        elif person_thens is not None:
            # only the Thens the records leave to the person wait for them (AR-26: the unit is the (Then, instance) pair):
            # the blocked ones behind the red check, with the handed ones beside them; the case's other Thens a test proved,
            # and a case with no Then row (the ledger's own record of the kind) lists none: the item names the case (FR-41)
            # shape B (the Thens moved before the red assert, covered, no `blocked_by_check` row): the covered Thens of the
            # case on the red instance are the person's too (R1, HF2-0), and the item gets the sibling default `how`
            covered, blockers = _behind_red(facts, key)
            person_thens = sorted(dict.fromkeys(person_thens + covered))
            item["to_check"] = _blocked_to_check(meta, person_thens, dict(then_recs.get(key, []))) or key
            if not item["how"]:
                item["how"] = _check_after_words(blockers, facts)
        elif then_recs.get(key) and key not in whole_handed:
            clauses = {}
            if meta.get("path"):
                try:
                    import traceability as T
                    clauses = T.case_thens(Path(meta["path"]))
                except Exception:
                    clauses = {}
            taken = sorted(dict.fromkeys(then_recs[key]))
            if set(item["kinds"]) == {"handed"}:
                # the item is ONLY the Thens the person took: its other Thens a green test proved, so only these are listed
                item["to_check"] = "; ".join(
                    " ".join(str(clauses.get(n) or f"Then {n}").split()) + (f" - the part: {part}" if part else "")
                    for n, part in taken)
            else:
                # the item also carries another kind (a probe gap, `review_unverified`): the other Thens rest on a test whose
                # sensitivity was never proved, so EVERY Then is listed and the part rides on the Then the person took (FR-41)
                parts = {n: part for n, part in taken}
                numbers = sorted(set(clauses) | set(parts))
                item["to_check"] = "; ".join(
                    " ".join(str(clauses.get(n) or f"Then {n}").split())
                    + (f" - the part: {parts[n]}" if parts.get(n) else "")
                    for n in numbers)
        elif meta.get("path") and not (item["to_check"] and "unprepared_walk" in item["kinds"]):
            try:
                import traceability as T
                item["to_check"] = "; ".join(T.case_thens(Path(meta["path"])).values())
            except Exception:
                item["to_check"] = ""
        item["stopped"] = _stopped_words(key, item["kinds"], facts)
        if not item["how"]:
            item["how"] = next((make(key, item, facts, control) for kind, make in _DEFAULT_HOW if kind in item["kinds"]), "")
    return list(items.values())


def _behind_red(facts: dict, case: str) -> tuple:
    """`ledger.behind_red` over the task's facts: `(covered Thens, blocker cases)`; `([], [])` when the manifest or the
    report cannot be read - the item then names the case alone (FR-41), never an empty line."""
    try:
        return L.behind_red(facts["manifest"], facts["report"], case, facts["cfg"] or None)
    except Exception:
        return [], []


def _person_thens(kinds: list, blocked: list, taken: list, whole_handed: bool) -> list | None:
    """The Thens a `blocked_by_check` item leaves to the person: the union of the Thens each record leaves - the blocked
    ones and the Then-level handed ones (`taken`: `[(Then, part)]`), duplicates collapsed, by Then number; `[]` for a record
    with no Then row (the item names the case). `None` when the item is not that shape: no blocked kind, or a record that
    leaves the WHOLE case (a whole-case hand-off, `not_executed`, any other kind) - every Then of the case, as before."""
    if C.BLOCKED_BY_CHECK not in kinds:
        return None
    if set(kinds) - {C.BLOCKED_BY_CHECK, "handed"} or ("handed" in kinds and (whole_handed or not taken)):
        return None
    return sorted(dict.fromkeys(list(blocked) + [n for n, _ in taken]))


def _blocked_to_check(meta: dict, numbers: list, parts: dict | None = None) -> str:
    """The clauses of the Thens that are the person's (behind a red check, or taken by the person), in the case's own words
    (`Then n` when the case file cannot be read); the part rides on a Then the person took; "" for no Then row."""
    clauses = {}
    if numbers and meta.get("path"):
        try:
            import traceability as T
            clauses = T.case_thens(Path(meta["path"]))
        except Exception:
            clauses = {}
    parts = parts or {}
    return "; ".join(" ".join(str(clauses.get(n) or f"Then {n}").split()) + (f" - the part: {parts[n]}" if parts.get(n) else "")
                     for n in sorted(dict.fromkeys(numbers)))


def _stopped_words(case: str, kinds: list, facts: dict) -> str:
    """What stopped the check of this case, in the record's OWN words (the report's "Not proven" quotes it, owner amendment
    03.10): the limitation the role wrote on a manual check that did not answer (carried verbatim by code's triage row), the
    manifest's `detail` of a stand gap, the missing evidence package of a manual-human case. "" when no record says."""
    if "not_executed_code" in kinds:
        for row in facts["triage"]:
            if row.get("source") == "code" and _bare(row.get("case") or row.get("instance_id") or "") == case:
                said = [" ".join(str(x).split()) for x in row.get("limitation") or [] if str(x).strip()]
                if said:
                    return "; ".join(said)
    if any(k in kinds for k in ("env_accepted", "env_change_pending", "env_undecided")):
        said = _missing_of(case, facts)
        return "" if said.endswith("(the row records none)") else said
    if "manual_human" in kinds:
        return "no evidence package was recorded for it"
    return ""


def _missing_of(case: str, facts: dict) -> str:
    """What the stand lacks for this case, in the manifest's own `detail` (or the run report's `needs`), else a plain
    statement that the row records none (FR-41)."""
    for row in C.manifest_unresolved(facts["manifest"]):
        if C.names_case([row.get("case") or ""], case, facts.get("cfg")):
            said = " ".join(str(row.get("detail") or row.get("needs") or "").split())
            if said:
                return said
    for row in facts["report"].get("env_blocked") or []:
        if isinstance(row, dict) and C.names_case([row.get("case") or ""], case, facts.get("cfg")):
            said = " ".join(str(row.get("detail") or row.get("needs") or "").split())
            if said:
                return said
    return "the missing piece exists (the row records none)"


def branch_records(artifacts: Path) -> list:
    """The records of branch accounting (TQ1-20): `branch_accounting.delivery_records`, the ONE reader. It raises when it cannot read
    what it must (the register's plan or snapshot is broken); that is the factory's own defect, ONE record of kind
    `branches_unreadable` with a `factory: ` text (verdict `no`, owner factory), and an unknown never reads as reconciled (FR-59, F-4c).
    This function never raises. `assess` as a whole can still raise before it gets here: a broken `test-plan.json` fails in
    `coverage_contract.plan_rows` (an earlier, unchanged line), so no verdict is written at all, which is not a pass (queued, F-7)."""
    try:
        import branch_accounting as BA
        return BA.delivery_records(artifacts)
    except Exception as exc:
        return [{"text": f"factory: branch accounting could not read what it checks ({type(exc).__name__}: {exc}) - the story's "
                         "branches are not known to be proven", "kind": "branches_unreadable", "case": "", "ref": "", "source": "check"}]


GROUNDING_HOW = ("Say at gate B that this needs a bug report (name {ref}): the conductor sends it to the failure analyst at S7; "
                 "or leave it with you.")


def bug_candidate_record(ref: str, requirements, to_check: str, how: str, source: str) -> dict:
    """The record of a bug candidate (G2-3, FR-22): a place where the code reads wrong that no executed check stands behind. Kind
    `bug_candidate` is `after_checks` (delivery-verdict-kinds.json): reading code proves nothing and moves no verdict by itself, but the
    candidate is a line in "Left with you", never silence. `item_key` is the ref (K-n or R-n): two candidates of one place are two items."""
    return {"text": f"grounding: {ref} {to_check}", "kind": "bug_candidate", "case": "", "ref": ref, "item_key": ref,
            "requirements": list(requirements), "to_check": to_check, "how": how, "source": source}


def _grounding_candidates(artifacts: Path) -> tuple:
    """`(candidates, unreadable)`: the places the factory read as possibly wrong, from the two inputs of FR-22. `K-n` = `rows[].risks[]` of
    the grounding table (a diff story only: the reader is `PC.read_grounding`; no table, or a table of a story without a diff, is silent),
    `R-n` = `contract.candidate_defects` of the register (any source world). Each candidate: `{ref, requirements, subject, source}`.
    `unreadable` = the names of an input that exists and could not be read (never read as "no candidates", FR-59)."""
    import planning_contract as PC
    out, unreadable = [], []
    table, problem = PC.read_grounding(artifacts)
    if table is not None:
        data = table.data if isinstance(table.data, dict) else {}
        if data.get("implementation_source") == "diff":
            seen = set()
            for row in data.get("rows") if isinstance(data.get("rows"), list) else []:
                reqs = [r for r in (row.get("requirements") if isinstance(row, dict) else None) or [] if isinstance(r, str)]
                for risk in (row.get("risks") if isinstance(row, dict) and isinstance(row.get("risks"), list) else []):
                    ident = risk.get("id") if isinstance(risk, dict) else None
                    if isinstance(ident, str) and ident not in seen:
                        seen.add(ident)
                        said = " ".join(str(risk.get("hypothesis") or "").split()) or "no hypothesis was written"
                        out.append({"ref": ident, "requirements": reqs, "subject": said, "source": "grounding"})
    elif getattr(problem, "kind", "") != "missing":
        unreadable += ["the grounding table"]   # a NAME of an input, not a reason text (the reason is built below)
    path = C.artifact(artifacts, "requirements-register.md")
    if path.is_file():
        try:
            text = C.read_text(path)
            if not text.strip():
                raise ValueError("empty")
            for found in C.candidate_defects(text):
                place = f"{found['file']}:{found['line']}" if found.get("file") else "place in the code not named"
                said = " ".join(str(found.get("requirement") or "").split()) or found["r"]
                out.append({"ref": found["r"], "requirements": [found["r"]], "subject": f"{said} ({place})", "source": "register"})
        except Exception:  # noqa: BLE001
            unreadable += ["the requirements register"]   # a NAME of an input, not a reason text (the reason is built below)
    return out, unreadable


def grounding_records(artifacts: Path, doc: dict, facts: dict) -> list:
    """The FR-22 road (G2-3): a bug candidate no EXECUTED check stands behind is a `bug_candidate` record, never silence. A candidate is
    closed by a plan row that names it (`K-n` by `PC.grounding_refs`, `R-n` by `PC.row_requirements`) and `PC.row_tests_it`, whose ledger
    row (`doc["rows"]`, kind `plan_row`, ref = the row id) is not red. No row names it, or the rows that name it only `skip` / `manual-human`
    / `unverifiable`: `bug_candidate` (the person's decision on it, from `not_planned`, rides in `how`). A testing row the ledger does not hold:
    `bug_candidate` ("could not be linked"). A testing row in the ledger that was not executed: nothing (its own kind says it). A red one:
    nothing (an ordinary bug). A green one whose `oracle_unknown` nobody answered and that no other green row backs: `unconfirmed_expectation`
    (unless the ledger already says it). A table or register that exists and cannot be read: ONE `factory_record`. Reading code confirms no bug
    and moves no verdict by itself: both kinds are `after_checks`. Then (G2-5) the requirements the change does not implement
    (`_pending_implementation_records`). Each part is guarded on its own: one that raises is ONE `factory_record`, and the other still
    runs. Never raises."""
    out: list = []
    for part, name in ((lambda: _grounding_records(Path(artifacts), doc, facts), "the bug candidates could not be checked against the plan"),
                       (lambda: _pending_implementation_records(Path(artifacts)),
                        "the requirements this change does not implement could not be established")):
        try:
            out += part()
        except Exception as exc:  # noqa: BLE001
            out.append({"text": f"factory: {name} ({type(exc).__name__}: {exc}) - they are not known to be covered", "kind": "factory_record",
                        "case": "", "ref": "", "source": "check"})
    return out


def pending_implementation_record(ref: str) -> dict:
    """The record of a requirement the story asks for and this change does not implement (G2-5, FR-21): kind `pending_implementation`
    is `no`, owner product (delivery-verdict-kinds.json), and never an item "Left with you" (only `after_checks` kinds are listed)."""
    return {"text": f"grounding: {ref} is required by the story and this change does not implement it", "kind": "pending_implementation",
            "case": "", "ref": ref, "source": "grounding"}


def awaiting_words(hold: dict, doc: dict | None = None) -> dict:
    """`{words, label}` of a hold read by `contract.awaiting`, by its `cause` (t-2277 PC-5; the table is `awaiting_words` of
    `references/delivery-verdict-kinds.json`, data, AR-1). A cause the table does not hold reads as the default cause
    (`contract.AWAITING_DEFAULT_CAUSE`) - an unknown cause never hides the hold. A `stopped` hold adds the table's `stopped_suffix` and
    the person's own words (`awaiting.stopped.words`, carried whole, never read - FR-12); its label says it was stopped. Never raises."""
    table = ((DV.load_kinds()[0] if doc is None else doc).get("awaiting_words")) or {}
    cause = str(hold.get("cause") or "")
    row = table.get(cause) if isinstance(table.get(cause), dict) else table.get(C.AWAITING_DEFAULT_CAUSE)
    row = row if isinstance(row, dict) else {}
    words = str(row.get("words") or "waiting for the code this story is about")
    label = str(row.get("label") or words)
    if hold.get("state") == "stopped":
        stopped = hold.get("stopped") if isinstance(hold.get("stopped"), dict) else {}
        said = " ".join(str(stopped.get("words") or "").split())
        suffix = str(table.get("stopped_suffix") or "the person stopped waiting")
        words = f"{words}; {suffix}" + (f': "{said}"' if said else "")
        label = f"{label} ({suffix})"
    return {"words": words, "label": label}


def awaiting_record(hold: dict, doc: dict | None = None) -> dict:
    """The ONE record of a story held for code (C10, B4): kind `awaiting_implementation` (`no`, owner product), the sentence under the
    family `grounding:` (a behaviour the story asks for that does not work yet - the product's, FR-19). It carries the `cause` and the
    `state` typed, so a reader never reads the sentence."""
    return {"text": "grounding: " + awaiting_words(hold, doc)["words"], "kind": "awaiting_implementation", "case": "", "ref": "awaiting",
            "source": "check", "cause": str(hold.get("cause") or ""), "state": str(hold.get("state") or "")}


def _pending_implementation_records(artifacts: Path) -> list:
    """G2-5 (FR-21, the owner's B4): a requirement of N (`GT.coverage_of`: the register's ids minus the implementation-only ones, minus the
    ones the base slice shows untouched, minus `outside_diff` with a `where`) the table calls `not_implemented` is a `pending_implementation`
    record WITHOUT any word of the person: the answer to the stop does not turn a missing behaviour into a passing delivery. An
    `outside_diff` with `where: none` is the same record only while a person's word stands for the current digest (`GT.stop_word`: the
    promise of the price the person paid to go on). `partial` and `unknown` give none (their own roads say so). A story with no diff table, or
    a table that cannot be read, gives none here (`_grounding_candidates` says the unreadable one). Raises only what the readers raise."""
    import grounding_table as GT
    import planning_contract as PC
    table, _problem = PC.read_grounding(artifacts)
    if table is None or not isinstance(table.data, dict) or table.data.get("implementation_source") != "diff":
        return []
    cov = GT.coverage_of(artifacts)
    if cov.get("road") == "unknown":   # F-2: an unreadable policy or register is ONE factory record (the guard above), never "nothing to say"
        raise ValueError(str(cov.get("reason") or "the coverage could not be established"))
    outside = [o for o in cov.get("outside") or [] if isinstance(o, dict)]
    out, word = [], None
    if any(o.get("state") == "outside_diff" for o in outside):
        pipeline = C.load_json(artifacts / "pipeline.json")
        word = GT.stop_word(pipeline if isinstance(pipeline, dict) else {}, GT.COVERAGE_STOP_BLOCK, GT.coverage_digest(artifacts, cov))
    for entry in outside:
        if entry.get("state") == "not_implemented" or (entry.get("state") == "outside_diff" and word is not None):
            out.append(pending_implementation_record(str(entry.get("r"))))
    return out


def _grounding_records(artifacts: Path, doc: dict, facts: dict) -> list:
    import coverage_contract as CC
    import grounding_table as GT
    import planning_contract as PC
    candidates, unreadable = _grounding_candidates(artifacts)
    out = [{"text": f"factory: {name} exists and could not be read, so its bug candidates are not known to be covered", "kind": "factory_record",
            "case": "", "ref": "", "source": "check"} for name in unreadable]
    if not candidates:
        return out
    rows = [row for row in CC.plan_rows(artifacts) if isinstance(row, dict)]
    path = PC.story_plan_path(artifacts)
    plan = C.load_json(path) if path is not None else {}
    decided = {str(e.get("ref") or "").strip().strip("`"): e for e in GT.not_planned_of(artifacts, "", plan or None)}
    ledger_rows = {str(r.get("ref")): str(r.get("state") or "") for r in (doc.get("rows") or [])
                   if isinstance(r, dict) and r.get("kind") == "plan_row"}
    for cand in candidates:
        ref = cand["ref"]
        named = [row for row in rows if (ref in PC.grounding_refs(row)["K"] if ref.startswith("K-") else ref in PC.row_requirements(row))]
        testing = [row for row in named if PC.row_tests_it(row)]
        said = decided.get(ref)
        how = GROUNDING_HOW.format(ref=ref) + (f" Recorded for {ref}: {' - '.join(str(said.get(k)) for k in ('state', 'reason') if said.get(k))}."
                                              if said and (said.get("state") or said.get("reason")) else "")
        subject = cand["subject"]
        if not testing:
            why = (f"the plan rows that name it ({', '.join(str(r.get('id')) for r in named)}) check nothing: "
                   f"{', '.join(str(r.get('disposition') or 'no disposition') for r in named)}" if named else "no plan row names it")
            out.append(bug_candidate_record(ref, cand["requirements"], f"{subject} - {why}", how, cand["source"]))
            continue
        ids = [str(r.get("id")) for r in testing]
        held = [r for r in testing if str(r.get("id")) in ledger_rows]
        if not held:
            out.append(bug_candidate_record(ref, cand["requirements"], f"{subject} - the check {', '.join(ids)} is planned but could not be "
                                            "linked to a result in the ledger", how, cand["source"]))
            continue
        states = [C.ledger_state_prefix(ledger_rows[str(r.get("id"))]) for r in held]
        if any(s.startswith("failed") for s in states) or L.NOT_VERIFIED_UNCONFIRMED in [ledger_rows[str(r.get("id"))] for r in held]:
            continue        # a red is an ordinary bug; a Then nobody confirmed is already the ledger's own kind
        green = [r for r, s in zip(held, states) if s == "passed_green"]
        if not green:
            continue        # not executed: its own kind of row says so
        if all(_oracle_unanswered(artifacts, r) for r in green):
            first = green[0]
            out.append({"text": "", "kind": "unconfirmed_expectation", "case": "", "ref": ref, "item_key": ref,
                        "requirements": list(cand["requirements"]), "source": cand["source"],
                        "to_check": f"{subject} - {first.get('id')} passed, but nobody confirmed the value it expects",
                        "how": "Needed: your answer to the question on that check"})
    return out


def _oracle_unanswered(artifacts: Path, row: dict) -> bool:
    """A row flagged `oracle_unknown` whose open question nobody settled (or that names none): the green run proved nothing against an
    expected value anybody confirmed (P20, FR-58). A row without the flag: False. A question register that could not be read: True (FR-59)."""
    if not row.get("oracle_unknown"):
        return False
    import planning_contract as PC
    found = PC.open_questions_of_plan_rows(artifacts, [str(row.get("id"))])
    if found.get("unknown") or found.get("open"):
        return True
    # nothing open: answered only if the row NAMES a question the register holds (a ref to nowhere is no answer, FR-59)
    import question_register as QR
    held = {str(q.get("id")).strip() for q in QR.load(artifacts).get("questions") or [] if isinstance(q, dict)}
    named = [str(x).strip() for x in (row.get("question_refs") or []) if isinstance(x, str)]
    named += [str(k).strip() for k in (row.get("if_answered") or {}) if isinstance(row.get("if_answered"), dict)]
    return not any(x in held for x in named)


def assess(artifacts: Path, finalized_delivery: bool = False) -> dict:
    artifacts = Path(artifacts)
    facts = gather(artifacts)
    records: list = []

    def own(texts, kind: str) -> None:
        records.extend({"text": str(t), "kind": kind, "case": "", "ref": "", "source": "check"} for t in texts)

    # t-2181 PC-5 (C10, B4): a story held for code (`contract.awaiting`: awaiting or stopped) is read FIRST and gives ONE record, kind
    # `awaiting_implementation` (`no`, owner product), with the words of its `cause`. No other check is run (no bug candidate, no gate B
    # reason): a pre-code story has no result a new bug could rest on, and the diff-story `pending_implementation` below stays a
    # different, ordinary record (`no`). ONE exception (AR-27, the Lead's fork): a RED a recorded S7 verdict already stands behind (a
    # ledger row `failed:*`, kind `red`) keeps its own record beside the hold - C13 refuses S6-S8 while a story is held, so such a red
    # was written BEFORE the hold (a story that went through S7 and parked later: rework after `reality=absent`, a re-park). The
    # verdict is `no` either way, so it cannot get weaker; the bug just never disappears from the report under its own owner.
    hold = C.awaiting(facts["pipeline"])
    held = hold["state"] != "none"
    kinds_doc, gap_read = DV.load_kinds()[0], ([], "")
    if held:
        records.append(awaiting_record(hold, kinds_doc))
        doc = mark_handed(L.build(artifacts), artifacts)
        records += [rec for rec in ledger_records(doc, facts) if rec["kind"] == RED_KIND]
    else:
        own(witness_reasons(artifacts), "factory_record")
        records += completeness_records(artifacts, facts)
        own(lifecycle_reasons(artifacts), "factory_record")
        own(case_version_reasons(artifacts), "factory_record")
        own(delivery_manifest_reasons(artifacts, finalized=finalized_delivery), "factory_record")
        records += traceability_records(artifacts, facts)
        own(run_reasons(artifacts), "run_not_deliverable")
        own(triage_reasons(artifacts), "triage_gap")
        own(factory_finding_reasons(artifacts), "factory_record")
        records += handed_records(artifacts)
        records += blocked_records(artifacts, facts)
        records += unverified_records(artifacts, facts)

        doc = mark_handed(L.build(artifacts), artifacts)
        records += ledger_records(doc, facts)
        records += unprepared_records(doc)
        # F1 (P21): no case with an observed failure reads kind `handed` - the hand-off record of a case whose ledger row is
        # `failed:*` (any triage class but the stand's: an ENV_ISSUE is the person's answer to the card, and `handed` is one
        # of its words) is dropped; the failed row's own kind decides, and `after_checks` stays out of reach while it stands -
        # EXCEPT `failed:ASSERT_STRICTER` (HF2-18, N6): the analyst's own word, held by its control experiment
        # (`contract.triage_control_problems`; a row without it is a `triage:` reason, so `no`), reads kind `assert_stricter`
        # (`after_checks`) with no recorded word of the person - the one observed failure that does, besides an ENV_ISSUE the
        # person answered. The owner's order (25.10): such a red is not a bug; it is a line in "Left with you".
        red = _red_cases(doc, facts, _stricter_cases(facts), kinds_doc)
        # HF2-3 (F6): only the WHOLE-case hand-off goes. A record that carries a Then (`handed_records`: a Then the person took
        # beside the case's own result) is a Then no run answered, and the case's red does not answer it either (the person's
        # debt stays on the list beside the `failed:*` row)
        records[:] = [rec for rec in records
                      if not (rec["kind"] == "handed" and not rec.get("then") and _bare(rec.get("case") or "") in red)]
        own(["manual evidence export: " + str(issue) for issue in doc.get("manual_evidence", {}).get("errors", [])],
            "factory_record")
        own(coverage_reasons(doc, handed_plan_rows(artifacts)), "coverage_gap")
        # TQ1-20: POSITION after the filter above (it must not drop a branch) and before `decide` (which must see it).
        records += branch_records(artifacts)
        # G2-3 (FR-22): the bug candidates; same position as the branches (after the filter, which must not drop one; before `decide`)
        records += grounding_records(artifacts, doc, facts)
        # RN1-15: the requirements the person called not implemented; same position (after the filter, before `decide`)
        gap_read = _read_product_gaps(artifacts)       # once per assess: the records and the finding read the same carrier (F10)
        records += product_gap_records(artifacts, facts, gap_read)

    # THE VERDICT: from the kinds, never from a sentence (F1). `decide` is `no` for a kind it does not know and for
    # a file it cannot read; the person's third word needs at least one item that counts (`VERDICT_WITHOUT_ITEMS`).
    word, verdict_findings = DV.decide([rec["kind"] for rec in records])
    items = build_left_items(records, facts, kinds_doc)
    regression, regression_findings = regression_record(artifacts)
    if word == "after_checks" and not DV.count_items(items, kinds_doc):
        word = "no"
        verdict_findings.append({"code": "VERDICT_WITHOUT_ITEMS", "entity": "task", "owner": "factory",
                                 "detail": "factory: the checks say some of the checking is left with you, but no item "
                                           "of it could be listed, so the verdict is `no` until the factory says what "
                                           "it is"})
        records.append({"text": "factory: some of the checking is left with you, but no item of it could be listed "
                                "(the factory's own gap)", "kind": "verdict_without_items", "case": "", "ref": "",
                        "source": "check"})
    items = items + [regression]
    texts_by_kind: dict = {}
    reasons = []
    for rec in records:
        if rec["text"] and DV.verdict_of_kind(rec["kind"], kinds_doc) in ("no", None):
            reasons.append(rec["text"])
            texts_by_kind.setdefault(rec["text"], rec["kind"])
    if word == "no" and not reasons:
        # a `no` always says why (FR-20, FR-41): a kind that carried no sentence is told by name
        names = ", ".join(sorted({str(rec["kind"]) for rec in records
                                  if DV.verdict_of_kind(rec["kind"], kinds_doc) in ("no", None)})) or "none"
        reasons.append(f"factory: the delivery verdict is `no` but no check wrote a reason for it (kinds: {names})")
        texts_by_kind[reasons[-1]] = "factory_record"

    seen, unique = set(), []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)

    defects = case_defect_cases(facts)
    case_lift = case_ownership(artifacts)
    context = {"factory_refs": factory_owned_refs(artifacts), "case_lift": case_lift,
               "cfg": C.case_config(artifacts), "case_defect_cases": defects,
               "case_defect_maps": case_defect_maps(artifacts, facts, case_lift) if defects else {}}
    # The task's own terms first (FR-20). The list used to come out in the order the checks run,
    # which is the order of our own pipeline: on run 5 the one true reason — a
    # requirement the product does not deliver — was behind 43 lines of our bookkeeping. The sort
    # is stable, so inside an owner the checks keep their order, and `L.OWNER_ORDER` is the same
    # order the ledger prints its headings in.
    order = {owner: rank for rank, owner in enumerate(L.OWNER_ORDER)}
    owners = {reason: reason_record(reason, context)["owner"] for reason in unique}
    unique = sorted(unique, key=lambda reason: order.get(owners[reason], len(order)))
    gap_of_text = {rec["text"]: rec for rec in records if rec["kind"] == "product_gap"}
    reason_records = []
    for reason in unique:
        record = reason_record(reason, context)
        record["kind"] = texts_by_kind.get(reason, "factory_record")    # the kind travels with the record (F1)
        if reason in gap_of_text:   # RN1-15: the requirement and the person's words, typed, for the report's head
            record["requirements"], record["words"] = gap_of_text[reason]["requirements"], gap_of_text[reason]["words"]
        reason_records.append(record)
    # `delivery_ready` is the bool of the word, exactly `yes` (Q2): the 12 readers that read it as a truth value stay
    # safe, and `after_checks` is NOT ready for any of them - the readers that must open on it read `word_of`.
    doc["delivery_verdict"] = word
    doc["delivery_ready"] = word == "yes"
    doc["reasons"] = unique
    doc["reason_records"] = reason_records
    doc["left_items"] = items
    # P20, F7: a Then whose expected value nobody confirmed (`not_verified:expectation_unconfirmed`)
    # is the person's debt. It is listed here, beside the reasons and never among them: a reason
    # holds `delivery_ready`, and an unconfirmed expectation is a gap in the report ("Left with
    # you": the Then, the question, "Needed: your answer to Q-n"), not a found discrepancy
    # (FR-21/FR-22 govern those). `ledger_reasons`' `blocking` set does not name `not_verified`.
    doc["person_debts"] = L.person_debts(doc)
    # Beside the reasons, never inside them: a proof the factory published in the wrong place
    # is visible to whoever reads the ledger and asks nothing of the person, and it cannot
    # turn `delivery_ready` to no (TP2-2553).
    typed = [{"code": "DEFERRED_WITHOUT_DECISION", "entity": str(rec.get("ref") or "?"), "owner": "factory",
              "detail": f"factory: {rec.get('ref')} is deferred by decision, but no word of the person's is recorded "
                        "for it (no gate waiver covers it)"}
             for rec in records if rec["kind"] == "deferred_undecided"]
    typed += [{"code": "HANDED_WITHOUT_COMMAND", "entity": str(rec.get("ref") or "?"), "owner": "factory",
               "detail": f"factory: {rec.get('ref')} was handed to the person with no command recorded to run it - "
                         "the factory's gap, not theirs"}
              for rec in records if rec.get("no_command")]
    doc["factory_findings"] = (binding_proof_findings(artifacts) + classifier_findings(unique)
                               + owner_lift_findings(unique, context) + product_gap_findings(artifacts, gap_read)
                               + verdict_findings + regression_findings
                               + not_executed_findings(artifacts, facts) + factory_data_gap_findings(artifacts, facts) + typed)
    # `delivery_ready` stays conservative — a gap with no decision attached does not deliver,
    # whoever owns it. What changes is that the gate can now say WHOSE it is: a story whose
    # `blocked_by` is only `["factory"]` is not a story about an unready product.
    doc["blocked_by"] = [owner for owner in L.OWNER_ORDER
                         if any(record["owner"] == owner for record in reason_records)]
    L.write(artifacts, doc)
    return doc


def main() -> None:
    C.force_utf8()
    ap = argparse.ArgumentParser(description="Delivery readiness aggregator")
    ap.add_argument("artifacts", help="qa-factory/artifacts/<TICKET>/")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--finalized-delivery", action="store_true",
                    help="verify the post-S9 compact manifest, including retro.md")
    args = ap.parse_args()

    artifacts = Path(args.artifacts)
    if not artifacts.exists():
        print(f"no such artifacts directory: {artifacts}", file=sys.stderr)
        sys.exit(1)

    doc = assess(artifacts, finalized_delivery=args.finalized_delivery)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(L.render(doc), end="")
        print()
        word = DV.word_of(doc) or "no"
        print(f"delivery_ready: {word}")
        for owner, reasons in L.reasons_by_owner(doc).items():
            print(f"\n{L.OWNER_HEADINGS[owner]}:")
            for reason in reasons:
                print(f"  - {reason}")
        if word == "after_checks":
            counting = [i for i in doc.get("left_items") or [] if i.get("counts")]
            print(f"\nReady once the checks left with the person are done ({len(counting)}):")
            for item in counting:
                print(f"  - {item.get('ref')} ({item.get('kind')})" + (f": {item['how']}" if item.get("how") else ""))
        # The interim of "the person is told, not asked" (R-208.6): why a reason stands among the
        # factory's, or why none could be re-labelled. Only these findings; the others stay in the ledger.
        lifted = [f for f in doc.get("factory_findings") or [] if str(f.get("code") or "").startswith("OWNER_LIFT")]
        if lifted:
            print("\nWhy some reasons are listed as the factory's:")
            for finding in lifted:
                print(f"  - {finding['detail']}")
        if word == "no":
            if doc.get("blocked_by") == ["factory"] and not L.factory_coverage_gaps(doc):
                print("\nNothing here says the product is not ready: every reason left is a defect "
                      "of the factory itself, and it is ours to fix.")
            print("\nAt gate B there is no \"open MR\" item while this says no — there is "
                  "\"deliver with known gaps\", and only with a stated reason.")
        elif word == "after_checks":
            print("\nAt gate B the Draft MR may be opened: its description carries what is left with the person.")
    sys.exit(0 if doc["delivery_ready"] else 1)


if __name__ == "__main__":
    main()
