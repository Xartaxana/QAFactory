"""A stale block is not the story's final state, and a reason says whose problem it is.

an environment block states what the stand could do at one moment. A later terminal
attempt of the SAME instance answers it — the block becomes history and stops deciding.
Before 0.7.5 nothing could clear one: a `blocked_by_env` in the manifest short-circuited
the ledger before any result was read, and `finalize_task` made `env_preflight` blocked
from every historical row (0.6.0 feedback on TP2-2530, item 2).

`delivery_ready: no` was one flat list, so the factory's own reducer defect read to
the person exactly like an unready product (same feedback, item 3).
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    GOOD, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir,
)

sys.path.insert(0, str(SCRIPTS))
import check_delivery as D  # noqa: E402
import contract as C  # noqa: E402
import delivery_summary as S  # noqa: E402
import finalize_task as F  # noqa: E402
import ledger as L  # noqa: E402


# A reason of check_delivery.py, read out of its source: appended to a list of reasons or
# returned as one, or (since t-305 N8) the `"text"` of a typed record, a `(text, kind, case)` tuple,
# a `text = ` or an `own([` argument. A bare `return "factory"` inside reason_owner is an owner, not
# a reason, so the list bracket, the `.append(` or one of those carriers is required.
REASON_LITERAL_RE = re.compile(
    r"(?:\w+\.append\s*\(\(?|reasons \+= \[|return \[|\{\"text\":|\btext = \(?|\bown\(\[)\s*\n?\s*f?\"([^\"]*)\"")


def state_of(doc: dict, ref: str) -> str:
    return next((row["state"] for row in doc["rows"] if row["ref"] == ref), "<absent>")


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def block(name: str, started: str, **payload) -> tuple:
    return name, dict(payload, block_id=name, attempt_started_at=started)


def reduce_blocks(label: str, *blocks) -> dict:
    """One throwaway task holding exactly these run blocks, reduced."""
    root = temp_dir("qa-env-supersede-")
    try:
        task = root / "qa-factory" / "artifacts" / label
        for name, payload in blocks:
            write(task / "work" / "run-blocks" / (name + ".json"), payload)
        report, _ = F.reduce(task)
        return report
    finally:
        cleanup(root)


def manifest_supersession() -> None:
    """A manifest `unresolved[]` environment block against a later green of that instance."""
    root = temp_dir("qa-manifest-supersede-")
    try:
        art = root / "QA-1"
        shutil.copytree(GOOD, art)
        path = C.artifact(art, "automation-manifest.json")
        manifest = C.load_json(path)
        manifest["unresolved"] = [
            {"case": "TC-001", "plan_row": "TS-1", "reason": "blocked_by_env"},
            {"case": "TC-999", "plan_row": "TS-3", "reason": "blocked_by_env"},
        ]
        path.write_text(json.dumps(manifest), encoding="utf-8")

        doc = L.build(art)
        check_eq("a later green of the same instance supersedes the manifest env block",
                 state_of(doc, "TS-1"), "passed_green")
        check_eq("a block with no later result keeps blocking exactly as before",
                 state_of(doc, "TS-3"), "env_blocked:user")
        superseded = {row["ref"] for row in doc["superseded_blocks"]}
        check("the superseded block stays visible as history", "TC-001" in superseded,
              str(doc["superseded_blocks"]))
        check_not_in("and the block still in force is not listed as superseded", "TC-999",
                     str(doc["superseded_blocks"]))
        check_in("ledger.md names the superseded block", "Superseded environment blocks",
                 L.render(doc))

        # A human decision is not an environment fact: nothing in a run may cancel it.
        manifest["unresolved"] = [{"case": "TC-001", "plan_row": "TS-1",
                                   "reason": "deferred_by_decision:gate A"}]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        check_eq("a decided deferral is never superseded by a green",
                 state_of(L.build(art), "TS-1"), "deferred_by_decision")
    finally:
        cleanup(root)


def reducer_supersession() -> None:
    env = {"area": "checkout", "owner": "user", "case": "TC-900", "instance_id": "inst-1"}
    other = {"area": "billing", "owner": "factory", "instance_id": "inst-2"}
    green = {"case": "TC-900", "instance_id": "inst-1", "status": "passed", "attempt_id": "a2"}

    # File order says the env block came first; the attempt clock says it came last. The
    # attempt clock is the one that decides.
    report = reduce_blocks("QA-ORDER",
                           block("a-env", "2026-09-20T12:00:00Z", env_blocked=[env]),
                           block("z-green", "2026-09-20T09:00:00Z", results=[green]))
    check_eq("an env block recorded after the green still blocks", report["env_preflight"], "blocked")
    check_eq("and it is not marked superseded", report["env_blocked"][0].get("superseded"), None)

    report = reduce_blocks("QA-GREEN-AFTER",
                           block("z-env", "2026-09-20T09:00:00Z", env_blocked=[env, other]),
                           block("a-green", "2026-09-20T12:00:00Z", results=[green]))
    check_eq("one instance answered while another is still down leaves the preflight blocked",
             report["env_preflight"], "blocked")
    marked = {str(row.get("instance_id")): bool(row.get("superseded")) for row in report["env_blocked"]}
    check_eq("the answered block is marked superseded", marked.get("inst-1"), True)
    check_eq("an unrelated instance is untouched", marked.get("inst-2"), False)
    check_eq("every historical row is kept — none is dropped", len(report["env_blocked"]), 2)
    check_eq("current_env_blocked holds only what still decides",
             [row.get("instance_id") for row in report["current_env_blocked"]], ["inst-2"])
    check_eq("and the superseding attempt is named",
             report["env_blocked"][0]["superseded_by"]["attempt_id"], "a2")

    report = reduce_blocks("QA-CLEARED",
                           block("z-env", "2026-09-20T09:00:00Z", env_blocked=[env]),
                           block("a-green", "2026-09-20T12:00:00Z", results=[green]))
    check_eq("with nothing left in force the preflight passes", report["env_preflight"], "pass")
    check_eq("the row is still in the report", len(report["env_blocked"]), 1)
    check_eq("the ledger reads the owner from what still blocks, not from history",
             L._env_owner(report), "user")

    # A skip is not proof that the stand came back.
    report = reduce_blocks("QA-SKIP",
                           block("z-env", "2026-09-20T09:00:00Z", env_blocked=[env]),
                           block("a-skip", "2026-09-20T12:00:00Z", results=[
                               dict(green, status="skipped")]))
    check_eq("a skipped later attempt supersedes nothing", report["env_preflight"], "blocked")


def reason_owners() -> None:
    cases = [
        ("ledger: TS-2 is `failed:APP_BUG` (TC-002)", "product"),
        ("ledger: TS-2 is `failed:TEST_BUG` (TC-002)", "factory"),
        ("ledger: TS-2 is `failed:ENV_ISSUE` (TC-002)", "environment"),
        ("ledger: TC-1 is `env_blocked:user` (checkout)", "environment"),
        ("ledger: TC-1 is `review_rejected` (tests/test_x.py)", "review"),
        # FR-35 / FR-19: a verdict the vocabulary lacks is our defect, never the critic's rejection;
        # an unverified one is the person's debt (D-0013) and is owned even though it never blocks.
        ("ledger: TC-1 is `review_unrecognised:maybe` (tests/test_x.py)", "factory"),
        ("ledger: TC-1 is `review_unverified` (tests/test_x.py)", "environment"),
        ("ledger: TC-1 is `not_verified_flaky` (timing)", "factory"),
        ("ledger: TS-4 is `not_executed:no result recorded` (TC-004)", "product"),
        ("review: no critic verdict for TC-001", "review"),
        ("triage: the failure ti_x has no verdict in triage.json", "factory"),
        # t-319 K7 (t-311 Q1): ONLY a manual check nobody judged is the review's; every other `triage:` stays ours
        ("triage:manual: the failure TC-5 has no verdict in triage.json", "review"),
        ("triage:manual: a failed or inconclusive manual check has no verdict in triage.json - manual check #1 has no "
         "case, instance_id or test, so no row can name it", "review"),
        ("triage: a failed result row has no verdict in triage.json - failed result row #1 has no instance_id, test_id, "
         "test or case, so no row can name it", "factory"),
        ("triage: the row x names 2 failures (x[json], x[multi]) and is a verdict for none of them", "factory"),
        ("triage: ti_x is FLAKY and was not fixed (fix_result: none)", "factory"),
        ("triage: ti_x carries verdict 'MAYBE' outside the matrix", "factory"),
        ("factory: ti_x — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row", "factory"),
        ("traceability: R-4 has no terminal outcome (nothing)", "product"),
    ]
    for reason, owner in cases:
        record = D.reason_record(reason)
        check_eq(f"owner of {reason[:34]!r}", record["owner"], owner)
        check(f"and it is in the closed list ({owner})",
              record["owner"] in C.DELIVERY_REASON_OWNERS, record["owner"])

    # TP1-15045: the first line the person read was "24 reasons on the product side", and
    # about twenty of them were the factory describing its own bookkeeping.
    bookkeeping = [
        "test instance test_x has stale case link TC-003/cv_10e94fde2940",
        "test instance test_x links case TC-003 not pinned by this story",
        "case TC-003: approved green test lacks current pinned CaseVersion proof",
        "test instance test_x carries stale proof or review",
    ]
    for reason in bookkeeping:
        check_eq(f"our own bookkeeping is ours: {reason[:40]!r}",
                 D.reason_record(reason)["owner"], "factory")
    context = {"factory_refs": {"TC-009", "TC-014"}}
    check_eq("a STALE unresolved row is not a product gap",
             D.reason_record("blocked on the stand: TC-014 is held by the stand and waits for your answer on its stand-gap card at gate B",
                             context)["owner"], "factory")
    check_eq("a STALE unresolved row of the old `manifest:` family is ours too (RD1-4 K2)",
             D.reason_record("manifest: TC-014 is impossible and carries no gate decision", context)["owner"], "factory")
    check_eq("and so is a STALE row of the manifest-record family (RD1-4 A')",
             D.reason_record("manifest record: TC-014 unresolved with reason 'x' outside ['a']", context)["owner"],
             "factory")
    check_eq("a partial the reducer could not join is not a product gap",
             D.reason_record("traceability: R-13 has no terminal outcome "
                             "(TC-009: run result 'partial' is not terminal)", context)["owner"],
             "factory")
    check_eq("but a partial of a case the reducer joined fine stays the product's",
             D.reason_record("traceability: R-4 has no terminal outcome "
                             "(TC-004: run result 'partial' is not terminal)", context)["owner"],
             "product")


def reason_families_are_declared_in_data() -> None:
    """FR-19: the owner of a reason family is declared in data, and an undeclared one is a defect.

    Run 5 printed 52 `product` reasons to the person and 43 of them were the factory's own
    bookkeeping. The owner was not unknown — `OWNER_BY_CODE` knew it — it was lost whenever a
    reason travelled as text without its typed code: measured on the forty-two literals this
    script can emit, fourteen answered `factory`/`environment` with the code and `product`
    without it. The table is what closes that, so the table is what this walk holds.
    """
    table = D.reason_owner_table()
    check_eq("the default owner is in the closed list", table["default_owner"] in
             C.DELIVERY_REASON_OWNERS, True)
    starts = [str(family.get("text_starts") or "") for family in table["families"]]
    check("every family names the words a reason starts with", all(starts), str(starts))
    check_eq("and none is declared twice", len(set(starts)), len(starts))
    for family in table["families"]:
        check(f"{family['text_starts']!r} names an owner from the closed list",
              family.get("owner") in C.DELIVERY_REASON_OWNERS, str(family.get("owner")))
        check(f"{family['text_starts']!r} says why that owner",
              len(str(family.get("why") or "").strip()) > 20, str(family.get("why")))
    check("the families are tried longest first, so a longer family wins",
          starts == sorted(starts, key=lambda s: -len(s)), str(starts[:3]))

    # The walk to the source: every reason this script can emit, read out of the script, not out
    # of memory (FR-26). A new reason family fails this until the data file declares it.
    source = (SCRIPTS / "check_delivery.py").read_text(encoding="utf-8")
    heads, unmatched = set(), []
    for match in REASON_LITERAL_RE.finditer(source):
        head = match.group(1).split("{", 1)[0]
        if head.strip():
            heads.add(head)
    for head in sorted(heads):
        # The literal stops where its first interpolation starts; a value follows it at runtime.
        if D.reason_family(head + "sample") is None:
            unmatched.append(head)
    check_eq(f"every reason literal of check_delivery.py has a declared family ({len(heads)})",
             unmatched, [])
    matched = {str(D.reason_family(head + "sample")["text_starts"]) for head in heads
               if D.reason_family(head + "sample")}
    check_eq("and no family is declared that no reason of this script produces",
             sorted(set(starts) - matched), [])

    # What the person reads, family by family. Not copied from the script's output: these are
    # the run-5 families and the four that were already right, with the owner each must have.
    expected = [
        ("delivery manifest: stale hash for test-report.md", "factory"),
        ("manual evidence export: row 3 has no evidence path", "factory"),
        ("manifest witness: no evidence line for R-1-OB1", "factory"),
        ("automation-manifest.json is missing — S5 produced no manifest to check", "factory"),
        ("check_witness.py could not be run (OSError: no python)", "factory"),
        ("run-report.json: execution_status 'weird' outside ['passed', 'failed']", "factory"),
        ("plan TS-12 is `automate` but no case names it as its plan row", "factory"),
        ("case TC-003: its test is approved and green, but the case file still says Draft",
         "factory"),
        ("test instance tests/test_x.py::test_a requires current sensitivity_proof", "factory"),
        ("triage: the failure ti_x has no verdict in triage.json", "factory"),
        ("traceability: requirements-register.md has no R rows — nothing was traced", "factory"),
        ("handed to the person: 2 test(s) nothing here could run — ti_x", "environment"),
        ("review: no critic verdict for TC-001", "review"),
        # The product's own, and they stay the product's.
        ("traceability: R-4 has no terminal outcome (nothing)", "product"),
        # RD1-21: evidence left missing by the factory's tools or coverage is the factory's; a red run or an open oracle stays the product's
        ("coverage: R-1-OB1 — no instance proves it", "factory"),
        ("coverage red: R-1-OB1 — no instance proves it", "product"),
        ("subtask TP1-1 is still In Progress — the story's own scope is not closed", "product"),
        ("ledger: TC-003 is `impossible` (the product has no such surface)", "product"),
        # RD1-4 K1/K3/A': the stand's hold is the environment's; an `impossible` row stays the product's; a malformed unresolved
        # row is a defect of our own manifest record
        ("blocked on the stand: TC-1 is held by the stand and waits for your answer on its stand-gap card at gate B", "environment"),
        ("manifest: TC-003 is impossible and carries no gate decision", "product"),
        ("manifest record: TC-5 unresolved with reason 'too hard' outside ['impossible'] + deferred_by_decision:<gate>",
         "factory"),
    ]
    for reason, owner in expected:
        check_eq(f"owner of {reason[:44]!r}", D.reason_record(reason)["owner"], owner)
        check_eq("and the text alone answers the same as the typed code",
                 D.reason_owner(reason), D.reason_record(reason)["owner"])

    # RD1-4 K7/K8: the new sentence is classified (no finding) and passes the report-kind text check
    import human_text
    stand_sentence = "blocked on the stand: TC-1 is held by the stand and waits for your answer on its stand-gap card at gate B"
    check_eq("K8: the stand sentence is not an unclassified reason", D.classifier_findings([stand_sentence]), [])
    check_eq("K8: nor is the manifest-record sentence",
             D.classifier_findings(["manifest record: TC-5 unresolved with reason 'x' outside ['a']"]), [])
    check_eq("K7: the stand sentence passes human_text.problems(kind='report')",
             human_text.problems(stand_sentence, kind="report"), [])

    # An unrecognised reason: the default is printed, and that it IS the default is printed too.
    invented = "some new check: the widget refused to widget"
    check_eq("an undeclared reason falls to the default", D.reason_owner(invented), "product")
    findings = D.classifier_findings([invented, "delivery manifest: files must be a list"])
    check_eq("and exactly the undeclared one is a defect of the classifier", len(findings), 1)
    check_eq("owned by the factory, not the person", findings[0]["owner"], "factory")
    check_in("naming the data file to add the family to", "delivery-reason-owners.json",
             findings[0]["detail"])
    check_in("and saying the owner printed is a default, not a reading",
             "reported as `product` by default", findings[0]["detail"])

    # The mutation: put run 5's defect back by dropping one family, and the owner is lost again.
    table = D.reason_owner_table()
    kept = table["families"]
    try:
        table["families"] = [f for f in kept if f["text_starts"] != "delivery manifest:"]
        check_eq("without its family, our own manifest reads as the product's",
                 D.reason_owner("delivery manifest: files must be a list"), "product")
        check_eq("and it is reported as unclassified while it does",
                 [f["code"] for f in
                  D.classifier_findings(["delivery manifest: files must be a list"])],
                 ["REASON_OWNER_UNCLASSIFIED"])
    finally:
        table["families"] = kept


def factory_defects_are_not_the_product() -> None:
    root = temp_dir("qa-factory-owner-")
    try:
        art = root / "QA-1"
        shutil.copytree(GOOD, art)
        path = C.artifact(art, "run-report.json")
        report = C.load_json(path)
        report["factory_findings"] = [{"code": "INSTANCE_MANIFEST_JOIN_FAILED", "entity": "ti_x",
                                       "attempt_id": "a1", "detail": "no manifest row"}]
        path.write_text(json.dumps(report), encoding="utf-8")

        doc = D.assess(art)
        check("the reducer's own defect list finally reaches gate B",
              any("INSTANCE_MANIFEST_JOIN_FAILED" in reason for reason in doc["reasons"]),
              str(doc["reasons"]))
        check_eq("delivery_ready stays conservative", doc["delivery_ready"], False)
        check_eq("but the machine field says whose it is", doc["blocked_by"], ["factory"])
        rendered = L.render(doc)
        check_in("the ledger separates the factory's defects", "Factory defects", rendered)
        check_in("and says the product is not the one on the hook",
                 "Nothing here says the product is not ready", rendered)
        check_not_in("with no product heading invented for it",
                     "What blocks delivery on the product side", rendered)

        summary = S.build(art, doc)
        check_eq("the delivery summary groups by owner", list(summary["reasons_by_owner"]),
                 ["factory"])
        check_eq("and carries the same machine field", summary["blocked_by"], ["factory"])
        check_in("the rendered fragment keeps the two lists apart", "Factory defects",
                 S.render(summary))

        # Add a product-side gap: now both headings appear and the reassurance is withdrawn.
        mpath = C.artifact(art, "automation-manifest.json")
        manifest = C.load_json(mpath)
        manifest["unresolved"] = [{"case": "TC-003", "plan_row": "TS-9", "reason": "impossible"}]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        mixed = D.assess(art)
        check_eq("a product-side gap beside it puts both owners on the board",
                 mixed["blocked_by"], ["product", "factory"])
        # FR-20: the list itself, not only the rendering, puts the task's own terms first. It
        # used to come out in the order our checks run, and on run 5 the one true reason stood
        # behind 43 lines of our own bookkeeping.
        check_eq("the first reason is the product's", D.reason_record(mixed["reasons"][0])["owner"],
                 "product")
        check_eq("and ours are last", D.reason_record(mixed["reasons"][-1])["owner"], "factory")
        rendered = L.render(mixed)
        check_in("the product side gets its own heading",
                 "What blocks delivery on the product side", rendered)
        check_in("and the factory's defects keep theirs", "Factory defects", rendered)
        check_not_in("the factory-only reassurance is withdrawn",
                     "Nothing here says the product is not ready", rendered)
    finally:
        cleanup(root)


def proof_levels_in_the_summary() -> None:
    """D-0010/D-0012 in the delivery summary: one line saying how the live tests were proven, from
    the ledger's own rows and the vocabulary's words - and nothing at all for a legacy ledger,
    which claims no level. D-0013: the tests the critic could not verify go to the person."""
    root = temp_dir("qa-summary-levels-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        ledger = L.build(art)
        plan = [row for row in ledger["rows"] if row["kind"] == "plan_row"]

        def summary_of(tests):
            return S.build(art, dict(ledger, rows=plan + tests))

        def test(ref, level="absent", state="passed_green", **extra):
            row = {"ref": ref, "kind": "test", "state": state, "detail": ref}
            if level != "absent":
                row["proof_level"] = level
            row.update(extra)
            return row

        real = S.build(art, ledger)
        check_eq("the ledger of the good set: its one test asked for nothing", real["proof_levels"],
                 {L.PROOF_NOT_REQUIRED: 1})
        text = S.render(real)
        check_in("the line names it in the vocabulary's words",
                 "Tests by proof level: not probed (unchanged test): 1", text)
        lines = text.splitlines()
        table = next(i for i, line in enumerate(lines) if line.startswith("| ") and line.count("|") > 9
                     and line[2:3].isdigit())
        check("and it stands right after the table's own note, before any list",
              lines.index("Tests by proof level: not probed (unchanged test): 1") - table <= 4,
              str(lines[table:table + 6]))

        legacy = summary_of([test("a"), test("b", state="review_rejected")])
        check_eq("a legacy ledger (no proof_level on its rows) counts nothing", legacy["proof_levels"], {})
        check_not_in("and prints no level line", "Tests by proof level", S.render(legacy))

        mixed = summary_of([test("a", "live"), test("b", "live"), test("c", "catches_broken_product"),
                            test("d", None), test("e", L.PROOF_NOT_REQUIRED), test("f", L.PROOF_UNKNOWN),
                            test("g", "live", dead=True), test("h", "from_the_future")])
        check_eq("counts over the live test rows, by level id / none / not_required / unknown",
                 mixed["proof_levels"], {"live": 2, "catches_broken_product": 1, "none": 1,
                                         L.PROOF_NOT_REQUIRED: 1, L.PROOF_UNKNOWN: 1, "from_the_future": 1})
        check_in("the words come from the vocabulary, lowest rank first, the states after",
                 "Tests by proof level: the check is live: 2; catches a broken product: 1; not probed: 1; "
                 "not probed (unchanged test): 1; proof level unknown (the test file cannot be found): 1; "
                 "unknown proof level from_the_future: 1", S.render(mixed))
        check_eq("a summary with no test rows at all claims nothing", summary_of([])["proof_levels"], {})

        # D-0013: the unverified tests are the person's debt, with the critic's reason and the words.
        none = S.render(mixed)
        check_not_in("no unverified test, no debt block", "could not verify", none)
        # F3: the list comes from the manifest's own verdict, not from a ledger state - the ledger rows
        # below say `passed_green` for all of them (a fixed FLAKY and a green row alike keep the debt).
        mpath = C.artifact(art, "automation-manifest.json")
        manifest = C.load_json(mpath)
        manifest["tests"] += [
            {"case": "TC-7", "file": "tests/a.py", "marker": "test_a", "instance_id": "ti_0123abcd",
             "critic_verdict": " unverified ", "sensitivity_proof_missing_reason": "the stand was  down"},
            {"case": "TC-8", "file": "tests/b.py", "instance_id": "test_b[eu]", "critic_verdict": "unverified"},
            {"case": "TC-9", "file": "tests/c.py", "instance_id": "test_c", "critic_verdict": "unverified",
             "note": "SUPERSEDED DUPLICATE - delinked"},
            {"case": "TC-6", "file": "tests/d.py", "instance_id": "test_d", "critic_verdict": "approved"}]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        debt = summary_of([test("a", "live"), test("ti_0123abcd", "live")])
        check_eq("the unverified tests are listed with their reasons (a dead row and an approved one are not)",
                 debt["unverified_by_critic"],
                 [{"ref": "ti_0123abcd", "test": "tests/a.py::test_a", "why": "the stand was down"},
                  {"ref": "test_b[eu]", "test": "tests/b.py::test_b", "why": ""}])
        text = S.render(debt)
        # t-305 N8 (F9, Q-N8-6, FR-10): the fragment keeps the typed list (above) but prints no list of its own - what is left
        # with the person is the report's ONE section, quoted whole (`left_with_you`); with no report it says so in a line.
        check_not_in("the fragment builds no second list of the unverified tests (the report's section is the one)",
                     "the code critic could not verify it", text)
        check_in("with no report it says there is none yet, in one line",
                 "Left with you: the report has none yet", text)
        check_not_in("never by an instance hash (FR-6)", "ti_0123abcd", text)
        quoted = dict(debt, left_with_you="## Left with you\n\n- R-3, TC-7: green, but not verified by the code critic\n")
        check_in("and with a report it quotes that section whole", "- R-3, TC-7: green, but not verified by the code critic", S.render(quoted))
        check_not_in("the release verdict is the scribe's one statement (FR-10), not repeated here",
                     "Not ready for release", text)
        check_eq("delivery is not blocked by it: the summary reads delivery_ready from the ledger alone",
                 debt["delivery_ready"], bool(ledger.get("delivery_ready")) and debt["ledger_freshness"] != "stale")
    finally:
        cleanup(root)


# --- the owner of a reason, lifted to the case level (t-109 R-208.6, factory-fixes P2) -----------------
#
# The synthetic story below is written by hand, not reduced: what is under test is the reader of a
# reduced report (`check_delivery.case_ownership` and `reason_owner`), and the rows it reads are the
# shapes finalize_task.py writes (t-183): a ghost is `partial` + `current_reason: instance_manifest_join_failed`
# + `raw_status`, a genuine row has no `current_reason`.

MOD = "tests/test_lift.py::"
T1, T2, T3 = "2026-09-30T10:00:00Z", "2026-09-30T11:00:00Z", "2026-09-30T12:00:00Z"


def link(case: str) -> list:
    return [{"case_id": case, "version": "v1"}]


def ghost(name: str, case: str, raw="not_run") -> dict:
    row = {"instance_id": name, "test_id": MOD + name, "status": "partial", "current_reason": D.JOIN_FAILED,
           "case_version_links": link(case)}
    if raw is not None:  # an old report carries no `raw_status`
        row["raw_status"] = raw
    return row


def joined(name: str, case: str, status: str = "passed", **extra) -> dict:
    return dict({"instance_id": name, "test_id": MOD + name, "status": status, "case_version_links": link(case)},
                **extra)


def run_block(name: str, started: str, status: str, rows: list) -> dict:
    return {"block_id": name, "attempt_id": name, "attempt_started_at": started, "execution_status": status,
            "results": rows}


def plan_text(rows: dict) -> str:
    """`{TS: (R, disposition)}` as a v0 plan table."""
    head = ("---\ntask: QA-1\n---\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority "
            "| observable | oracle | disposition + reason | fit | level | technique |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    return head + "".join(f"| {ts} | a check | {req} | h | money | P0 | expected-contract | requirement:{req} "
                          f"| `{disp}` - reason | new | api | t |\n" for ts, (req, disp) in rows.items())


def case_text(cid: str, reqs: list, ts: str) -> str:
    return (f"---\nid: {cid}\ntitle: {cid}\narea: lift\npriority: P0\nstatus: Approved\nchannel: api\n"
            f"reuse_decision: new\nupdated: 2026-09-30\ntask: QA-1\ncovers: [{', '.join(reqs)}]\n"
            f"defect_class: contract\nbasis: requirement:{reqs[0]}\n---\n\nRequirements: {', '.join(reqs)}\n"
            f"Plan row: {ts}\n\n## Steps\n\n| # | Action | Expected |\n|---|---|---|\n| 1 | act | see |\n")


class LiftStory:
    """One throwaway story: `cases` {cid: ([R ids], TS)}, the plan's dispositions, the reduced report's rows."""

    def __init__(self, cases: dict, current: list, *, dispositions: dict = None, blocks: list = (),
                 results: list = None, manifest: dict = None, report: dict = None, plan: bool = True,
                 files: bool = True):
        self.root = temp_dir("qa-owner-lift-")
        self.art = self.root / "QA-1"
        work = self.art / "work"
        work.mkdir(parents=True)
        dispositions = dispositions or {}
        rows = {ts: (reqs[0], dispositions.get(ts, "automate")) for _cid, (reqs, ts) in cases.items()}
        if plan:
            (self.art / "test-plan.md").write_text(plan_text(rows), encoding="utf-8")
        for cid, (reqs, ts) in (cases.items() if files else ()):
            write_text(work / "test-cases" / "lift" / f"{cid}.md", case_text(cid, reqs, ts))
        write(work / "run-report.json", dict({"execution_status": "passed", "env_preflight": "pass",
                                               "current_results": current, "results": results or current,
                                               "manual_checks": [], "impossible": [], "env_blocked": [],
                                               "current_env_blocked": [], "totals": {}}, **(report or {})))
        write(work / "automation-manifest.json", manifest if manifest is not None else {"tests": [], "unresolved": []})
        for name, payload in blocks:
            write(work / "run-blocks" / (name + ".json"), payload)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        cleanup(self.root)

    def lift(self) -> dict:
        return D.case_ownership(self.art)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def trace(req: str, case: str) -> str:
    return f"traceability: {req} has no terminal outcome ({case}: run result 'partial' is not terminal)"


def ledger_row(ts: str, case: str) -> str:
    return f"ledger: {ts} is `not_executed:no result recorded for this row's cases` ({case})"


def case_level_owner() -> None:
    """R-208.6: the owner of a reason naming a plan row, a case or a requirement, read at the case level.

    Direction: factory where product is the one forbidden error. Every input below is a way a case can
    LOOK like the reducer's doubt while something else keeps it unproven."""
    cases = {
        "TC-101": (["R-101", "R-116"], "TS-101"),   # only a ghost: the factory's
        "TC-102": (["R-102", "R-116"], "TS-102"),   # ghost + a genuine partial row
        "TC-103": (["R-103"], "TS-103"),            # ghost + a genuine failed row
        "TC-104": (["R-104"], "TS-104"),            # ghost + a genuine not_run row
        "TC-105": (["R-105"], "TS-105"),            # ghost + a skipped row
        "TC-106": (["R-106"], "TS-106"),            # ghost, manual-human, no evidence package
        "TC-107": (["R-107"], "TS-107"),            # the control: the same with an evidence package
        "TC-108": (["R-108"], "TS-108"),            # a mixed case: a ghost beside a green row
        "TC-109": (["R-109"], "TS-109"),            # a ghost whose function went red before
        "TC-110": (["R-110"], "TS-110"),            # a ghost of an OLD report: no raw_status
        "TC-111": (["R-111"], "TS-111"),            # a ghost whose own raw status was red
        "TC-112": (["R-112"], "TS-112"),            # no row at all
        "TC-113": (["R-113"], "TS-113"),            # an ambiguous_attempt_order row (it keeps no raw_status)
        "TC-114": (["R-114"], "TS-114"),            # ghost only ... and TC-115, the same plan row, is product
        "TC-115": (["R-115"], "TS-114"),
        "TC-117": (["R-117"], "TS-117"),            # ghost only, but the manifest says `impossible`
        "TC-118": (["R-118"], "TS-118"),            # a clean ghost beside a green row whose function went red
    }
    current = [
        ghost("g101", "TC-101"),
        ghost("g102", "TC-102"), joined("p102", "TC-102", "partial"),
        ghost("g103", "TC-103"), joined("f103", "TC-103", "failed"),
        ghost("g104", "TC-104"), joined("n104", "TC-104", "not_run"),
        ghost("g105", "TC-105"), joined("s105", "TC-105", "skipped"),
        ghost("g106", "TC-106"),
        ghost("g107", "TC-107"),
        ghost("g108", "TC-108"), joined("p108", "TC-108"),
        ghost("g109", "TC-109"),
        ghost("g110", "TC-110", raw=None),
        ghost("g111", "TC-111", raw="failed"),
        dict(joined("a113", "TC-113", "partial"), current_reason="ambiguous_attempt_order"),
        ghost("g114", "TC-114"), joined("p115", "TC-115", "partial"),
        ghost("g117", "TC-117"),
        joined("p118", "TC-118"), ghost("g118", "TC-118"),
    ]
    blocks = [("b1", run_block("b1", T1, "failed", [{"instance_id": "g109", "test_id": MOD + "g109", "status": "failed"},
                                                    {"instance_id": "p118", "test_id": MOD + "p118", "status": "failed"}])),
              ("b2", run_block("b2", T2, "passed", [{"instance_id": "g108", "test_id": MOD + "g108", "status": "passed"}]))]
    dispositions = {"TS-106": "manual-human", "TS-107": "manual-human"}
    report = {"manual_human": [{"case": "TC-107", "evidence": "evidence/hand-over.md"}],
              "impossible": [{"case": "TC-117", "reason": "no such surface"}]}
    with LiftStory(cases, current, dispositions=dispositions, blocks=blocks, report=report) as story:
        lift = story.lift()
        ctx = {"case_lift": lift}
        owned = sorted(lift["factory_cases"])
        check_eq("the factory's cases are exactly the ones whose every non-green row is the reducer's own doubt",
                 owned, ["TC-101", "TC-107", "TC-108", "TC-113", "TC-114"])
        check_eq("and a story with nothing to say prints no note", lift["notes"], [])

        def owner(reason: str) -> str:
            return D.reason_owner(reason, D._reason_code(reason), ctx)

        # the inputs that may be lifted, and the four shapes a reason names them by
        check_eq("a case of only ghosts: its requirement is the factory's", owner(trace("R-101", "TC-101")), "factory")
        check_eq("a case of only ghosts: its plan row is the factory's", owner(ledger_row("TS-101", "TC-101")), "factory")
        check_eq("a case of only ghosts: named by its id alone",
                 owner("ledger: TC-101 is `not_executed:no result recorded` (nothing)"), "factory")
        check_eq("a mixed case (a ghost beside a green row) whose history holds no red: the factory's",
                 owner(trace("R-108", "TC-108")), "factory")
        check_eq("a manual-human case WITH its evidence package and a ghost: the factory's",
                 owner(trace("R-107", "TC-107")), "factory")
        check_eq("an ambiguous_attempt_order row (it keeps no raw_status) with a clean history: the factory's",
                 owner(trace("R-113", "TC-113")), "factory")
        # the adversarial table: each stays product
        stays = [
            ("ghost + a genuine partial row", trace("R-102", "TC-102")),
            ("ghost + a genuine failed row", trace("R-103", "TC-103")),
            ("ghost + a genuine not_run row", trace("R-104", "TC-104")),
            ("ghost + a genuine skipped row", trace("R-105", "TC-105")),
            ("ghost + a manual-human case with no evidence", trace("R-106", "TC-106")),
            ("the history of the case holds a red (edge iv), though its current rows all carry reducer reasons",
             trace("R-109", "TC-109")),
            ("a join-failed row with no raw_status (an old report, edge iii)", trace("R-110", "TC-110")),
            ("a join-failed row whose own raw status was red", trace("R-111", "TC-111")),
            ("a case with no current row at all (edge ii, see the report)", trace("R-112", "TC-112")),
            ("a case the manifest or the run calls impossible", trace("R-117", "TC-117")),
            ("a clean ghost beside a green row of the same case whose function went red before (the case's history)",
             trace("R-118", "TC-118")),
            ("two cases in one reason, one the factory's and one the product's (edge v)",
             "traceability: R-101 has no terminal outcome (TC-101: x; TC-102: y)"),
            ("a plan row mapped to two cases, one the product's (edge vi)", ledger_row("TS-114", "TC-114")),
            ("a requirement carried by two cases, one the product's", trace("R-116", "TC-101")),
            ("an id that maps to nothing (a plan row this story never had)", ledger_row("TS-999", "TC-101")),
            ("an id of a case this story never had", "ledger: TC-999 is `not_executed:no result` (nothing)"),
            ("no id at all (edge i)", "some new check: the widget refused to widget"),
            ("an obligation id is not a plan row or a requirement", "coverage red: OB-TS-101-1 - no instance proves it"),
            ("a failed:<verdict> ledger state is a verdict somebody passed", "ledger: TS-101 is `failed:APP_BUG` (TC-101)"),
        ]
        for label, reason in stays:
            check_eq(f"stays product: {label}", owner(reason), "product")
            check_eq(f"and that is exactly the owner it had before the lift: {label}",
                     owner(reason), D._owner_before_lift(reason, D._reason_code(reason), ctx))
        # the lift never touches an owner that is not `product`
        for reason, expected in (("ledger: TS-101 is `env_blocked:user` (TC-101)", "environment"),
                                 ("review: no critic verdict for TC-101", "review"),
                                 ("ledger: TS-101 is `review_rejected` (TC-101)", "review"),
                                 ("triage: the failure g101 (TC-101) has no verdict in triage.json", "factory")):
            check_eq(f"a {expected} owner is never changed by the lift: {reason[:34]!r}", owner(reason), expected)
        check_eq("with no lift in the context the same reason keeps the old answer",
                 D.reason_owner(trace("R-101", "TC-101")), "product")
        check_eq("and so does a context that carries only the old facts",
                 D.reason_owner(trace("R-101", "TC-101"), "", {"factory_refs": {"g999"}}), "product")

        # the person is told, not asked: the interim finding for each case lifted, for reasons that name it
        reasons = [trace("R-101", "TC-101"), ledger_row("TS-101", "TC-101"), trace("R-102", "TC-102"),
                   trace("R-113", "TC-113")]
        findings = D.owner_lift_findings(reasons, ctx)
        check_eq("one finding per lifted case that a reason names, none for a case left with the product",
                 [(f["code"], f["entity"], f["owner"]) for f in findings],
                 [("OWNER_LIFTED_TO_FACTORY", "TC-101", "factory"), ("OWNER_LIFTED_TO_FACTORY", "TC-113", "factory")])
        line = findings[0]["detail"] if findings else "<no finding>"  # a missing one fails, it does not crash the run
        check_in("it says how many reasons it moved and how to settle the case", "2 delivery reason(s)", line)
        check_in("and names the way out (FR-40)", "run_suite.py --mine TC-101", line)
        check_in("and says nothing is asked of the person", "not put to you as a product question", line)
        check_eq("a reason that stays product adds no finding", D.owner_lift_findings([trace("R-102", "TC-102")], ctx), [])

    # edge (ii), read as the critic's override reads it: a ghost-only case is the factory's ...
    with LiftStory({"TC-201": (["R-201"], "TS-201")}, [ghost("g201", "TC-201")]) as story:
        lift = story.lift()
        check_eq("a case of only ghosts (no joined result at all) is the factory's", sorted(lift["factory_cases"]), ["TC-201"])
        doc = D.assess(story.art)
        named = [r for r in doc["reason_records"] if "TC-201" in r["detail"] or "TS-201" in r["detail"]]
        check("...and the requirement is still counted not proven: its reasons stand and delivery is not ready",
              bool(named) and doc["delivery_ready"] is False, str(doc["reasons"][:4]))
        check("...every reason that names it is owned by the factory, none is put to the person as a product gap",
              all(r["owner"] == "factory" for r in named), str([(r["owner"], r["detail"][:60]) for r in named]))
        check("...and the finding that tells the person is on the findings road of the ledger",
              any(f["code"] == "OWNER_LIFTED_TO_FACTORY" and f["entity"] == "TC-201" for f in doc["factory_findings"]),
              str(doc["factory_findings"]))
        check_eq("...and it is the same list the ledger file carries",
                 [f["code"] for f in C.load_json(C.artifact(story.art, "ledger.json"))["factory_findings"]
                  if f["code"].startswith("OWNER_LIFT")], ["OWNER_LIFTED_TO_FACTORY"])
        said = run_script("check_delivery.py", story.art)
        check_in("...and the command prints it, where the person reads the verdict",
                 "Why some reasons are listed as the factory's:", said.stdout)
        check_in("...in words, naming the case", "TC-201 is not proven, and the reason is ours", said.stdout)
    # ... and a case with no current row at all is not: nothing says the reducer is why it has none
    with LiftStory({"TC-202": (["R-202"], "TS-202"), "TC-203": (["R-203"], "TS-203")}, [ghost("g203", "TC-203")]) as story:
        check_eq("a case with no row at all is left with the product (today's answer)",
                 sorted(story.lift()["factory_cases"]), ["TC-203"])

    # edge (ix): no plan and no case files - the mapping source is missing
    with LiftStory({"TC-301": (["R-301"], "TS-301")}, [ghost("g301", "TC-301")], plan=False, files=False) as story:
        lift = story.lift()
        check_eq("edge (ix): no plan and no case files: nothing is lifted", lift["factory_cases"], {})
        check_eq("edge (ix): and exactly one note says so", len(lift["notes"]), 1)
        check_in("edge (ix): in words a person can read", "no test plan and no case files", lift["notes"][:1])
        check_eq("edge (ix): the owner is what it was", D.reason_owner(trace("R-301", "TC-301"), "", {"case_lift": lift}),
                 "product")
        doc = D.assess(story.art)
        notes = [f for f in doc["factory_findings"] if f["code"] == "OWNER_LIFT_NOTE"]
        check_eq("edge (ix): the note is filed as a finding, once", len(notes), 1)
    # a story with no reducer row at all owes no note and pays for nothing
    with LiftStory({"TC-302": (["R-302"], "TS-302")}, [joined("p302", "TC-302")], plan=False, files=False) as story:
        check_eq("no reducer row: no lift and no note", (story.lift()["factory_cases"], story.lift()["notes"]), ({}, []))

    # edge (x): the history cannot be read -> never lifted (the safe direction), and it is said
    clean = ({"TC-401": (["R-401"], "TS-401")}, [ghost("g401", "TC-401")])
    with LiftStory(*clean) as story:
        real = D.RH.red_blocks

        def boom(*_args, **_kw):
            raise OSError("disk gone")
        D.RH.red_blocks = boom
        try:
            lift = story.lift()
        finally:
            D.RH.red_blocks = real
        check_eq("edge (x): red_blocks raises: nothing is lifted", lift["factory_cases"], {})
        check_eq("edge (x): and one note says the history was unreadable", len(lift["notes"]), 1)
        check_in("edge (x): naming what failed", "OSError", lift["notes"][:1])
        check_eq("edge (x): the owner is what it was", D.reason_owner(trace("R-401", "TC-401"), "", {"case_lift": lift}),
                 "product")
        check_eq("edge (x): the control - the same story with a readable history is lifted",
                 sorted(story.lift()["factory_cases"]), ["TC-401"])
        check_eq("edge (x): the note reaches the person as a finding",
                 [f["code"] for f in D.owner_lift_findings([], {"case_lift": lift})], ["OWNER_LIFT_NOTE"])
    with LiftStory(*clean, blocks=[("broken", run_block("broken", T1, "passed", []))]) as story:
        (story.art / "work" / "run-blocks" / "corrupt.json").write_text("{not json", encoding="utf-8")
        lift = story.lift()
        check_eq("edge (x): a run block that is not readable may hold the red: nothing is lifted", lift["factory_cases"], {})
        check_in("edge (x): and the note names it", "corrupt.json", lift["notes"][:1])

    # the row with no function to look up in the history is not lifted, without a note
    row = {"status": "partial", "current_reason": D.JOIN_FAILED, "raw_status": "not_run", "instance_id": "",
           "case": "TC-501"}
    with LiftStory({"TC-501": (["R-501"], "TS-501")}, [row]) as story:
        check_eq("a row that names no test function cannot be looked up: left with the product",
                 story.lift()["factory_cases"], {})


def headings_agree() -> None:
    """Three files print these headings; a person reads them side by side."""
    check_eq("ledger and delivery_summary order the owners the same way",
             list(L.OWNER_ORDER), list(S.OWNERS))
    check_eq("and use the same headings", L.OWNER_HEADINGS, S.OWNER_HEADINGS)
    check_eq("every owner in the closed list has a heading",
             sorted(L.OWNER_HEADINGS), sorted(C.DELIVERY_REASON_OWNERS))


def coverage_owner() -> None:
    """RD1-21: the family `coverage` is split by typed fields. Missing evidence on a green run with a closed oracle is the
    factory's (`coverage:`, stays unproven); a red run or an open oracle stays the product's (`coverage red:`). The verdict
    never changes, and no sentence says "nothing here says the product is not ready" over an unproven behaviour."""
    def ob(oid, **fields):
        base = {"obligation_id": oid, "execution_scope": "current_task", "verified": False, "person_debt": False,
                "gap": "evidence incomplete", "execution_state": "passed", "oracle_open": False}
        return dict(base, **fields)
    said = D.coverage_reasons({"coverage": {"obligations": [
        ob("OB-1"),                                             # green run, closed oracle: the factory's
        ob("OB-2", execution_state="failed"),                   # red run
        ob("OB-3", oracle_open=True),                           # open oracle
        ob("OB-4", execution_state="not_run"),                  # not run, closed oracle: still the factory's
        ob("OB-5", execution_state="inconclusive"),
        {k: v for k, v in ob("OB-6").items() if k not in ("execution_state", "oracle_open")},   # absent fields read RED
        ob("OB-7", execution_state="failed", decision="manual-agent"),
        ob("OB-8", verified=True), ob("OB-9", person_debt=True), ob("OB-10", execution_scope="earlier"),
    ]}})
    check_eq("coverage_reasons splits by execution_state and oracle_open; verified, person_debt and old scope are no reason",
             [r.split(" — ")[0] for r in said],
             ["coverage: OB-1", "coverage red: OB-2", "coverage red: OB-3", "coverage: OB-4", "coverage: OB-5",
              "coverage red: OB-6", "coverage red: OB-7"])
    one, two = D.reason_record("coverage: OB-1 — x"), D.reason_record("coverage red: OB-2 — x")
    check_eq("`coverage:` is the factory's under the one typed code", (one["owner"], one["code"]),
             ("factory", L.COVERAGE_GAP_CODE))
    check_eq("`coverage red:` is the product's under the same code", (two["owner"], two["code"]),
             ("product", L.COVERAGE_GAP_CODE))
    check_eq("both kinds are owners the table established", (one["owner_established"], two["owner_established"]),
             (True, True))
    check_eq("the kind `coverage_gap` carries the factory and the verdict `no`",
             D.DV.load_kinds()[0]["kinds"]["coverage_gap"], {"verdict": "no", "owner": "factory"})
    check_eq("one coverage_gap record is still `no`, never `yes`", D.DV.decide(["coverage_gap"])[0], "no")
    # F-3: a reason no rule placed is `product` by default and the record says it was not established
    unplaced = D.reason_record("some new check: the widget refused to widget")
    check_eq("an unplaced reason stays `product` and is not established", (unplaced["owner"], unplaced["owner_established"]),
             ("product", False))
    check_eq("a placed `product` family is established", D.reason_record("traceability: R-4 has no terminal outcome (x)")
             ["owner_established"], True)

    # the one predicate behind every "nothing here says" sentence
    records = [{"owner": "factory", "code": L.COVERAGE_GAP_CODE, "detail": "coverage: OB-1 — x"}, "not a dict",
               {"owner": "product", "code": L.COVERAGE_GAP_CODE, "detail": "coverage red: OB-2 — x"},
               {"owner": "factory", "code": "FACTORY_DEFECT", "detail": "factory: y"}]
    check_eq("factory_coverage_gaps counts the factory's coverage records only", L.factory_coverage_gaps({"reason_records": records}), 1)
    check_eq("and none in a ledger with no records", L.factory_coverage_gaps({}), 0)
    only = {"reason_records": [records[0], records[3]]}
    said_all = "\n".join(L.render_reasons(only))
    check_in("the ledger says the behaviour stays unproven", L.factory_coverage_line(1), said_all)
    check_not_in("and does not reassure over it", "Nothing here says the product is not ready", said_all)
    check_in("the control: a bookkeeping-only list still reassures",
             "Nothing here says the product is not ready", "\n".join(L.render_reasons({"reason_records": [records[3]]})))
    summary = {"counts": {}, "gaps": [], "bugs": [], "blocked_by": ["factory"], "factory_coverage_gaps": 1,
               "reasons_by_owner": {"factory": ["coverage: OB-1 — x"]}}
    rendered = S.render(summary)
    check_in("the summary says it too", L.factory_coverage_line(1), rendered)
    check_not_in("and does not reassure", "Nothing here says the product is not ready", rendered)
    check_in("the control: with no coverage gap the summary reassures", "Nothing here says the product is not ready",
             S.render(dict(summary, factory_coverage_gaps=0)))

    root = temp_dir("qa-factory-cov-owner-")
    try:
        art = root / "QA-1"
        shutil.copytree(GOOD, art)
        doc = D.assess(art)
        doc["reason_records"] = [dict(D.reason_record("coverage: OB-1 — x"), kind="coverage_gap"),
                                 dict(D.reason_record("some new check: z"), kind="factory_record")]
        built = S.build(art, doc)
        check_eq("build carries the count", built["factory_coverage_gaps"], 1)
        check_in("and an owner nobody established says so", "owner not established: some new check: z",
                 built["reasons_by_owner"]["product"])
    finally:
        cleanup(root)


def scribe_witness_reads_the_word() -> None:
    """RD1-4 K13 (B-304 G6): the scribe's charter no longer says the exit codes must be green (`check_delivery.py` exits 1 on
    `after_checks` too) and its Witness list carries the word `check_delivery.py` printed, not its exit code."""
    text = (SCRIPTS.parent / "agents" / "qa-doc-scribe.md").read_text(encoding="utf-8")
    # the sentence "you quote the word `check_delivery.py` printed, never its exit code" is a row of design/role-rules.json
    check_eq("K13: the charter is not larger than before (9122 bytes)", len(text.encode("utf-8")) <= 9122, True)


def main() -> None:
    scribe_witness_reads_the_word()
    coverage_owner()
    headings_agree()
    manifest_supersession()
    reducer_supersession()
    reason_owners()
    reason_families_are_declared_in_data()
    factory_defects_are_not_the_product()
    proof_levels_in_the_summary()
    case_level_owner()
    finish("test_delivery_ownership")


if __name__ == "__main__":
    main()
