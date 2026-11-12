"""The gate rehearsal: everything that would stop the story after an approval, found before it.

The owner's rule of 21.09.2026 in one sentence: the factory must not show a person gate A if,
once they have approved, it cannot go on because it lacks something. TP1-15045 is the
story that earned the rule — after "approve, keep all automate, accept gaps" the factory
stopped four more times, every time over a fact it already had on disk.

These tests assert the shape of that rehearsal, not the wording of the checks it delegates to:
a finding has an owner (`factory_fixable` / `person_decides` / `factory_defect`), the rehearsal
writes nothing, an uninstalled check is a finding and never a silent pass, and the stage in
front of the gate refuses to close while a repair the factory owes itself is open.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import gate_preflight  # noqa: E402
import stage_done  # noqa: E402

# t-238 W2, the tripwire: from here on EVERY `Rehearsal.add()` of this whole file that offers a
# person's word is recorded with the message it carried, keyed by the line of the call.
# `test_w2_every_card_that_offers_a_word_contains_its_block` reads the record at the end.
# t-357: the word is a line the person WRITES (`<check id>: accept`), not a command with `--block "<text>"`; the block it
# passes travels in the finding's `waives` (machine data, never printed), and that is what the tripwire reads.
WAIVER_SEEN: dict = {}
# t-357, the class sweep's record: every finding and every INFO line any run of this file produced, so one test at the
# end can hold ALL of them to the owner's rule (no script name, no flag, no exit code) - not the handful a test names.
TEXTS_SEEN: list = []


def _install_the_tripwire() -> None:
    original = gate_preflight.Rehearsal.add
    original_note = gate_preflight.Rehearsal.note

    def add(self, check, klass, message, fix="", **extra):
        line = sys._getframe(1).f_lineno
        before = len(self.findings)
        done = original(self, check, klass, message, fix, **extra)
        if len(self.findings) > before:
            found = self.findings[-1]
            TEXTS_SEEN.append((f"{check}:{line}", "message", found["message"]))
            TEXTS_SEEN.append((f"{check}:{line}", "fix", found["fix"]))
            for door in found.get("waives") or []:
                WAIVER_SEEN.setdefault(line, []).append(
                    (" ".join(str(found["message"]).split()), door["block"], door["stage"]))
        return done
    gate_preflight.Rehearsal.add = add

    def note(self, check, message, **extra):
        TEXTS_SEEN.append((f"{check}:note", "info", " ".join(str(message).split())))
        return original_note(self, check, message, **extra)
    gate_preflight.Rehearsal.note = note


_install_the_tripwire()

def plan_row(row_id: str, **extra) -> dict:
    """A plan row that satisfies the planning contract, so a finding in these tests is the one
    the test asked for and never a field the fixture forgot."""
    return dict({"id": row_id, "requirement_ids": ["R-1"], "level": "api",
                 "disposition": "automate", "impact": "moderate", "likelihood": "medium",
                 "design_review_required": False,
                 "confidence": "medium", "risk_rationale": "a permission seam",
                 "risk_source_refs": ["strategy/test-strategy.md@2026-09-14"],
                 "risk_policy_revision": "factory-starter-v1", "coverage_refs": [],
                 "unknowns": [], "verification_depth": "normal",
                 "defect_hypothesis": "seam @ validate vs update",
                 "required_scenarios": ["a denied caller"],
                 "test_level_rationale": "HTTP contract, no UI involved"}, **extra)


PLAN = [
    plan_row("TS-1", level="e2e-ui"),
    plan_row("TS-2", coverage_obligations=[{
        "obligation_id": "OB-TS-2-1",
        "parts": [{"part_id": "denial", "status": "unresolved"}],
        "remaining_gap": "no non-owner account on localhost",
        "observation_contract": {"surfaces": [{"id": "S-denial", "status": "gap"}]}}]),
]

FINDINGS = (
    "# Critic findings\n\nVerdict: approve_with_fixes.\n\n"
    "## Fixes without a new round\n\n"
    "```json\n"
    '[{"case_id": "TC-001", "locator": "Then 3", "find": "denied with a 4xx",'
    ' "replace": "denied with exactly 401 or 403", "reviewed_version": "cv_one"}]\n'
    "```\n\n## Gate A debts\n\n- TC-001, fix 1. owner: qa-case-designer.\n"
)


def story(prefix: str, *, with_fixes: bool = True) -> Path:
    """A project with one story parked where TP1-15045 was: S4 written, gate A not asked.

    Everything the rehearsal reads is present and consistent, so a finding in these tests is
    the one the test put there. `with_fixes=False` is the same story with the critic's
    replacements already applied — the baseline that has to close S4 without a word."""
    import hashlib
    root = temp_dir(prefix)
    task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
    (task_root / "work" / "test-cases" / "workflows").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "tests_root": "tests", "app_root": "."}), encoding="utf-8")
    (root / "qa-factory" / "readiness.json").write_text(json.dumps(
        {"capabilities": {"environment": {"status": "ok"}, "test_repo": {"status": "ok"}}}),
        encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
    for name in ("source-inventory.json", "context-manifest.json", "context-bundle.json"):
        (task_root / "work" / name).write_text("{}", encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps(
        {"ticket": "TP1-15045",
         "stages": {"S3": {"status": "done"}, "S4": {"status": "done", "role": "qa-case-critic"}}}),
        encoding="utf-8")
    case = task_root / "work" / "test-cases" / "workflows" / "TC-001.md"
    case.write_text("---\nid: TC-001\nplan_row: TS-1\n---\n\n## Then\n3. "
                    + ("denied with a 4xx" if with_fixes else "denied with exactly 401 or 403")
                    + ".\n", encoding="utf-8")
    (task_root / "state" / "story-case-links.json").write_text(json.dumps(
        {"task_id": "TP1-15045",
         "links": [{"case_id": "TC-001", "version": "cv_one" if with_fixes else "cv_two",
                    "content_hash": hashlib.sha256(case.read_bytes()).hexdigest(),
                    "path": "work/test-cases/workflows/TC-001.md"}]}), encoding="utf-8")
    (task_root / "work" / "test-cases" / "workflows" / "critic-findings.md").write_text(
        FINDINGS, encoding="utf-8")
    return root


def by_check(result: dict, name: str) -> list:
    return [f for f in result["findings"] if f["check"] == name]


def test_the_shape_of_a_rehearsal() -> None:
    root = story("qa-gate-preflight-")
    try:
        use_project(root)
        result = gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        check_eq("the rehearsal is about the stage the approval unlocks",
                 result["next_stage"], "S5")
        check("every finding carries an owner",
              all(f["class"] in gate_preflight.CLASSES for f in result["findings"]))
        check("every finding carries an id, a check and a message",
              all(f.get("id") and f.get("check") and f.get("message") for f in result["findings"]))
        check_eq("a story with findings cannot proceed on an approval alone",
                 result["can_proceed"], not result["findings"])
        check_eq("gate B rehearses the stage behind it",
                 gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045",
                                    "B")["next_stage"], "S9")
    finally:
        cleanup(root)


def test_the_critics_unapplied_fix_is_the_factorys_to_repair() -> None:
    """The fourth of the four stops after "approve": four exact replacements, none applied."""
    root = story("qa-gate-preflight-fixes-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        found = by_check(gate_preflight.run(task_root, "A"), "critic_rollcall")
        unapplied = [f for f in found if "not applied" in f["message"]]
        check_eq("the unapplied replacement is named", len(unapplied), 1)
        check_eq("and it is the factory's own to repair, not a question for the person",
                 unapplied[0]["class"], gate_preflight.FACTORY_FIXABLE)
        check_in("the repair is the factory's own code, not a role dispatch - said in words, no script (t-357)",
                 "the factory applies it by code and re-pins the case; no designer dispatch is needed", unapplied[0]["fix"])
        check_not_in("t-357: and no script or flag is named", "critic_rollcall.py", unapplied[0]["fix"])
        check_not_in("t-357: not the flag either", "--apply-fixes", unapplied[0]["fix"])
        check_in("the finding says where in the case it belongs", "Then 3", unapplied[0]["message"])
    finally:
        cleanup(root)


def test_a_fix_no_code_can_apply_is_carried_to_the_gate_not_repaired_forever() -> None:
    """B-F8: `approve_with_fixes` whose `find` matches nothing deadlocked S4.

    `--apply-fixes` skips a 0/2+-match replacement by design, s4.md carries it under
    `## Gate A debts` with an owner, and `critic_rollcall` accepts that — while the rehearsal
    kept calling it `factory_fixable`, which `stage_done` refuses to close S4 over. There was
    no repair to run: the loop ended only in a waiver s4.md forbids asking for."""
    root = story("qa-gate-preflight-debt-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        findings = task_root / "work" / "test-cases" / "workflows" / "critic-findings.md"
        # The same debt, with a `find` that is in no case file — nothing can land it.
        findings.write_text(FINDINGS.replace("denied with a 4xx", "a sentence nobody wrote"),
                            encoding="utf-8")
        unapplied = [f for f in by_check(gate_preflight.run(task_root, "A"), "critic_rollcall")
                     if "not applied" in f["message"]]
        check_eq("the unapplied replacement is still named", len(unapplied), 1)
        check_eq("but a debt the critic carried with an owner is the person's to weigh",
                 unapplied[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("the finding repeats the owner it was carried with",
                 "qa-case-designer", unapplied[0]["message"])
        check_not_in("and stops offering a repair that cannot run",
                     "--apply-fixes", unapplied[0]["fix"])
        check_eq("so S4 closes instead of looping on a repair that does not exist",
                 stage_done.gate_rehearsal_errors(task_root, "A"), [])
    finally:
        cleanup(root)


def _case_versions_findings(root: Path) -> list:
    use_project(root)
    task = root / "qa-factory" / "artifacts" / "TP1-15045"
    return by_check(gate_preflight.run(task, "A"), "case_versions")


def _second_case(task: Path, pinned: bool) -> None:
    import hashlib
    folder = task / "work" / "test-cases" / "workflows"
    case = folder / "TC-002.md"
    case.write_text("---\nid: TC-002\nplan_row: TS-2\n---\n\n## Then\n1. ok.\n", encoding="utf-8")
    if pinned:
        links = task / "state" / "story-case-links.json"
        doc = json.loads(links.read_text(encoding="utf-8"))
        doc["links"].append({"case_id": "TC-002", "version": "cv_x", "content_hash": hashlib.sha256(
            case.read_bytes()).hexdigest(), "path": "work/test-cases/workflows/TC-002.md"})
        links.write_text(json.dumps(doc), encoding="utf-8")


def _drop_cases(task: Path) -> None:
    for path in (task / "work" / "test-cases").rglob("TC-*.md"):
        path.unlink()
    (task / "state" / "story-case-links.json").unlink()


def test_sc5_15_no_case_on_disk_under_a_planned_history_is_a_finding_not_a_pass() -> None:
    """K1-K5. The silence of an EMPTY plan is the invariant: a zero-cases finding never appears for it."""
    door = "the plan has 2 rows but no case file is on disk; the factory writes the cases before the gate"
    root = story("qa-gate-preflight-sc5-15-")
    try:
        task = root / "qa-factory" / "artifacts" / "TP1-15045"
        _second_case(task, pinned=True)
        check_eq("K2: two pinned cases raise nothing", _case_versions_findings(root), [])
        _second_case(task, pinned=False)
        (task / "state" / "story-case-links.json").write_text(json.dumps(
            {"task_id": "TP1-15045", "links": json.loads((task / "state" / "story-case-links.json").read_text(
                encoding="utf-8"))["links"][:1]}), encoding="utf-8")
        found = _case_versions_findings(root)
        check_eq("K3: one pinned and one unpinned give exactly one finding", len(found), 1)
        check_in("K3: it is the unpinned one", "TC-002", found[0]["message"])
        _drop_cases(task)
        found = _case_versions_findings(root)
        check_eq("K1: a 2-row plan with no case file gives one finding", len(found), 1)
        check_in("K1: with the door text", door, found[0]["message"])
        check_eq("K1: of the factory-fixable class", found[0]["class"], gate_preflight.FACTORY_FIXABLE)
        plan = task / "work" / "test-plan.json"
        plan.write_text("[]", encoding="utf-8")
        check_eq("K4: an empty plan with no case raises nothing", _case_versions_findings(root), [])
        plan.write_text(json.dumps([plan_row("TS-1", disposition="skip"), plan_row("TS-2", disposition="skip")]),
                        encoding="utf-8")
        check_eq("K5: a skip-only plan with no case raises nothing", _case_versions_findings(root), [])
        row = plan_row("TS-1")
        del row["disposition"]
        plan.write_text(json.dumps([row]), encoding="utf-8")
        check_eq("a row with no disposition counts as planned", len(_case_versions_findings(root)), 1)
        plan.unlink()
        check_eq("an absent plan file is an empty plan", _case_versions_findings(root), [])
        plan.write_text("{not json", encoding="utf-8")
        found = _case_versions_findings(root)
        check("an unreadable plan is `unavailable`, never a count",
              len(found) == 1 and "unavailable" in found[0]["message"] and "no case file" not in found[0]["message"],
              str(found))
    finally:
        cleanup(root)


def test_a_gap_the_plan_itself_declares_becomes_a_question() -> None:
    """The fifth row of the plan's table: "no non-owner account on localhost" reached the gate
    as a sentence nobody had checked. It is read from the obligation's structured fields —
    `parts[].status` and an observation surface `status: gap` — never parsed out of prose."""
    root = story("qa-gate-preflight-env-")
    try:
        use_project(root)
        found = by_check(gate_preflight.run(
            root / "qa-factory" / "artifacts" / "TP1-15045", "A"), "case_environment")
        check_eq("the declared gap is raised exactly once", len(found), 1)
        check_eq("a gap only a person can accept is theirs to decide",
                 found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("and it names the gap in the plan's own words",
                 "no non-owner account", found[0]["message"])
        check_in("with the row it belongs to", "TS-2", found[0]["message"])
    finally:
        cleanup(root)


def test_d1b_k_b6_a_finding_made_for_a_subject_keeps_its_id_between_rehearsals() -> None:
    """R7 (D1-B B6): `case_environment-TS-10` and `vcs-test-repo` are ids of a SUBJECT, so a word written for one keeps meeting it when
    another row leaves the list; a finding with no subject is still `<check>-<n>`. Killed by: `add` keeping the ordinal."""
    root = story("qa-gate-preflight-ids-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        gap = lambda rid: plan_row(rid, coverage_obligations=[{"obligation_id": f"OB-{rid}", "parts": [{"part_id": "p", "status": "unresolved"}],  # noqa: E731
                                                                 "remaining_gap": "no account"}])
        plan = task_root / "work" / "test-plan.json"
        plan.write_text(json.dumps([gap("TS-3"), gap("TS-10")]), encoding="utf-8")
        first = [f["id"] for f in by_check(gate_preflight.run(task_root, "A"), "case_environment")]
        plan.write_text(json.dumps([plan_row("TS-3", disposition="skip"), gap("TS-10")]), encoding="utf-8")
        second = [f["id"] for f in by_check(gate_preflight.run(task_root, "A"), "case_environment")]
        check_eq("K-B6 two rehearsals: TS-10 is `case_environment-TS-10` before and after TS-3 left", (first, second),
                 (["case_environment-TS-3", "case_environment-TS-10"], ["case_environment-TS-10"]))
        found = by_check(gate_preflight.run(task_root, "A"), "case_environment")[0]
        check_in("K-B6 the fix offers the third answer, `<its id>: product gap` (C1; D1-C2 fills the id in, never prints `<id>`)",
                 "`case_environment-TS-10: product gap`", found["fix"])
        check_in("K-B6 ... beside accepting the gap and holding the row", "accept the gap", found["fix"])
        # two gapped obligations of one row: each is its own item, told apart by the obligation id
        two = plan_row("TS-5", coverage_obligations=[gap("A")["coverage_obligations"][0], gap("B")["coverage_obligations"][0]])
        plan.write_text(json.dumps([two]), encoding="utf-8")
        check_eq("K-B6 one row, two gapped obligations: the id names both",
                 [f["id"] for f in by_check(gate_preflight.run(task_root, "A"), "case_environment")],
                 ["case_environment-TS-5-OB-A", "case_environment-TS-5-OB-B"])
        # the ids of a subject: folding, collision, empty subject, no subject
        r = gate_preflight.Rehearsal(task_root, "A")
        r.add("x", gate_preflight.PERSON_DECIDES, "m1", subject="TS 3/a")
        r.add("x", gate_preflight.PERSON_DECIDES, "m2", subject="TS-3-a")      # folds to the SAME token as the first: `-2`
        r.add("x", gate_preflight.PERSON_DECIDES, "m3", subject="TS 3/a")      # a third one: `-3`
        r.add("x", gate_preflight.PERSON_DECIDES, "m4")                        # no subject: the ordinal (4 findings of `x` stand before it -> 4)
        r.add("x", gate_preflight.PERSON_DECIDES, "m5", subject="   ")         # a blank subject is no subject
        check_eq("K-B6 AT the fold: `TS 3/a` -> x-TS-3-a; the same token again -> -2, -3 (E-B5); no subject -> the ordinal (E-B6)",
                 [f["id"] for f in r.findings], ["x-TS-3-a", "x-TS-3-a-2", "x-TS-3-a-3", "x-4", "x-5"])
        # (re-pinned, F5 t-1758: `.` folds too and no `-` stays at an edge, so every id is one the reader accepts; "é" has no token at all)
        check_eq("K-B6 the id token keeps [A-Za-z0-9_-], folds every other run (a `.` too) to one `-`, strips the edges",
                 (gate_preflight._id_token("a b//c.d_e-f"), gate_preflight._id_token("é"), gate_preflight._id_token("TS 3!")), ("a-b-c-d_e-f", "", "TS-3"))
        # F5 (t-1752): the id the writer makes is the id the reader reads (ONE definition, gate_preflight.FINDING_ID_PATTERN)
        import story_run
        reader = story_run.Driver._FINDING_LINE_RE
        w = gate_preflight.Rehearsal(task_root, "A")
        subjects = ("TS-3.1", "TS 3!", "vcs test repo", "TS-4-OB.2", "é", "TS-10")
        for subject in subjects:
            w.add("case_environment", gate_preflight.PERSON_DECIDES, f"m {subject}", subject=subject)
        ids = [f["id"] for f in w.findings]
        check_eq("F5 every id `add(subject=)` makes is read back whole by `Driver._FINDING_LINE_RE`",
                 [(m.group("id") if (m := reader.match(f"{i}: accept because")) else None) for i in ids], ids)
        check_eq("F5 the ids themselves", ids, ["case_environment-TS-3-1", "case_environment-TS-3", "case_environment-vcs-test-repo",
                                                "case_environment-TS-4-OB-2", "case_environment-5", "case_environment-TS-10"])
        check_eq("F5 a plain `word: text` line is no finding line", [reader.match(t) for t in ("note: x", "ok: fine", "Note: x - y", "note-: x")], [None] * 4)
        # the vcs finding is `vcs-test-repo`, in both of its branches
        (root / "tests").mkdir(exist_ok=True)
        original = gate_preflight._git
        try:
            for status in ("", " M a.py"):
                answers = {("rev-parse", "--abbrev-ref", "HEAD"): "main", ("status", "--porcelain"): status,
                           ("rev-parse", "HEAD"): "0123456789abcdef"}
                gate_preflight._git = lambda root, *args, **kw: answers.get(args)
                v = gate_preflight.Rehearsal(task_root, "A")
                v.check_vcs()
                check_eq(f"K-B6 vcs ({'dirty' if status else 'clean'}) -> the id is `vcs-test-repo`", [f["id"] for f in v.findings], ["vcs-test-repo"])
        finally:
            gate_preflight._git = original
    finally:
        cleanup(root)


def _norms_register(task_root, rows) -> None:
    head = "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |\n|---|---|---|---|---|---|---|---|---|\n"
    body = "".join(f"| {r} | requirement {r} | {'derived' if r in norms else 'story'} | {norms.get(r, '—')} | yes | — | none | degraded | new |\n"
                   for r, norms in rows)
    (task_root / "work" / "requirements-register.md").write_text("## Register\n\n" + head + body, encoding="utf-8")


def test_d1b_k_b7_the_norms_question_rule_runs_at_gate_a_and_the_marker_is_read() -> None:
    """D1-B B7/B8: gate A reads the register's norm rows once and gives them to `question_errors`; a question marked `norms_list` that
    names a non-norm row is refused; an unreadable register is a note. Killed by: the marker ignored / the norm ids not passed."""
    root = story("qa-gate-preflight-norms-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        norm = {"R-1": "norm:price", "R-2": "aspect:stock"}
        _norms_register(task_root, [("R-1", norm), ("R-2", norm), ("R-3", {})])

        def question(qid, text, origin="description", **extra):
            return dict({"id": qid, "question": f"Do these hold: {text}?", "severity": "major", "owner_role": "po_ba",
                         "source_says": [{"quote": "q", "where": "register"}],
                         "readings": [{"reading": "yes", "from": "description", "if_chosen": "kept"},
                                      {"reading": "no", "from": origin, "if_chosen": "dropped"}]}, **extra)

        def rehearse(*questions, register=True):
            (task_root / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": list(questions)}), encoding="utf-8")
            if not register:
                (task_root / "work" / "requirements-register.md").unlink(missing_ok=True)
            r = gate_preflight.Rehearsal(task_root, "A")
            r.check_open_questions()
            return r

        got = [f for f in rehearse(question("Q9", "R-1, R-2", origin="code")).findings if f["check"] == "open_questions"]
        check("K-B7 `from: code` on the norms question -> a finding naming Q9", len(got) == 1 and "Q9" in got[0]["message"] and "no source of a norm" in got[0]["message"], str(got))
        check_eq("K-B7 ... without `from: code` -> none", rehearse(question("Q9", "R-1, R-2")).findings, [])
        got = rehearse(question("Q9", "R-1, R-3", norms_list=True)).findings
        check("K-B7 a question marked `norms_list` that names a non-norm row (R-3) -> a finding", len(got) == 1 and "marked `norms_list`" in got[0]["message"] and "R-3" in got[0]["message"], str(got))
        got = rehearse(question("Q9", "R-1", origin="code", norms_list=True)).findings
        check("K-B7 the MARK makes a question the norms question even with ONE row named: `from: code` refused", len(got) == 1 and "no source of a norm" in got[0]["message"], str(got))
        check_eq("K-B7 an UNmarked question naming one norm row and one non-norm is a fork question: `from: code` stays legal",
                 rehearse(question("Q8", "R-1, R-3", origin="code")).findings, [])
        r = rehearse(question("Q9", "R-1, R-2", origin="code"), register=False)
        check_eq("K-B7 register unreadable -> no finding", [f for f in r.findings if f["check"] == "open_questions"], [])
        check("K-B7 ... and a note says the rule was not checked", any("norms-question rule was not checked" in i["message"] for i in r.info), str(r.info))
    finally:
        cleanup(root)


def test_a_word_already_given_is_not_asked_for_twice() -> None:
    """A person's word passes any block in this factory — and, having passed it, is not
    re-asked at the next gate. TP1-15045 asked about the dirty tree after the approval it
    should have been part of."""
    root = story("qa-gate-preflight-word-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        before = len(by_check(gate_preflight.run(task_root, "A"), "case_environment"))
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "no non-owner account",
                                        "decision": "accept the gap, report it not executed",
                                        "by": "human"}]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        after = len(by_check(gate_preflight.run(task_root, "A"), "case_environment"))
        check_eq("the question was asked once", before, 1)
        check_eq("and never again after it was answered", after, 0)
    finally:
        cleanup(root)


def test_a_check_that_is_not_installed_is_a_finding_not_a_pass() -> None:
    """A rehearsal that quietly skips the step that would have failed is worth less than none."""
    root = story("qa-gate-preflight-absent-")
    try:
        use_project(root)
        # An event log makes this a controller-managed story, which is the only shape whose
        # gate decision the controller builds at all.
        (root / "qa-factory" / "artifacts" / "TP1-15045" / "state" / "events.jsonl").write_text(
            "", encoding="utf-8")
        from controller import Controller
        import stage_guard
        held = (Controller.build_gate_decision, stage_guard.dispatch_errors)
        try:
            del Controller.build_gate_decision
            del stage_guard.dispatch_errors
            result = gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        finally:
            Controller.build_gate_decision = held[0]
            stage_guard.dispatch_errors = held[1]
        unavailable = [f for f in result["findings"] if "rehearsal step unavailable" in f["message"]]
        check_eq("both missing steps are reported", len(unavailable), 2)
        check("and each as a defect of the factory, never as a silent pass",
              all(f["class"] == gate_preflight.FACTORY_DEFECT for f in unavailable))
        check_in("naming the interface that is missing", "build_gate_decision",
                 " ".join(f["message"] for f in unavailable))
        check_in("and the other one too", "dispatch_errors",
                 " ".join(f["message"] for f in unavailable))
    finally:
        cleanup(root)


def test_a_refusal_waiting_on_the_other_side_is_named_before_the_gate() -> None:
    """The second row of the plan's table: the stage guard would not let S5 start, and that was
    deterministic from the moment S4 closed. Whatever the guard would answer then, the person
    hears now — with the command that passes it."""
    root = story("qa-gate-preflight-guard-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stages"]["S4"]["status"] = "running"   # the designer rework still in flight
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        found = by_check(gate_preflight.run(task_root, "A"), "stage_guard")
        check("the guard's refusal is rehearsed", bool(found))
        check_eq("and owned by the factory, with the person's word as the way through",
                 found[0]["class"], gate_preflight.FACTORY_DEFECT)
        check_in("the message says what happens after the approval",
                 "after your approval", found[0]["message"])
        check_in("and the way past it is a line the person writes, named by the finding's own id (t-357)",
                 f"write `{found[0]['id']}: accept` with your reason", found[0]["fix"])
        check_not_in("t-357: and the guard's own command is not in the text", "waiver.py", found[0]["message"] + found[0]["fix"])
        check("t-357: the word passes it", _word_passes(found[0]))
    finally:
        cleanup(root)


def test_the_dirty_tree_and_the_branch_are_asked_inside_the_packet() -> None:
    """The third row of the plan's table. On TP1-15045 the dirty tree and the branch came
    as a SEPARATE stop after the gate, although `--probe-vcs` knew both at S0. One stop, one
    answer: the question belongs in the packet the person is already reading."""
    import shutil
    import subprocess
    if not shutil.which("git"):
        check("git is on PATH for the working-tree question", False, "git not installed")
        return
    root = story("qa-gate-preflight-vcs-")
    try:
        use_project(root)
        repo = root / "tests"
        repo.mkdir(parents=True, exist_ok=True)
        env = {"GIT_AUTHOR_NAME": "qa", "GIT_AUTHOR_EMAIL": "qa@example.invalid",
               "GIT_COMMITTER_NAME": "qa", "GIT_COMMITTER_EMAIL": "qa@example.invalid"}
        import os
        env = dict(os.environ, **env)
        (repo / "test_base.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        for args in (["init", "-b", "story-branch"], ["add", "-A"],
                     ["commit", "-m", "base", "--no-gpg-sign"]):
            subprocess.run(["git", *args], cwd=str(repo), env=env, capture_output=True, text=True)
        (repo / "test_uncommitted.py").write_text("# half-written\n", encoding="utf-8")
        found = by_check(gate_preflight.run(
            root / "qa-factory" / "artifacts" / "TP1-15045", "A"), "vcs")
        check_eq("the tree and the branch are one question, not two", len(found), 1)
        check_eq("and it is the person's to answer", found[0]["class"],
                 gate_preflight.PERSON_DECIDES)
        check_in("it names the branch S5 would write on", "story-branch", found[0]["message"])
        check_in("and the file that is not committed", "test_uncommitted.py", found[0]["message"])
        # GW1-43: the CLEAN tree asks too (this branch, or name another), under the same door; its card is proved by this run
        (repo / "test_uncommitted.py").unlink()
        clean = by_check(gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045", "A"), "vcs")
        check_eq("a clean tree is one question as well, the person's to answer", [f["class"] for f in clean],
                 [gate_preflight.PERSON_DECIDES])
        check_in("it names the branch", "story-branch", clean[0]["message"])
        check("and its door is the block `test repository state: <HEAD>`, which passes it",
              bool(clean[0].get("waives")) and _word_passes(clean[0]), str(clean[0].get("waives")))
    finally:
        cleanup(root)


def test_gate_b_rehearses_the_write_it_is_about_to_authorise() -> None:
    """Gate B's approval is an instruction to write outside the factory.

    The owner's decision of 21.09: a tracker that cannot be written to is an unfinished setup
    of the factory, and how to close it is a choice among three — so it is the PERSON's
    question with options, never a `factory_defect` with a waiver command. A waiver would mean
    "ignore the block", and none of the three answers is that."""
    root = story("qa-gate-preflight-b-")
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["external_writes"] = {"bugs": "jira", "cases": "markdown"}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        found = by_check(gate_preflight.run(
            root / "qa-factory" / "artifacts" / "TP1-15045", "B"), "external_writes")
        check_eq("a channel with no delivery is named before the approval", len(found), 1)
        check_eq("and it is the person's call, not a defect to be waived",
                 found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_not_in("no waiver: none of the three answers is `ignore it`",
                     "waiver.py", found[0]["fix"])
        for option in ("set the delivery up now", "I hand you each write and you give me the id it gets back", "keep it local"):
            check_in(f"the question carries the option: {option}", option, found[0]["fix"])
        check_not_in("t-357: the option names no script and no flag", "external_writes.py", found[0]["fix"])
        check_not_in("t-357: not the flag either", "--external-id", found[0]["fix"])
        check_eq("the same channel is not asked about twice",
                 len(by_check(gate_preflight.run(
                     root / "qa-factory" / "artifacts" / "TP1-15045", "B"), "tracker_write")), 0)
        config["external_writes"] = {"bugs": "jira", "cases": "markdown",
                                     "channels": {"jira": {"method": "agent",
                                                           "invoke": "jira-assistant"}}}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        result = gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045", "B")
        check_eq("a channel an agent delivers has nothing wrong with its delivery",
                 by_check(result, "external_writes"), [])
        # ... but nobody has established that the agent may CREATE anything. TP2-2534:
        # a read-only assistant, discovered after the person had chosen which bugs to file.
        right = by_check(result, "tracker_write")
        check_eq("the write RIGHT is a separate question, asked before the gate", len(right), 1)
        check_eq("and it is the factory's to close, not the person's",
                 right[0]["class"], gate_preflight.FACTORY_FIXABLE)
        check_in("with the exact question to put to the assistant", "writes: yes", right[0]["fix"])
        check_in("and the way to record what it answers, in words (t-357)", "then record what it answered, in its own words", right[0]["fix"])
        check_not_in("t-357: no script and no flag", "tracker_write.py", right[0]["fix"])
        check_not_in("t-357: not the flag either", "--record", right[0]["fix"])
    finally:
        cleanup(root)


def test_the_write_right_the_project_already_denied_is_the_persons_question() -> None:
    """A project whose own config declares the assistant read-only needs no probe — and the
    person is asked once, with the three ways out, before they choose which bugs to file."""
    root = story("qa-gate-preflight-readonly-channel-")
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["external_writes"] = {"bugs": "jira", "cases": "markdown",
                                     "channels": {"jira": {"method": "agent",
                                                           "invoke": "jira-assistant",
                                                           "writes": False}}}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        found = by_check(gate_preflight.run(
            root / "qa-factory" / "artifacts" / "TP1-15045", "B"), "tracker_write")
        check_eq("a declared read-only channel is one question", len(found), 1)
        check_eq("and the person answers it", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("the reason is the project's own declaration", "read-only", found[0]["message"])
        check_in("and the three options are on the line", "keep it local", found[0]["fix"])
    finally:
        cleanup(root)


def test_an_experiment_rehearses_no_write_and_probes_no_tracker() -> None:
    """t-017 D3 (B-003, FR-36): a run whose pipeline says `no_trace` sends nothing after gate B,
    so neither the delivery check nor the write-right check has anything to say - and the probe
    is never called (a probe of a tracker is a call to it). The control is the same story and
    the same config without the flag, which raises both findings."""
    import tracker_write
    root = story("qa-gate-preflight-experiment-")
    task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
    held = tracker_write.probe
    probes: list = []
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["external_writes"] = {"bugs": "jira", "cases": "markdown",
                                     "channels": {"jira": {"method": "agent",
                                                           "invoke": "jira-assistant",
                                                           "writes": False}}}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        result = gate_preflight.run(task_root, "B")
        check_eq("control: without the flag the write right is asked", len(by_check(result, "tracker_write")), 1)
        config["external_writes"] = {"bugs": "jira", "cases": "markdown"}   # no delivery at all
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        check_eq("control: and so is a channel nothing delivers",
                 len(by_check(gate_preflight.run(task_root, "B"), "external_writes")), 1)
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["no_trace"] = True
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        tracker_write.probe = lambda *a, **k: probes.append(a) or {"status": "no", "reason": "x"}
        result = gate_preflight.run(task_root, "B")
        check_eq("an experiment: no finding about the delivery", by_check(result, "external_writes"), [])
        check_eq("an experiment: no finding about the write right", by_check(result, "tracker_write"), [])
        check_eq("an experiment: the tracker is not probed", probes, [])
        pipeline["no_trace"] = False
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("`no_trace: false` closes nothing", len(by_check(gate_preflight.run(task_root, "B"), "external_writes")), 1)
    finally:
        tracker_write.probe = held
        cleanup(root)


def test_the_toolchain_of_the_next_stage_is_collected_before_the_gate() -> None:
    """S0 said "preflight green" and the automator then spent fifteen minutes writing
    code that could not be collected: `ModuleNotFoundError: pydantic`. The story's own tests do
    not exist at gate A — the project's do, and collecting them proves the toolchain is alive."""
    import sys as _sys
    root = story("qa-gate-preflight-collect-")
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        # A stand-in for the project's runner: `--collect-only` on a file whose import fails is
        # exactly the shape of the real failure, without needing pytest itself.
        fake = root / "fake_pytest.py"
        fake.write_text(
            "import sys\n"
            "print('ModuleNotFoundError: No module named \\'pydantic\\'')\n"
            "sys.exit(2)\n", encoding="utf-8")
        config["test_command_templates"] = {
            "quiet": f'"{_sys.executable}" "{fake}" pytest -m "<test-id>" --reruns 2'}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "tests").mkdir(parents=True, exist_ok=True)
        command = gate_preflight.collect_command(config)
        check("the project's own command is what gets rehearsed", "--reruns" in command)
        check("with every placeholder dropped", "<test-id>" not in command)
        check("and the flag that was waiting for it", "-m" not in command)
        check("as a collect, never an execution", "--collect-only" in command)
        found = by_check(gate_preflight.run(
            root / "qa-factory" / "artifacts" / "TP1-15045", "A"), "s5_toolchain")
        check_eq("an uncollectable toolchain is one finding", len(found), 1)
        check_eq("and it is the person's to decide, never a silent factory repair",
                 found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("the finding names what is actually missing", "pydantic", found[0]["message"])
        check_in("and says how to reproduce it, in words (t-357: a flag of the runner is not shown to a person)",
                 "Collecting the project's tests with its own runner, in ", found[0]["fix"])
        check_not_in("t-357: no flag", "--collect-only", found[0]["fix"])
        # A runner that collects cleanly leaves the gate alone.
        # (EP1-9: a collect that lists no id but counts tests is now an unreadable output, so the stand-in lists one)
        fake.write_text("import sys\nprint('tests/test_a.py::test_a')\nprint('3 tests collected')\nsys.exit(0)\n",
                        encoding="utf-8")
        check_eq("a healthy toolchain is not mentioned at all",
                 by_check(gate_preflight.run(
                     root / "qa-factory" / "artifacts" / "TP1-15045", "A"), "s5_toolchain"), [])
    finally:
        cleanup(root)


def test_ep1_9_a_collect_that_counts_tests_and_lists_none_is_unavailable_never_silent() -> None:
    """EP1-9 / A2: the gate's own collect asks the same question S5 asks (`node_ids.unread_count`): pytest said
    N tests were collected and the one parser read none. That is one `unavailable` step naming N and the head of
    the output - not a silent empty string that lets the rehearsal go on as if the project had no tests (AR-28)."""
    import sys as _sys
    root = story("qa-gate-preflight-unreadable-collect-")
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        fake = root / "fake_pytest.py"
        config["test_command_templates"] = {"quiet": f'"{_sys.executable}" "{fake}" pytest'}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "tests").mkdir(parents=True, exist_ok=True)
        task = root / "qa-factory" / "artifacts" / "TP1-15045"

        def toolchain(script: str) -> list:
            fake.write_text(script, encoding="utf-8")
            return by_check(gate_preflight.run(task, "A"), "s5_toolchain")

        found = toolchain("import sys\nprint('=== My Harness v2 ===')\nprint('weird line 1')\nprint('3 tests collected in 0.01s')\n"
                          "sys.exit(0)\n")
        check_eq("N>0 counted and 0 read: one finding", len(found), 1)
        check_eq("and it is the factory's own, never a silent pass or a question to the person",
                 found[0]["class"], gate_preflight.FACTORY_DEFECT)
        check_in("it says the step is unavailable", "rehearsal step unavailable", found[0]["message"])
        check_in("it names the count and that none was read", "collect output unreadable: 3 collected, 0 read",
                 found[0]["message"])
        check_in("and the head of the output", "weird line 1", found[0]["message"])
        found = toolchain("import sys\nprint('3/4 tests collected (1 deselected) in 0.06s')\nsys.exit(0)\n")
        check_in("the deselected form is counted too: 3 of 4 collected, 0 read",
                 "3 collected, 0 read", " ".join(f["message"] for f in found))
        check_eq("a banner before readable ids is not a finding (the one parser skips it)",
                 toolchain("import sys\nprint('=== My Harness v2 ===')\nprint('tests/test_a.py::test_a')\n"
                           "print('1 test collected')\nsys.exit(0)\n"), [])
        check_eq("exit 0, empty output and no count line stays as it was: nothing is said",
                 toolchain("import sys\nsys.exit(0)\n"), [])
        check_eq("exit 5 (nothing matched the filter) is still not a finding, whatever it prints",
                 toolchain("import sys\nprint('3 tests collected')\nsys.exit(5)\n"), [])
    finally:
        cleanup(root)


def test_rh1_3_a_broken_test_file_does_not_stop_the_gate_collect() -> None:
    """RH1-3 3.4: the gate's collect goes on past files that fail to import (the runner's flag is DATA), reads its
    outcome through `node_ids.collect_verdict` with the real exit code, and says only what it proved. `partial` and
    `none_selected` are notes (and a record for the report), `all_broken` and a usage error are the person's card,
    `-x` and a runner that cannot continue say why. Stand-in runner: a script that prints what pytest prints."""
    import sys as _sys
    import collect_gaps
    import launch_check
    root = story("qa-gate-preflight-partial-collect-")
    saved_path = launch_check.CAUSES_PATH
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        fake = root / "fake_pytest.py"
        config["test_command_templates"] = {"quiet": f'"{_sys.executable}" "{fake}" pytest'}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "tests").mkdir(parents=True, exist_ok=True)
        task = root / "qa-factory" / "artifacts" / "TP1-15045"
        broken = "ERROR tests/test_bad.py\nERROR tests/servicenow_budget - ModuleNotFoundError: No module named 'sdk'"

        def script(body: str, code: int) -> str:
            return f"import sys\n{body}\nsys.exit({code})\n"

        def gate(body: str, code: int = 1) -> tuple:
            fake.write_text(script(body, code), encoding="utf-8")
            result = gate_preflight.run(task, "A")
            notes = [n for n in (result.get("info") or result.get("notes") or []) if n.get("check") == "s5_toolchain"]
            return by_check(result, "s5_toolchain"), notes

        healthy = "print('tests/test_a.py::test_a')\nprint('tests/test_a.py::test_b')\n"
        found, notes = gate(healthy + f"print({broken!r})\nprint('2 tests collected, 2 errors in 1s')")
        check_eq("K-3.4-partial exit 1 with the healthy ids and two broken files: no finding, the gate is not held", found, [])
        check_eq("K-3.4-partial ... one note, with the files named and the others said to be collected",
                 (len(notes), "2 of the project's test files could not be collected and are left out" in notes[0]["message"],
                  "tests/test_bad.py, tests/servicenow_budget" in notes[0]["message"],
                  "the other tests were collected" in notes[0]["message"]), (1, True, True, True))
        check_eq("K-3.4-partial ... the note's field holds the files whole",
                 [b["path"] for b in notes[0]["broken_files"]], ["tests/test_bad.py", "tests/servicenow_budget"])
        rows = collect_gaps.read(task)["rows"]
        check_eq("K-3.4-record ... and the story keeps them for the report (source gate_a)",
                 [(r["source"], [b["path"] for b in r["broken"]]) for r in rows],
                 [("gate_a", ["tests/test_bad.py", "tests/servicenow_budget"])])
        found, notes = gate(healthy + "print('2 tests collected in 1s')", code=0)
        check_eq("K-3.4-record a collect that finished with nothing broken erases the row",
                 (found, collect_gaps.read(task)["rows"]), ([], []))

        found, notes = gate("print('ERROR tests/test_bad.py - ImportError: x')\nprint('no tests collected (5 deselected), 1 error in 1s')")
        check_eq("K-3.4-deselected the REAL line when a filter left nothing and one file broken: a note, never the "
                 "PERSON_DECIDES card (B1)",
                 (found, "no test was selected by the filter; 1 file(s) could not be collected" in notes[0]["message"]), ([], True))
        found, notes = gate("print('ERROR tests/test_bad.py - ImportError: x')\nprint('no tests collected, 1 error in 1s')")
        check_eq("K-3.4-all nothing collected and a file broken: the person's card, never `no tests`",
                 (len(found), found[0]["class"], notes), (1, gate_preflight.PERSON_DECIDES, []))
        check_in("K-3.4-all ... with the number of broken files and the first path",
                 "every one of the 1 test files failed to import; the first is tests/test_bad.py", found[0]["message"])
        check_not_in("K-3.4-all ... and the offer to install is not made (it is C3-18's)", "say the word", found[0]["fix"])
        check_eq("m6 all_broken is recorded for the report too (\"let the stage run\" must not leave it silent), owner project",
                 [(r["source"], r["broken"][0]["path"], r["broken"][0].get("owner")) for r in collect_gaps.read(task)["rows"]],
                 [("gate_a", "tests/test_bad.py", "project")])
        found, notes = gate("print('ImportError while loading conftest')", code=4)
        check_eq("K-3.4-root a root conftest that cannot load (exit 4): the old card, the old promise",
                 (len(found), "say the word and I do it" in found[0]["fix"], notes), (1, True, []))
        found, notes = gate("print('3 tests collected')", code=5)
        check_eq("K-3.4-five exit 5 stays the filter's fact: nothing is said", (found, notes), ([], []))
        found, notes = gate("print('tests/a.py::t')\nprint('ERROR tests/test_bad.py')\nprint('!!! stopping after 1 failures !!!')\n"
                            "print('1 test collected, 1 error in 1s')")
        check_eq("K-3.4-stopped `-x` in the addopts: the old card, with the reason, and never `the other tests were collected`",
                 (len(found), "stop the collect at the first error" in found[0]["message"], notes), (1, True, []))
        found, notes = gate("print('tests/a.py::t')\nprint('ERROR tests/test_bad.py')\n")
        check_eq("K-3.4-count no count line at a partial exit: unavailable, never a pass",
                 (len(found), found[0]["class"]), (1, gate_preflight.FACTORY_DEFECT))
        body = ("import os\nif sys.argv.count('-q') >= 2:\n    print('tests/a.py::t')\n    print('ERROR tests/test_bad.py')\n"
                "    print('1 test collected, 1 error in 1s')\nelse:\n    print('<Dir x>')\n    print('  <Module a.py>')\n"
                "    print('ERROR tests/test_bad.py')\n    print('==== 1 test collected, 1 error in 1s ====')")
        found, notes = gate(body)
        check_eq("K-3.4-tree the tree at exit 1 (net verbosity 0, the live gate) is retried with -q and read as partial",
                 (found, len(notes)), ([], 1))

        data = json.loads(saved_path.read_text(encoding="utf-8"))
        data["collect_forms"] = [{k: v for k, v in data["collect_forms"][0].items() if k not in ("continue_tokens", "partial_exits")}]
        other = root / "causes-no-flag.json"
        other.write_text(json.dumps(data), encoding="utf-8")
        launch_check.CAUSES_PATH = other
        found, notes = gate("print('tests/a.py::t')\nprint('ERROR tests/test_bad.py')\nprint('1 test collected, 1 error in 1s')")
        check_eq("K-3.4-noflag a runner row without the flag: the old card, said why one broken file hides the rest",
                 (len(found), "one broken file hides the rest" in found[0]["message"], notes), (1, True, []))
        other.write_text("{not json", encoding="utf-8")
        found, notes = gate("print('tests/a.py::t')\nprint('2 tests collected in 1s')", code=0)
        check_eq("m1 / E3-12 an unreadable runner table: the collect stays all-or-nothing and the gate SAYS so (a note)",
                 (found, [("the runner table could not be read" in n["message"]) for n in notes]), ([], [True]))
    finally:
        launch_check.CAUSES_PATH = saved_path
        cleanup(root)


def test_rh1_4_a_difference_from_the_lock_is_a_note_and_one_phrase_of_the_collect_card() -> None:
    """RH1-4 4.5: `check_s5_dependencies` runs BEFORE the collect; a difference or a missing package is a note with the pair of
    versions and the project's install command (not a finding); the collect's own card or partial note adds the same
    sentence only when the collect then failed on a library, or went partial. K-4.5-*. The check itself is
    `dependency_drift.check` (test_dependency_drift.py); here it is a canned answer."""
    import sys as _sys
    import dependency_drift
    root = story("qa-gate-preflight-drift-")
    held = dependency_drift.check
    calls = []
    cmd = {"argv": ["poetry", "install"], "cwd": ".", "source": "table"}
    sentence = "installed testproject1-sdk-python 0.1.700, the lock says 0.1.704; the project's install command: `poetry install`"

    def drifted(state="differs"):
        return {"state": state, "lock": "poetry.lock", "checked": 2, "conditional": 0, "why": "x", "command": cmd,
                "environment": {"source": "dir", "where": ".venv", "rejected": []}, "absent": [],
                "differs": [{"name": "testproject1-sdk-python", "installed": "0.1.700", "locked": "0.1.704", "direction": "older"}]}

    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        fake = root / "fake_pytest.py"
        config["test_command_templates"] = {"quiet": f'"{_sys.executable}" "{fake}" pytest'}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "tests").mkdir(parents=True, exist_ok=True)
        task = root / "qa-factory" / "artifacts" / "TP1-15045"

        def gate(body: str, code: int, answer, switch=False):
            fake.write_text(f"import sys\n{body}\nsys.exit({code})\n", encoding="utf-8")
            cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            cfg["gate_rehearsal"] = {"skip_dependencies": True} if switch else {}
            (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            dependency_drift.check = lambda *a, **k: (calls.append(a), answer)[1]
            result = gate_preflight.run(task, "A")
            notes = [n for n in result.get("info") or [] if n.get("check") == "s5_dependencies"]
            tool = [n for n in result.get("info") or [] if n.get("check") == "s5_toolchain"]
            return by_check(result, "s5_toolchain"), by_check(result, "s5_dependencies"), notes, tool

        healthy = "print('tests/a.py::t')\nprint('1 test collected in 1s')"
        found, deps, notes, _tool = gate(healthy, 0, drifted())
        check_eq("K-4.5-note: a difference -> one note with the pair and the command; no finding, the collect is quiet",
                 (found, deps, [n["message"] for n in notes]), ([], [], [sentence]))
        check_eq("K-4.5-note: the note's fields hold the lock, the pairs and the command (a reader reads fields, FR-12)",
                 (notes[0]["lock"], notes[0]["differs"][0]["installed"], notes[0]["command"]["argv"]), ("poetry.lock", "0.1.700", ["poetry", "install"]))
        found, deps, notes, _tool = gate(healthy, 0, drifted("missing_only") | {"differs": [], "absent": [{"name": "requests", "locked": "2.0.0"}]})
        check_in("K-4.5-note: missing_only -> the same note, saying it is not installed", "requests is not installed, the lock says 2.0.0", notes[0]["message"])
        for state in ("in_sync", "unknown"):
            found, deps, notes, _tool = gate(healthy, 0, {"state": state, "command": cmd, "why": "w", "lock": "", "checked": 0})
            check_eq(f"K-4.5-quiet: {state} says nothing at the gate", (found, deps, notes), ([], [], []))
        before = len(calls)
        found, deps, notes, _tool = gate(healthy, 0, drifted(), switch=True)
        check_eq("K-4.5-switch: gate_rehearsal.skip_dependencies turns the step off - not called, no note",
                 (len(calls) - before, notes), (0, []))

        broken = "print('tests/test_bad.py')\nprint('ERROR tests/test_bad.py - ImportError: x')\nprint('1 test collected, 1 error in 1s')"
        found, deps, notes, tool = gate("print('tests/a.py::t')\n" + broken, 1, drifted())
        check_eq("K-4.5-partial: a partial collect on a drifted environment: the note of the collect carries the pair and the command",
                 (found, sentence in tool[0]["message"], len(notes)), ([], True, 1))
        found, _deps, _notes, _tool = gate("print('ModuleNotFoundError: No module named \\'sdk\\'')", 2, drifted())
        check_eq("K-4.5-failed: a collect that fails on a library: the card adds the pair and the command",
                 (len(found), sentence in found[0]["message"]), (1, True))
        found, _deps, _notes, _tool = gate("print('Segmentation fault')", 2, drifted())
        check_eq("K-4.5-failed: a collect that fails for another reason does NOT get the phrase (it would be a guess)",
                 (len(found), sentence in found[0]["message"]), (1, False))
        found, _deps, _notes, _tool = gate("print('ModuleNotFoundError: No module named \\'sdk\\'')", 2, {"state": "in_sync", "command": cmd})
        check_eq("K-4.5-failed: the same failure on an in-sync environment: no phrase", (len(found), "lock says" in found[0]["message"]), (1, False))
        found, _deps, _notes, _tool = gate("print('ERROR tests/test_bad.py - ImportError: x')\nprint('no tests collected, 1 error in 1s')", 2, drifted())
        check_eq("K-4.5-all: every file broken on a drifted environment: the card adds the pair", (len(found), sentence in found[0]["message"]), (1, True))
        found, _deps, _notes, _tool = gate("", 2, drifted())
        check_eq("K-4.5-failed (F4): a collect that FAILED with an empty output, drift set: no phrase (nothing says it was a library)",
                 (len(found), found[0]["class"], sentence in found[0]["message"]), (1, gate_preflight.PERSON_DECIDES, False))

        def with_profiles(rows):
            cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            cfg["profiles"] = rows
            (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

        def test_command(cwd):
            return {"one_test": {"argv": ["pytest"], "kind": "test", "cwd": cwd}}

        with_profiles([{"profile_id": "api", "commands": test_command(".")}, {"profile_id": "ui", "commands": test_command(".")}])
        before = len(calls)
        _found, _deps, notes, _tool = gate(healthy, 0, drifted())
        check_eq("Q1: two selected profiles over one environment -> ONE check, ONE note naming both profiles",
                 (len(calls) - before, len(notes), notes[0]["profiles"], notes[0]["message"].startswith("(api, ui) installed")),
                 (1, 1, ["api", "ui"], True))
        with_profiles([{"profile_id": "api", "commands": test_command(".")}, {"profile_id": "ui", "commands": test_command("web")}])
        before = len(calls)
        _found, _deps, notes, _tool = gate(healthy, 0, drifted())
        check_eq("Q1: two profiles over two environments (another cwd) -> two checks, one note each, each naming its profile",
                 (len(calls) - before, sorted(n["profiles"][0] for n in notes)), (2, ["api", "ui"]))
        with_profiles([{"profile_id": "api", "selected": False, "commands": test_command(".")},
                       {"profile_id": "ui", "commands": test_command("web")}])
        before = len(calls)
        _found, _deps, notes, _tool = gate(healthy, 0, drifted())
        check_eq("F1: a deselected profile (`selected: false`) takes no part; one without the key does",
                 (len(calls) - before, [n["profiles"] for n in notes]), (1, [["ui"]]))
        with_profiles([])
        dependency_drift.check = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        fake.write_text(f"import sys\n{healthy}\nsys.exit(0)\n", encoding="utf-8")
        result = gate_preflight.run(task, "A")
        check_eq("a check that raises is one unavailable step, the collect still runs",
                 ([f["class"] for f in by_check(result, "s5_dependencies")], by_check(result, "s5_toolchain")),
                 ([gate_preflight.FACTORY_DEFECT], []))
    finally:
        dependency_drift.check = held
        cleanup(root)


def test_the_credentials_of_the_next_stage_name_the_file_that_reads_them() -> None:
    """The credentials the person supplied went into the `.env` of the
    wrong directory — a second stop, a 24-minute window, for a path the config already held."""
    root = story("qa-gate-preflight-creds-")
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["environment"] = {"env_file": "harness/.env", "user_key": "AUTH_USERNAME",
                                 "secret_keys": ["AUTH_PASSWORD"]}
        config["environments"] = [{"name": "localhost", "credentials_by_role": {
            "default_user": ".env: AUTH_USERNAME / AUTH_PASSWORD",
            "project_scoped_user": "NOT provisioned locally"}}]
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "harness").mkdir(parents=True, exist_ok=True)
        (root / "harness" / ".env").write_text("AUTH_USERNAME=admin@example.invalid\n",
                                               encoding="utf-8")
        found = by_check(gate_preflight.run(
            root / "qa-factory" / "artifacts" / "TP1-15045", "A"), "s5_environment")
        check_eq("what the stage needs from the environment is one question", len(found), 1)
        check_eq("and it is the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("the missing key is named", "AUTH_PASSWORD", found[0]["message"])
        check_not_in("an account the stand records as not provisioned is no longer asked for "
                     "here: a case that needs one says so in its preconditions (t-218, F2b)",
                     "project_scoped_user", found[0]["message"])
        check_not_in("the key that IS set is not asked for again",
                     "AUTH_USERNAME", found[0]["message"])
        check_in("and the answer says which file actually reads them",
                 "harness/.env", found[0]["fix"])
        text = json.dumps(found)
        check_not_in("no value ever leaves this check", "admin@example.invalid", text)
    finally:
        cleanup(root)


def test_the_rehearsal_writes_nothing() -> None:
    """Read-only is a contract, not an intention: a rehearsal that moved the story would be a
    second way to run it."""
    root = story("qa-gate-preflight-readonly-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        before = {p.relative_to(root).as_posix(): p.read_bytes()
                  for p in root.rglob("*") if p.is_file()}
        gate_preflight.run(task_root, "A")
        gate_preflight.run(task_root, "B")
        after = {p.relative_to(root).as_posix(): p.read_bytes()
                 for p in root.rglob("*") if p.is_file()}
        check_eq("no file was added or removed", sorted(after), sorted(before))
        check_eq("and none was changed",
                 [k for k in before if after.get(k) != before[k]], [])
    finally:
        cleanup(root)


def test_the_brief_block_is_short_and_says_who_owns_what() -> None:
    result = {"gate": "A", "next_stage": "S5", "can_proceed": False,
              "by_class": {gate_preflight.FACTORY_FIXABLE: 2,
                           gate_preflight.PERSON_DECIDES: 7,
                           gate_preflight.FACTORY_DEFECT: 0},
              "findings": [{"id": f"x-{n}", "check": "case_environment",
                            "class": gate_preflight.PERSON_DECIDES,
                            "message": f"question {n}", "fix": ""} for n in range(7)]}
    lines = gate_preflight.brief_lines(result)
    check("the block stays short enough for the gate packet", len(lines) <= 7)
    check_in("it says the gate should not have been shown while repairs are open",
             "should not have been shown yet", lines[0])
    check_in("the rest are named as the person's call", "your call", "\n".join(lines))
    check_in("and the tail points at the full list, in words (t-357: no script name)",
             "the whole list is under \"Rehearsal of gate A\" below", lines[-1])
    check_not_in("t-357: and names no command", "gate_preflight.py", lines[-1])
    clean = gate_preflight.brief_lines({"gate": "A", "next_stage": "S5", "can_proceed": True,
                                        "findings": [], "by_class": {}})
    check_eq("a clean rehearsal is one line", len(clean), 1)
    check_in("and it answers the only question that matters", "S5 can start: yes", clean[0])
    skipped = gate_preflight.brief_lines(
        {"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {},
         "findings": [{"id": "c-1", "check": "critic_rollcall",
                       "class": gate_preflight.PERSON_DECIDES, "message": "8 of 15", "fix": ""}]},
        skip_checks=("critic_rollcall",))
    check_not_in("what the packet already states in its own words is not repeated",
                 "8 of 15", "\n".join(skipped))


def test_s4_does_not_close_while_the_factory_owes_itself_a_repair() -> None:
    """The gate is the last stop before the next stage, so the stage in front
    of it does not close while something the factory can mend itself is still open."""
    root = story("qa-stage-done-rehearsal-")
    try:
        use_project(root)
        code = stage_done.run("TP1-15045", "S4", "done", "qa-case-critic", "cases reviewed", True)
        check_eq("S4 refuses to close over the unapplied critic fix", code, stage_done.EXIT_BAD_ARGS)
        pipeline = json.loads((root / "qa-factory" / "artifacts" / "TP1-15045" /
                               "pipeline.json").read_text(encoding="utf-8"))
        check_eq("and nothing was written", pipeline["stages"]["S4"]["status"], "done")
        check_eq("a stage that is not in front of a gate is never rehearsed",
                 stage_done.gate_rehearsal_errors(
                     root / "qa-factory" / "artifacts" / "TP1-15045", "A") != [], True)
    finally:
        cleanup(root)


def test_ep1_24_b3_a_refusal_with_a_typed_argv_names_the_command() -> None:
    """EP1-24 B3 (AK6, AK7, B-7): a `factory_fixable` finding that carries `argv` is quoted with the command that the config's
    portable form resolves to on THIS machine (no `{python}`); a finding without one is the same bytes as before; an argv
    that is not a list of strings, or holds an unknown `{token}`, is never shown as a command."""
    import runtime_probe
    real = gate_preflight.run
    head = [runtime_probe.PY_TOKEN, runtime_probe.PLUGIN_TOKEN + "/scripts/runtime_probe.py"]

    def finding(**extra) -> dict:
        return {"id": "c-1", "check": "s5_runtime_probe", "class": gate_preflight.FACTORY_FIXABLE,
                "message": "`api`: matched.", "fix": "the factory registers this probe itself", **extra}
    try:
        def errors(item: dict) -> list:
            gate_preflight.run = lambda task_root, gate: {"findings": [item]}
            return stage_done.gate_rehearsal_errors(Path("."), "A")
        plain = errors(finding())
        check_eq("AK7: no argv: the text is what it was", plain,
                 ["gate rehearsal: `api`: matched. [fix: the factory registers this probe itself]"])
        text = errors(finding(argv=[*head, "--suggest", "--write", "--profile", "api"]))[0]
        check_in("AK6: the command is named", "--suggest --write --profile api", text)
        check_not_in("AK6: resolved, no `{python}`", "{python}", text)
        check_not_in("AK6: resolved, no `{plugin_root}`", "{plugin_root}", text)
        check_in("AK6: the reason is kept", "`api`: matched.", text)
        for label, argv in (("an unknown token", [*head, "--x", "{mystery}"]), ("not a list", "runtime_probe.py --suggest"),
                            ("a non-string element", [*head, 3]), ("an empty list", [])):
            shown = errors(finding(argv=argv))
            check_eq(f"B-7: {label}: the text is the one without a command", shown, plain)
        # F2: only the probe's `argv` is a command for whoever closes the stage. The reporter's is the helper's own line, ending
        # `--by driver`: a role is refused it (PT-human-word) and a conductor would write a false author.
        reporter = {"id": "s5_reporter-1", "check": "s5_reporter", "class": gate_preflight.FACTORY_FIXABLE,
                    "message": "`web`: the report is a trx.", "fix": "the factory records the kind itself",
                    "argv": [*head[:1], head[1].replace("runtime_probe.py", "report_adapt.py"), "kind", "--profile", "web",
                             "--reader", "trx", "--by", "driver", "--task", "T-1"]}
        gate_preflight.run = lambda task_root, gate: {"findings": [reporter]}
        check_eq("F2: a reporter finding with an argv: no command, the text as without one",
                 stage_done.gate_rehearsal_errors(Path("."), "A"),
                 ["gate rehearsal: `web`: the report is a trx. [fix: the factory records the kind itself]"])
        # F4: the waiver is matched on the error's text and the command is not part of it: a word that only the command's
        # path or flags would satisfy passes nothing (before this, `runtime_probe.py` alone passed a factory repair)
        from waiver import split_overridden
        gate_preflight.run = lambda task_root, gate: {"findings": [finding(argv=[*head, "--suggest", "--write", "--profile", "api"])]}
        pairs = stage_done.gate_rehearsal_pairs(Path("."), "A")
        check_not_in("F4: the error text the waiver reads carries no command", "[command:", pairs[0][0])
        check_in("F4: the command is the pair's second half", "--suggest --write --profile api", pairs[0][1])
        word = {"stage_overrides": [{"stage": "S4", "match": "runtime_probe.py", "decision": "go on", "at": "2026-10-30T10:00:00"}]}
        blocking, passed = split_overridden([e for e, _c in pairs], word, "S4")
        check_eq("F4: a word matching only the command's path passes nothing", (len(blocking), passed), (1, []))
        word["stage_overrides"][0]["match"] = "matched"
        blocking, passed = split_overridden([e for e, _c in pairs], word, "S4")
        check_eq("F4 control: a word matching the finding's own text still passes it", (blocking, len(passed)), ([], 1))
    finally:
        gate_preflight.run = real


def test_ep1_24_f4_the_close_refusal_prints_the_command_and_the_waiver_ignores_it() -> None:
    """EP1-24 F4 at the site: `stage_done.run` closing S4 over a factory-fixable finding with a probe `argv`: the refusal PRINTS
    the command, and a person's word that matches only the command (`runtime_probe.py`) does not lift the refusal."""
    import contextlib
    import io
    import runtime_probe
    root = story("qa-stage-done-f4-")
    real = gate_preflight.run
    try:
        use_project(root)
        argv = [runtime_probe.PY_TOKEN, runtime_probe.PLUGIN_TOKEN + "/scripts/runtime_probe.py", "--suggest", "--write", "--profile", "api"]
        gate_preflight.run = lambda task_root, gate: {"findings": [
            {"id": "s5_runtime_probe-1", "check": "s5_runtime_probe", "class": gate_preflight.FACTORY_FIXABLE,
             "message": "`api`: matched.", "fix": "the factory registers this probe itself", "argv": argv}]}
        pipeline_path = root / "qa-factory" / "artifacts" / "TP1-15045" / "pipeline.json"
        data = json.loads(pipeline_path.read_text(encoding="utf-8"))
        data["stage_overrides"] = [{"stage": "S4", "match": "runtime_probe.py", "decision": "go on", "at": "2026-10-30T10:00:00"}]
        pipeline_path.write_text(json.dumps(data), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = stage_done.run("TP1-15045", "S4", "done", "qa-case-critic", "cases reviewed", True)
        check_eq("F4: a word that matches only the command does not close the stage", code, stage_done.EXIT_BAD_ARGS)
        check_in("F4: the refusal prints the finding", "gate rehearsal: `api`: matched.", err.getvalue())
        check_in("F4: and the command beside it", "[command: ", err.getvalue())
        check_in("F4: with the profile's write", "--suggest --write --profile api", err.getvalue())
    finally:
        gate_preflight.run = real
        cleanup(root)


def test_a_persons_word_closes_the_stage_anyway() -> None:
    """Any refusal this factory adds must name the way a person's word passes it."""
    root = story("qa-stage-done-word-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S4", "match": "*",
                                        "decision": "go to the gate, I will read the fixes there",
                                        "by": "human"}]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        code = stage_done.run("TP1-15045", "S4", "done", "qa-case-critic", "cases reviewed", True)
        check_eq("the person's word closes the stage", code, 0)
    finally:
        cleanup(root)


def test_a_clean_story_closes_s4_without_a_word() -> None:
    """The refusal must be about a real finding, not about having a rehearsal at all."""
    root = story("qa-stage-done-clean-", with_fixes=False)
    try:
        use_project(root)
        result = gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        check_eq("nothing is left for the factory to repair",
                 result["by_class"][gate_preflight.FACTORY_FIXABLE], 0)
        check("the gate may be shown", result["gate_ready"])
        check("but not without an answer: the declared gap is still a question",
              not result["can_proceed"])
        code = stage_done.run("TP1-15045", "S4", "done", "qa-case-critic", "cases reviewed", True)
        check_eq("a story with nothing for the factory to repair closes S4", code, 0)
    finally:
        cleanup(root)

# --- what the cases need from the stand ------------------------------------------------

TC_012 = (
    "---\nid: TC-012\nplan_row: TS-1\ntask: TP1-15045\n"
    'preconditions: [{"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are '
    'enabled", "partitions": ["P-selfref"], "check": {"http": {"path": "/v1/config", "status": 200, '
    '"json_path": "features.subWorkflow", "equals": true}}}, {"id": "PC-2", "kind": "data", '
    '"what": "a guardrail owned by another project", "partitions": ["P-guardrail"], "check": '
    '{"none": "no API lists guardrails of a project the caller is not in"}}, {"id": "PC-3", '
    '"kind": "account", "what": "a non-owner account", "partitions": ["P-nonowner"], "check": '
    '{"env": "NON_OWNER_USERNAME"}}, {"id": "PC-4", "kind": "env", "what": "the default '
    'account", "check": {"env": "AUTH_USERNAME"}}]\n---\n\n'
    "## Given\n| P-valid | P-warn | P-auto | P-selfref | P-guardrail | P-nonowner |\n\n"
    "## Then\n1. each partition returns its own status.\n")


def stand_story(prefix: str, case_text: str = TC_012) -> Path:
    """The TP1-15045 stand: one account in the env file the conftest loads, the second
    account's variables in a file it does not, and a feature flag that is off."""
    import hashlib
    root = story(prefix, with_fixes=False)
    config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    config["environments"] = [{"name": "localhost", "base_url": "http://stand.invalid:8080"}]
    (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "tests" / "harness").mkdir(parents=True)
    (root / "tests" / "harness" / "conftest.py").write_text(
        "from dotenv import load_dotenv\nload_dotenv(Path(__file__).parent / '.env')\n",
        encoding="utf-8")
    (root / "tests" / "harness" / ".env").write_text("AUTH_USERNAME=admin@example.invalid\n",
                                                     encoding="utf-8")
    (root / "tests" / "harness" / ".env.accounts").write_text(
        "NON_OWNER_USERNAME=bob@example.invalid\nNON_OWNER_PASSWORD=hunter2-not-printed\n",
        encoding="utf-8")
    task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
    case = task_root / "work" / "test-cases" / "workflows" / "TC-012.md"
    case.write_text(case_text, encoding="utf-8")
    links = json.loads((task_root / "state" / "story-case-links.json").read_text(encoding="utf-8"))
    links["links"].append({"case_id": "TC-012", "version": "cv_one",
                           "content_hash": hashlib.sha256(case.read_bytes()).hexdigest(),
                           "path": "work/test-cases/workflows/TC-012.md"})
    (task_root / "state" / "story-case-links.json").write_text(json.dumps(links), encoding="utf-8")
    return root


class stub_http:
    """Every test here answers for the stand itself: nothing in this file opens a socket."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __enter__(self):
        self.real = gate_preflight.http_get

        def fake(url, timeout_s):
            self.calls.append((url, timeout_s))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
        gate_preflight.http_get = fake
        return self

    def __exit__(self, *exc):
        gate_preflight.http_get = self.real


def test_what_a_case_needs_from_the_stand_is_one_question_per_case() -> None:
    """TP1-15045, TC-012 / TC-014: `features:subWorkflow` was off, there was no guardrail
    data and no non-owner account, and the account variables sat in an env file the conftest
    never loads. All of it surfaced in S5, a dispatch at a time."""
    root = stand_story("qa-gate-preflight-preconditions-")
    try:
        use_project(root)
        with stub_http((200, json.dumps({"features": {"subWorkflow": False}}))) as http:
            result = gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        found = by_check(result, "case_preconditions")
        # F1b (t-218): the prose `none` of a story is ONE card of its own, so the case's two
        # unmet needs are one question and its `none` item is the story-wide one.
        none_card = [f for f in found if f["message"].startswith("preconditions no machine can check")]
        found = [f for f in found if f not in none_card]
        check_eq("two unmet needs of one case are ONE question", len(found), 1)
        check_eq("the prose `none` is one card beside it", len(none_card), 1)
        check_in("which quotes the designer's reason as written",
                 '"no API lists guardrails of a project the caller is not in" (TC-012)',
                 none_card[0]["message"])
        check_eq("and is the person's too", none_card[0]["class"], gate_preflight.PERSON_DECIDES)
        check_eq("and it is the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
        message = found[0]["message"]
        check_in("the case is named first", "TC-012: 2 of 6 partitions", message)
        check_in("the partitions that wait are named", "P-selfref, P-nonowner", message)
        check_in("in the designer's plain words", "sub-workflow states are enabled", message)
        check_in("what the stand answered is said", "`features.subWorkflow` is false, expected true", message)
        check_in("the variable is looked for where the conftest really loads it",
                 "(`tests/harness/.env`, per the project's own conftest", message)
        check_in("and the file that holds it but is never loaded is named",
                 "tests/harness/.env.accounts", message)
        check_not_in("a met precondition is not mentioned", "PC-4", message)
        # t-256 O6: the card prints the form the register's parser reads, per case - `<case id>: accept as blocked`
        check_in("the two ways out are offered, the second as the exact line to write", "`TC-012: accept as blocked`", found[0]["fix"])
        check_not_in("...and not the old words, which applied nothing", "accept them as blocked", found[0]["fix"])
        text = json.dumps(result)
        check_not_in("no value of any variable leaves the check", "example.invalid", text)
        check_not_in("nor a secret", "hunter2", text)
        check_not_in("nor the stand's address", "stand.invalid", text)
        check_eq("the path is glued to the API base URL from config",
                 [url for url, _ in http.calls], ["http://stand.invalid:8080/v1/config"])
        check("with a short timeout", all(t <= 10 for _, t in http.calls))
        check("a question never stops the stage in front of the gate", result["gate_ready"])
    finally:
        cleanup(root)


def test_a_stand_that_meets_every_precondition_raises_nothing() -> None:
    root = stand_story("qa-gate-preflight-preconditions-met-")
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["environment"] = {"env_files": ["tests/harness/.env", "tests/harness/.env.accounts"]}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        with stub_http((200, json.dumps({"features": {"subWorkflow": True}}))):
            found = by_check(gate_preflight.run(
                root / "qa-factory" / "artifacts" / "TP1-15045", "A"), "case_preconditions")
        check_eq("with `environment.env_files` naming both files only the uncheckable one is left",
                 len(found), 1)
        check_in("and it is the story-wide card of the prose `none`, naming the case",
                 "1 precondition of 1 case cannot be checked on the stand", found[0]["message"])
        check_in("with the designer's own reason", '"no API lists guardrails of a project the '
                 'caller is not in" (TC-012)', found[0]["message"])
    finally:
        cleanup(root)


def test_a_check_that_cannot_run_is_never_the_persons_problem() -> None:
    root = stand_story("qa-gate-preflight-preconditions-error-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        with stub_http(OSError("connection refused by http://stand.invalid:8080")) as http:
            found = by_check(gate_preflight.run(task_root, "A"), "case_preconditions")
        classes = sorted(f["class"] for f in found)
        check_eq("the dead stand is the factory's finding, the rest still a question (the "
                 "case's own unmet need, and the story-wide card of the prose `none`)",
                 classes, sorted([gate_preflight.FACTORY_DEFECT, gate_preflight.PERSON_DECIDES,
                                  gate_preflight.PERSON_DECIDES]))
        broken = [f for f in found if f["class"] == gate_preflight.FACTORY_DEFECT][0]
        check_in("it says the check could not run", "could not be checked", broken["message"])
        check_in("and that it is nothing of the person's to repair", "nothing of yours", broken["fix"])
        check_not_in("the stand's address is not printed even from an exception",
                     "stand.invalid", json.dumps(found))
        check_eq("one request per rehearsal, however it ended", len(http.calls), 1)
        with stub_http((302, "")):
            found = by_check(gate_preflight.run(task_root, "A"), "case_preconditions")
        check_eq("a stand behind a login is not an error", [f["class"] for f in found],
                 [gate_preflight.PERSON_DECIDES, gate_preflight.PERSON_DECIDES])
        check_in("it is a precondition nobody can verify from here", "wants a login",
                 [f["message"] for f in found])
        with stub_http((200, "<html>not json</html>")):
            found = by_check(gate_preflight.run(task_root, "A"), "case_preconditions")
        check_in("a body that is not JSON is the factory's too", "did not return JSON",
                 [f["message"] for f in found if f["class"] == gate_preflight.FACTORY_DEFECT])
        # B-408: the body of an error answer is kept, so a protection page is told from the stand's own 403
        page = ('<html><head><title>Attention Required! | Cloudflare</title></head><body>blocked</body></html>')
        with stub_http((403, "")):
            found = by_check(gate_preflight.run(task_root, "A"), "case_preconditions")
        check_in("B-408 control: an EMPTY 403 keeps the sentence 'wants a login'", "wants a login", [f["message"] for f in found])
        with stub_http((403, page)):
            found = by_check(gate_preflight.run(task_root, "A"), "case_preconditions")
        messages = [f["message"] for f in found]
        check_in("B-408: a 403 that is a page says it is not shown to be the stand's own, with the title",
                 "Attention Required! | Cloudflare", messages)
        check_in("B-408: ... and that whether the stand wants a login is unknown", "whether the stand wants a login is unknown", messages)
        check("B-408: ... and the state stays 'uncheckable' (the same two person-decides cards, no factory defect), no claim that it wants a login",
              sorted(f["class"] for f in found) == [gate_preflight.PERSON_DECIDES, gate_preflight.PERSON_DECIDES]
              and not any("it wants a login" in m for m in messages), str(messages))
        with stub_http((200, page)):
            found = by_check(gate_preflight.run(task_root, "A"), "case_preconditions")
        check_in("B-408: a 200 that is not JSON names its title", "Attention Required! | Cloudflare",
                 [f["message"] for f in found if f["class"] == gate_preflight.FACTORY_DEFECT])
    finally:
        cleanup(root)


def test_http_get_keeps_the_error_body_and_names_the_factory() -> None:
    """B-408: `http_get` (the one function every other test replaces) is a real request here: the 403 body comes back, a
    302 is not followed, and the User-Agent is the factory's."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("User-Agent", ""))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b"<html><title>Blocked</title></html>"
            self.send_response(403)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        check_eq("B-408: the body of a 403 is returned, not dropped", gate_preflight.http_get(base + "/x", 5),
                 (403, "<html><title>Blocked</title></html>"))
        check_eq("B-408: a 302 is the answer (not followed)", gate_preflight.http_get(base + "/redirect", 5), (302, ""))
        check("B-408: every request carries the factory's User-Agent", seen and all(u.startswith("qa-factory/") for u in seen), str(seen))
    finally:
        server.shutdown()
        server.server_close()
    # F1: the status arrived and the body stalls - the words of this function are unchanged
    from test_http_client import StallStub
    stall = StallStub(200)
    try:
        try:
            gate_preflight.http_get(stall.url, 1)
            said = "returned"
        except TimeoutError:
            said = "TimeoutError"
        check_eq("B-408 F1: a 2xx whose body stalls still raises the timeout (the stand 'did not answer', as before)", said, "TimeoutError")
        stall.status = 500
        check_eq("B-408 F1: a 500 whose body stalls is (500, '') as before", gate_preflight.http_get(stall.url, 1), (500, ""))
    finally:
        stall.close()


def test_a_case_without_preconditions_is_never_refused() -> None:
    """Stories in flight: a case written by 0.7.4 has no such field, and says nothing."""
    root = story("qa-gate-preflight-preconditions-none-", with_fixes=False)
    try:
        use_project(root)
        with stub_http(AssertionError("no request may be made for a case that asks for nothing")) as http:
            result = gate_preflight.run(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        check_eq("no finding", by_check(result, "case_preconditions"), [])
        check_eq("and no request", http.calls, [])
    finally:
        cleanup(root)


def test_an_unreadable_preconditions_line_is_the_factorys_to_repair() -> None:
    root = stand_story("qa-gate-preflight-preconditions-shape-",
                       TC_012.replace('"kind": "feature_flag"', '"kind": "toggle"'))
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        with stub_http((200, "{}")) as http:
            found = by_check(gate_preflight.run(task_root, "A"), "case_preconditions")
        check_eq("a designer rework repairs it", [f["class"] for f in found],
                 [gate_preflight.FACTORY_FIXABLE])
        check_in("the closed list is in the message", "feature_flag", found[0]["message"])
        check_in("and a person's word passes it, as a line they write (t-357)",
                 f"write `{found[0]['id']}: accept` with your reason", found[0]["fix"])
        check_not_in("t-357: and no script is named", "validate_artifacts.py", found[0]["fix"])
        check("t-357: the word passes it", _word_passes(found[0]))
        check_eq("nothing of a line that cannot be read is sent to the stand", http.calls, [])
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["gate_rehearsal"] = {"skip_preconditions": True}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        check_eq("a project that says no is not checked",
                 by_check(gate_preflight.run(task_root, "A"), "case_preconditions"), [])
    finally:
        cleanup(root)


def test_the_shape_has_one_owner() -> None:
    items, errors = gate_preflight.parse_preconditions(gate_preflight.case_preconditions_raw(TC_012))
    check_eq("the real-shaped line parses clean", (len(items), errors), (4, []))
    check_eq("a case that declares nothing is None, not an empty list",
             gate_preflight.case_preconditions_raw("---\nid: TC-1\n---\nbody"), None)
    for name, raw, needle in (
            ("not JSON", "[{id: PC-1}]", "not JSON"),
            ("a nested block", "", "one line of JSON"),
            ("two checks at once", '[{"id": "PC-1", "kind": "env", "what": "x", "check": '
                                   '{"env": "A", "none": "b"}}]', "exactly one of"),
            ("a duplicate id", '[{"id": "PC-1", "kind": "env", "what": "x", "check": {"env": "A"}}, '
                               '{"id": "PC-1", "kind": "env", "what": "y", "check": {"env": "B"}}]',
             "used twice"),
            ("equals without a path", '[{"id": "PC-1", "kind": "service", "what": "x", "check": '
                                      '{"http": {"path": "/health", "equals": 1}}}]', "needs a json_path"),
            ("a misspelt http key", '[{"id": "PC-1", "kind": "service", "what": "x", "check": '
                                    '{"http": {"path": "/health", "jsonpath": "a"}}}]', "unknown keys")):
        check_in(f"rejected: {name}", needle, gate_preflight.parse_preconditions(raw)[1])
    check_eq("a list is indexed by number",
             gate_preflight._json_path({"a": [{"b": True}]}, "a.0.b"), (True, True))
    # t-218 F1: the two structured answers to "who provides this", never read from prose.
    for name, raw, needle in (
            ("case_seeds with no words", '[{"id": "PC-1", "kind": "data", "what": "x", "check": '
                                         '{"case_seeds": ""}}]', "must say what the case itself creates"),
            ("case_seeds that is not text", '[{"id": "PC-1", "kind": "data", "what": "x", "check": '
                                            '{"case_seeds": 1}}]', "check.case_seeds"),
            ("stand_account with no role", '[{"id": "PC-1", "kind": "account", "what": "x", "check": '
                                           '{"stand_account": " "}}]', "credentials_by_role"),
            ("stand_account that is not text", '[{"id": "PC-1", "kind": "account", "what": "x", '
                                               '"check": {"stand_account": ["a"]}}]', "check.stand_account")):
        check_in(f"rejected: {name}", needle, gate_preflight.parse_preconditions(raw)[1])
    for name, raw in (
            ("case_seeds", '[{"id": "PC-1", "kind": "data", "what": "x", "check": {"case_seeds": "a workflow"}}]'),
            ("stand_account", '[{"id": "PC-1", "kind": "account", "what": "x", "check": '
                              '{"stand_account": "default_user"}}]')):
        check_eq(f"accepted: {name}", gate_preflight.parse_preconditions(raw)[1], [])
    check_in("the form the designer reads names both kinds (FR-38)", "case_seeds",
             gate_preflight.PRECONDITION_FORM)
    check_in("and the other one", "stand_account", gate_preflight.PRECONDITION_FORM)


# --- t-218: the cmp2 story (TP1-15045, gate A of 01.10.2026) ---------------------------------
#
# Built in the OS temp from the shapes of the real files: the config of testproject1-sdk-cmp2, the
# plan rows TS-4/8 e2e-ui and TS-10/12/14/15 api automate, and the `preconditions` line of every
# case of the story. Nothing here starts docker, a probe or a collect: the stand is stubbed.

CMP2_TICKET = "TP1-15045"
CMP2_SEED_REASONS = {  # the reason each case gave, verbatim from the cmp2 files
    1: "seeded by the case itself, no machine check of the stand applies",
    9: "invalid revision is seeded by the case itself",
}
CMP2_SUPERADMIN = "the localhost superadmin holds it"
CMP2_NEEDS_PREVIEW = "localhost has only the superadmin; needs the preview stand"


def _pc(pid, kind, what, partitions, legacy, rewritten=None):
    return {"id": pid, "kind": kind, "what": what, "partitions": partitions,
            "legacy": {"none": legacy}, "rewritten": rewritten or {"none": legacy}}


def _seeded(what, reason="seeded by the case itself", partitions=()):
    return _pc("PC-1", "data", what, list(partitions), reason, {"case_seeds": what})


def _superadmin(what):
    return _pc("PC-1", "account", what, [], CMP2_SUPERADMIN, {"stand_account": "default_user"})


# case number -> (plan row, its preconditions); 5 and 13 declare none, as on cmp2
CMP2_CASES = {
    1: ("TS-1", [_seeded("a workflow with at least two saved revisions, created by the case",
                         CMP2_SEED_REASONS[1])]),
    2: ("TS-2", [_seeded("a workflow with two revisions: one added state and one state whose "
                         "prompt changed", partitions=["P-added", "P-modified"])]),
    3: ("TS-3", [_seeded("a workflow whose selected revision has a state that the editor YAML "
                         "no longer has")]),
    4: ("TS-4", [_seeded("an own workflow with at least one saved revision, created by the case")]),
    5: ("TS-5", []),
    6: ("TS-6", [_seeded("a workflow with at least two saved revisions, created by the case")]),
    7: ("TS-7", [_seeded("a workflow with at least three states across two revisions")]),
    8: ("TS-8", [_seeded("an own workflow with at least two states and two revisions")]),
    9: ("TS-9", [_seeded("a workflow with one valid and one hand-seeded invalid saved revision",
                         CMP2_SEED_REASONS[9], ["P-invalid"])]),
    10: ("TS-10", [_superadmin("an account with WRITE ability on an own project")]),
    11: ("TS-11", [_seeded("an own workflow with at least three revisions")]),
    12: ("TS-12", [_superadmin("an account with WRITE ability on an own project")]),
    13: ("TS-13", []),
    14: ("TS-14", [
        {"id": "PC-1", "kind": "account", "what": "a non-admin user inside W's project with "
         "read-only ability (no WRITE)", "partitions": ["P-nowrite"],
         "legacy": {"env": "TC014_READONLY_USER_TOKEN"}, "rewritten": {"env": "TC014_READONLY_USER_TOKEN"}},
        {"id": "PC-2", "kind": "account", "what": "a non-admin user outside W's project",
         "partitions": ["P-noproject"], "legacy": {"env": "TC014_OUTSIDE_USER_TOKEN"},
         "rewritten": {"env": "TC014_OUTSIDE_USER_TOKEN"}}]),
    15: ("TS-15", [_superadmin("an account with WRITE ability on an own project")]),
    16: ("TS-17", [_seeded("a workflow with a seeded malformed revision and one with a blank "
                           "yaml_config", partitions=["P-parse", "P-empty"])]),
    17: ("TS-20", [_pc("PC-1", "account", "a second user with read-only ability on the workflow",
                       ["P-readonly"], CMP2_NEEDS_PREVIEW)]),
    18: ("TS-21", [_seeded("an own workflow that can be started with a prompt")]),
}
CMP2_ROW_LEVEL = {"TS-4": "e2e-ui", "TS-8": "e2e-ui", "TS-10": "api", "TS-12": "api",
                  "TS-14": "api", "TS-15": "api", "TS-13": "unit"}
CMP2_AUTOMATE = ("TS-4", "TS-8", "TS-10", "TS-12", "TS-14", "TS-15")
CMP2_EXTRA_KEYS = ["FRONTEND_URL", "NATS_URL", "PROJECT_NAME", "VERIFY_SSL", "CLEANUP_DATA",
                   "DEFAULT_TIMEOUT", "LANGFUSE_TRACES_ENABLED", "TEST_USER_FULL_NAME"]
CMP2_AWS = ["AWS_ACCESS_KEY", "AWS_SECRET_KEY", "AWS_PROFILE"]


def cmp2_case_id(n) -> str:
    return f"{CMP2_TICKET}_TC_{int(n):03d}"


def cmp2_config() -> dict:
    """The shape of the real config, reduced to what the gate reads; the pre-patch one, with no
    runtime probe, no recorded limit and the checks that would run a real command switched off."""
    def profile(profile_id, capability, tests, **extra):
        return dict({"profile_id": profile_id, "capabilities": [capability],
                     "roots": {"test": tests}, "reporter": {"kind": "pytest"},
                     "commands": {"one_test": {"argv": ["poetry", "run", "pytest", "<test-file>",
                                                        "--reruns", "2"], "cwd": "."}}}, **extra)
    return {
        "schema_version": 1, "tests_root": ".", "app_root": "../..",
        "case_id_form": "{ticket}_TC_{nnn}",
        "environment": {
            "env_file": "testproject1_test_harness/.env", "base_url_key": "TESTPROJECT1_API_DOMAIN",
            "user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"],
            "extra_keys": list(CMP2_EXTRA_KEYS),
            "integrations": [{"name": "aws-parameter-store", "keys": list(CMP2_AWS),
                              "owner": "user", "health_url": ""}]},
        "environments": [
            {"name": "localhost", "base_url": "http://localhost:8080",
             "credentials_by_role": {
                 "default_user": ".env: AUTH_USERNAME / AUTH_PASSWORD — the superadmin "
                                 "admin@testproject1.ai auto-created by SUPERADMIN_EMAIL/"
                                 "SUPERADMIN_PASSWORD in testproject1/.env (needs ENV != local and "
                                 "ENABLE_USER_MANAGEMENT=true)",
                 "project_scoped_user": "NOT provisioned locally",
                 "default_scoped_user": "NOT provisioned locally",
                 "auditor": "NOT provisioned locally"},
             "safe_to_break": True, "frontend_url": "http://localhost:5173",
             "verified": "2026-09-18: stack rebuilt from testproject1 82c81e41c and testproject1-ui 5084e1120",
             "limits": "Only one account exists, so role-matrix and auditor cases cannot run here"},
            {"name": "preview", "base_url": "https://preview.example.invalid/api",
             "credentials_by_role": {"default_user": ".env: AUTH_USERNAME / AUTH_PASSWORD"}}],
        "implementation_repos": [
            {"repo_id": "testproject1-backend", "role": "review", "local_path": "../../testproject1",
             "execution_profile_id": "api"},
            {"repo_id": "testproject1-ui", "role": "review", "local_path": "../../testproject1-ui",
             "execution_profile_id": "e2e-ui"}],
        "profiles": [profile("api", "api", "testproject1_test_harness/tests"),
                     profile("e2e-ui", "web", "testproject1_test_harness/tests/ui")],
        "gate_rehearsal": {"skip_collect": True, "skip_executor": True, "skip_reporter": True,
                           "skip_runtime_probe": True}}


def cmp2_story(prefix: str, *, rewritten: bool = True, base: bool = True, extra=(),
               config=None, pipeline=None, env_lines=None) -> Path:
    """The cmp2 story in a temp project. `rewritten` writes the cases as the designer now writes
    them (`case_seeds`, `stand_account`); False writes the lines of the real cmp2 files, prose
    `none` and all. `extra` is [(case number, plan row, [precondition dicts] or a raw line)] added
    beside the 18 cases (or instead of them with `base=False`); `config(dict)` edits the config."""
    root = temp_dir(prefix)
    task_root = root / "qa-factory" / "artifacts" / CMP2_TICKET
    cases_dir = task_root / "work" / "test-cases" / "workflow-visual-diff"
    cases_dir.mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    for folder in ("tests/ui", "tests/workflow"):
        (root / "testproject1_test_harness" / folder).mkdir(parents=True)
    cfg = cmp2_config()
    if config:
        config(cfg)
    (root / "qa-factory" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (root / "qa-factory" / "readiness.json").write_text(json.dumps(
        {"capabilities": {"environment": {"status": "ok"}, "test_repo": {"status": "ok"}}}),
        encoding="utf-8")
    lines = env_lines if env_lines is not None else (
        ["AUTH_USERNAME=admin@example.invalid", "AUTH_PASSWORD=not-printed-1"]
        + [f"{key}=x" for key in CMP2_EXTRA_KEYS])
    (root / "testproject1_test_harness" / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    pipe = {"ticket": CMP2_TICKET, "environment": "localhost",
            "stages": {"S3": {"status": "done"}, "S4": {"status": "done", "role": "qa-case-critic"}}}
    pipe.update(pipeline or {})
    (task_root / "pipeline.json").write_text(json.dumps(pipe), encoding="utf-8")
    cases = {n: spec for n, spec in CMP2_CASES.items()} if base else {}
    rows = {}
    for n, (row, items) in list(cases.items()) + [(n, (row, items)) for n, row, items in extra]:
        rows[row] = True
        if isinstance(items, str):
            line = items
        else:
            line = json.dumps([{k: v for k, v in dict(item, check=item["rewritten" if rewritten else "legacy"]).items()
                                if k not in ("legacy", "rewritten")} for item in items])
        front = ("---\n" f"id: {cmp2_case_id(n)}\ntitle: case {n}\narea: workflow-visual-diff\n"
                 f"task: {CMP2_TICKET}\n" + (f"preconditions: {line}\n" if items else "") + "---\n")
        body = (f"Requirements: R-{n}\nPlan row: {row}\n\n## Then\n1. the visible result holds.\n")
        (cases_dir / f"{cmp2_case_id(n)}.md").write_text(front + body, encoding="utf-8")
    plan = []
    for row in sorted(rows, key=lambda r: int(r.split("-")[1])):
        plan.append(plan_row(row, level=CMP2_ROW_LEVEL.get(row, "e2e-ui"),
                             disposition="automate" if row in CMP2_AUTOMATE else "manual-agent"))
    (task_root / "work" / "test-plan.json").write_text(json.dumps({"rows": plan}), encoding="utf-8")
    return root


def cmp2_run(root: Path, gate: str = "A", steps=None) -> dict:
    """The whole rehearsal (K-lines), or - with `steps=("case_preconditions", ...)` - only those
    steps of it, in the order given: a full gate costs ~2 s (`prepare`, the pins), and an edge
    case that is about one check does not need the other sixteen."""
    use_project(root)
    task = root / "qa-factory" / "artifacts" / CMP2_TICKET
    if steps is None:
        return gate_preflight.run(task, gate)
    r = gate_preflight.Rehearsal(task, gate)
    for name in steps:
        getattr(r, "check_" + name)()
    return {"findings": r.findings, "info": r.info, "stand_gaps": r.stand_gaps}


def cmp2_edit(root: Path, change) -> None:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    change(cfg)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def info_of(result: dict, name: str) -> list:
    return [row["message"] for row in result["info"] if row["check"] == name]


def test_k1_the_seeded_and_the_stands_own_account_are_not_questions() -> None:
    """TP1-15045, gate A: 16 `case_preconditions` cards, 14 of them the case's own business."""
    root = cmp2_story("qa-gate-k1-")
    try:
        result = cmp2_run(root)
        found = by_check(result, "case_preconditions")
        check_eq("K1: exactly two findings, TC_014 and TC_017", len(found), 2)
        check_in("TC_014 (two unmet variables) is one of them", cmp2_case_id(14), [f["message"] for f in found])
        check_in("TC_017 (the second user, preview only) is the other", cmp2_case_id(17),
                 [f["message"] for f in found if f["message"].startswith("preconditions no machine")])
        text = json.dumps(found)
        check_not_in("K1: nobody is told 'seeded by the case itself'", "seeded by the case itself", text)
        check_not_in("K1: nor 'the superadmin holds it'", "superadmin holds it", text)
        notes = info_of(result, "case_preconditions")
        check_eq("K1: one info line", len(notes), 1)
        check_in("K1: it counts what is not asked", "14 preconditions are not asked", notes[0])
        first = ", ".join(cmp2_case_id(n) for n in (1, 2, 3, 4, 6, 7))
        check_eq("K1: the line names six cases of each kind and counts the rest",
                 notes[0], f"14 preconditions are not asked: 11 the cases create themselves ({first} "
                           f"and 5 more), 3 are held by the stand's own account "
                           f"({', '.join(cmp2_case_id(n) for n in (10, 12, 15))}).")
        check_eq("K1: a question never stops the stage in front of the gate: none of these findings "
                 "is the factory's own to repair",
                 [f for f in found if f["class"] == gate_preflight.FACTORY_FIXABLE], [])
    finally:
        cleanup(root)


def test_k1_legacy_the_cmp2_lines_verbatim_make_two_findings() -> None:
    """F1b: a story written before the two kinds existed still stops once, not fifteen times."""
    root = cmp2_story("qa-gate-k1-legacy-", rewritten=False)
    try:
        result = cmp2_run(root)
        found = by_check(result, "case_preconditions")
        check_eq("K1-legacy: exactly two findings, TC_014 and ONE card of the prose `none`",
                 len(found), 2)
        card = [f for f in found if f["message"].startswith("preconditions no machine can check")]
        check_eq("one card carries every `none`", len(card), 1)
        check_eq("and it is the person's", card[0]["class"], gate_preflight.PERSON_DECIDES)
        check_eq("it names all fifteen cases", sorted(card[0]["cases"]),
                 sorted(cmp2_case_id(n) for n in CMP2_CASES if n not in (5, 13, 14)))
        check_in("it counts them", "15 preconditions of 15 cases", card[0]["message"])
        for reason in (CMP2_SEED_REASONS[1], CMP2_SEED_REASONS[9], "seeded by the case itself",
                       CMP2_SUPERADMIN, CMP2_NEEDS_PREVIEW):
            check_in(f"each reason is quoted as the designer wrote it: {reason[:30]}",
                     f'"{reason}"', card[0]["message"])
        check_in("the real need is named by its case", f'"{CMP2_NEEDS_PREVIEW}" ({cmp2_case_id(17)})',
                 card[0]["message"])
        check_eq("nothing is counted as not asked: no case said so", info_of(result, "case_preconditions"), [])
        check_in("a person's word passes it (FR-4), as a line they write (t-357)",
                 f"write `{card[0]['id']}: accept` with your reason", card[0]["fix"])
        check("t-357: and the word passes it", _word_passes(card[0]))
        pipe = root / "qa-factory" / "artifacts" / CMP2_TICKET / "pipeline.json"
        data = json.loads(pipe.read_text(encoding="utf-8"))
        data["stage_overrides"] = [{"stage": "S5", "match": "preconditions no machine can check",
                                    "decision": "the cases make their own data", "by": "human"}]
        pipe.write_text(json.dumps(data), encoding="utf-8")
        check_eq("and once passed it is not asked again",
                 len(by_check(cmp2_run(root, steps=("case_preconditions",)),
                              "case_preconditions")), 1)
    finally:
        cleanup(root)


def test_a_case_whose_items_are_all_seeded_asks_nothing_but_is_counted() -> None:
    root = cmp2_story("qa-gate-seeded-only-", base=False,
                      extra=[(1, "TS-1", [_seeded("data the case creates")])])
    try:
        result = cmp2_run(root, steps=("case_preconditions",))
        check_eq("no finding for the case", by_check(result, "case_preconditions"), [])
        check_eq("but it is counted: the case is in the info line",
                 info_of(result, "case_preconditions"),
                 [f"1 precondition is not asked: 1 the case creates itself ({cmp2_case_id(1)})."])
    finally:
        cleanup(root)


def test_seeded_items_never_make_an_unmet_one_met() -> None:
    """The invariant of the position: classification is per item, before the open split."""
    mixed = [_seeded("a workflow the case creates"),
             {"id": "PC-2", "kind": "env", "what": "the second account", "partitions": [],
              "legacy": {"env": "NOT_SET_ANYWHERE"}, "rewritten": {"env": "NOT_SET_ANYWHERE"}}]
    root = cmp2_story("qa-gate-seeded-mixed-", base=False, extra=[(1, "TS-1", mixed)])
    try:
        result = cmp2_run(root, steps=("case_preconditions",))
        found = by_check(result, "case_preconditions")
        check_eq("the unmet item is still a question", len(found), 1)
        check_in("it lists the unmet item", "the second account", found[0]["message"])
        check_not_in("and not the seeded one", "a workflow the case creates", found[0]["message"])
        check_in("the seeded one is still counted in the info line", "1 precondition is not asked",
                 info_of(result, "case_preconditions")[0])
        check_not_in("an item that is unmet never lands in the info line", "second account",
                     info_of(result, "case_preconditions")[0])
    finally:
        cleanup(root)


def test_a_stand_account_is_met_only_on_positive_evidence() -> None:
    """C2: the keys the role's own note names are set where the runner loads them, or it is a card."""
    def account(role):
        return [{"id": "PC-1", "kind": "account", "what": "an account of its own", "partitions": [],
                 "legacy": {"stand_account": role}, "rewritten": {"stand_account": role}}]

    def card_for(role, notes=None, env_lines=None) -> list:
        def edit(cfg):
            cfg["environments"][0]["credentials_by_role"].update(notes or {})
        root = cmp2_story("qa-gate-account-", base=False, extra=[(1, "TS-1", account(role))],
                          config=edit, env_lines=env_lines)
        try:
            return by_check(cmp2_run(root, steps=("case_preconditions",)), "case_preconditions")
        finally:
            cleanup(root)

    check_eq("the default user's note names two keys that are set: met, nothing asked",
             card_for("default_user"), [])
    absent = card_for("ghost_user")
    check_eq("a role the stand does not record is a card", len(absent), 1)
    check_in("and says the stand records no such account", "the stand records no such account",
             absent[0]["message"])
    for label, role, note in (("an empty note", "default_user", ""),
                              ("`NOT provisioned locally`", "auditor", "NOT provisioned locally"),
                              ("`missing locally`", "auditor", "missing locally"),
                              ("a note with no name in it", "auditor", "the admin account")):
        found = card_for(role, {role: note})
        check_eq(f"unmet, never met: {label}", len(found), 1)
        check_eq(f"and it is the person's: {label}", found[0]["class"], gate_preflight.PERSON_DECIDES)
    partial = card_for("default_user", {"default_user": ".env: AUTH_USERNAME / AUTH_PASSWORD_MISSING"})
    check_in("a key of the note that is not set is named, never its value", "AUTH_PASSWORD_MISSING",
             partial[0]["message"])
    check_not_in("and the key that is set is not", "AUTH_USERNAME is not", partial[0]["message"])
    check_eq("the note's prose after the names does not add keys the runner never reads",
             gate_preflight.account_keys(
                 ".env: AUTH_USERNAME / AUTH_PASSWORD — made by SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD"),
             ["AUTH_USERNAME", "AUTH_PASSWORD"])
    for note, keys in (("NOT provisioned locally", []), ("", []), (None, []), ("missing locally", []),
                       ("ENV != local", []), ("AUTH_USERNAME, AUTH_PASSWORD (admin)",
                                              ["AUTH_USERNAME", "AUTH_PASSWORD"]),
                       ("preview: .env: AUDITOR_USERNAME / AUDITOR_PASSWORD", ["AUDITOR_USERNAME", "AUDITOR_PASSWORD"]),
                       ("AUTH_USERNAME: admin", ["AUTH_USERNAME"])):
        check_eq(f"account_keys({note!r})", gate_preflight.account_keys(note), keys)


def test_a_stand_account_card_names_every_file_it_looked_in() -> None:
    """OH3-40: the card of a role whose keys are not found lists EVERY file of `environment.env_files` in order, and says
    `(not found)` after one the disk lacks; `_place_of` named only the first file that exists. Mutant: `_stand_account` back to
    `_target_of` -> this test. Also: the file the config lists is the file that is read (`met` from `.env.local`), a `how` that
    names no file keeps `the process environment`, and another text of the same packet may still name the first existing file."""
    item = [{"id": "PC-1", "kind": "account", "what": "an account of its own", "partitions": [],
             "legacy": {"stand_account": "default_user"}, "rewritten": {"stand_account": "default_user"}}]

    def listed(files):
        def edit(cfg):
            cfg["environment"].pop("env_file", None)
            cfg["environment"]["env_files"] = files
        return edit

    def card(files, local=None, env_lines=None):
        root = cmp2_story("qa-gate-looked-in-", base=False, extra=[(1, "TS-1", item)], config=listed(files), env_lines=env_lines)
        try:
            if local is not None:
                (root / "testproject1_test_harness" / ".env.local").write_text("\n".join(local) + "\n", encoding="utf-8")
            return by_check(cmp2_run(root, steps=("case_preconditions",)), "case_preconditions")
        finally:
            cleanup(root)

    keys = ["AUTH_USERNAME=local-user", "AUTH_PASSWORD=not-printed-2"]
    check_eq("keys in `.env.local`, which the config lists: met, nothing asked",
             card(["testproject1_test_harness/.env.local"], local=keys, env_lines=["OTHER=1"]), [])
    found = card(["testproject1_test_harness/.env.local"], env_lines=keys)
    check_eq("the listed file is missing (the keys sit in another file): a card", len(found), 1)
    check_in("it names the missing file", "`testproject1_test_harness/.env.local` (not found)", found[0]["message"])
    check_in("it says what is needed", "AUTH_USERNAME, AUTH_PASSWORD", found[0]["message"])
    both = card(["testproject1_test_harness/.env.local", "testproject1_test_harness/.env"], env_lines=["OTHER=1"])
    check_in("two files, the first missing, the second there without the keys: both named, in order, only the first marked",
             "(`testproject1_test_harness/.env.local` (not found), `testproject1_test_harness/.env`)", both[0]["message"])
    check_not_in("... and no value", "not-printed", both[0]["message"])


def test_no_selectable_stand_is_the_factorys_error_never_a_question() -> None:
    """Two stands, none chosen: `stand_account` cannot be looked up, which is not the person's."""
    items = [{"id": "PC-1", "kind": "account", "what": "an account", "partitions": [],
              "legacy": {"stand_account": "default_user"}, "rewritten": {"stand_account": "default_user"}}]
    root = cmp2_story("qa-gate-nostand-", base=False, extra=[(1, "TS-1", items)])
    try:
        pipe = root / "qa-factory" / "artifacts" / CMP2_TICKET / "pipeline.json"
        data = json.loads(pipe.read_text(encoding="utf-8"))
        del data["environment"]
        pipe.write_text(json.dumps(data), encoding="utf-8")
        result = cmp2_run(root, steps=("case_preconditions",))
        found = by_check(result, "case_preconditions")
        check_eq("one finding", len(found), 1)
        check_eq("and it is the factory's", found[0]["class"], gate_preflight.FACTORY_DEFECT)
        check_in("it says no stand is selectable", "no stand is selectable", found[0]["message"])
        check_eq("nothing is counted as held", info_of(result, "case_preconditions"), [])
    finally:
        cleanup(root)


def test_the_info_line_names_six_cases_and_counts_the_rest() -> None:
    """The limit the line introduces: AT 6 every id is named, BEYOND at 7 'and 1 more'."""
    seeded = lambda n: (cmp2_case_id(n), {"id": "PC-1"})  # noqa: E731
    six = gate_preflight.not_asked_line([seeded(n) for n in range(1, 7)], [])
    seven = gate_preflight.not_asked_line([seeded(n) for n in range(1, 8)], [])
    check_in("at six the sixth case is named", cmp2_case_id(6), six)
    check_not_in("and nothing is counted", " more", six)
    check_not_in("at seven the seventh is not named", cmp2_case_id(7), seven)
    check_in("it is counted instead", "TC_006 and 1 more)", seven)
    check_eq("one item reads in the singular",
             gate_preflight.not_asked_line([seeded(1)], []),
             f"1 precondition is not asked: 1 the case creates itself ({cmp2_case_id(1)}).")
    check_eq("two cases with one item each read in the plural",
             gate_preflight.not_asked_line([], [seeded(1), seeded(2)]),
             f"2 preconditions are not asked: 2 are held by the stand's own account "
             f"({cmp2_case_id(1)}, {cmp2_case_id(2)}).")
    check_eq("named_ids deduplicates", gate_preflight.named_ids(["a", "a", "b"]), "a, b")


def test_k2_integration_keys_and_accounts_are_asked_only_when_the_story_names_them() -> None:
    """cmp2: AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_PROFILE and three accounts were put to the person
    for a story whose cases touch neither."""
    root = cmp2_story("qa-gate-k2-")
    try:
        result = cmp2_run(root)
        check_eq("K2: no s5_environment finding", by_check(result, "s5_environment"), [])
        text = json.dumps(result["findings"])
        check_not_in("K2: the AWS keys are not asked", "AWS_ACCESS_KEY", text)
        check_not_in("K2: nor an account", "project_scoped_user", text)
        check_eq("FR-41: what was left out is said, in env_probe's own words",
                 [m for m in info_of(result, "s5_environment")],
                 ["keys of aws-parameter-store not asked: an integration that does not say "
                  "which area needs it"])
        cmp2_edit(root, lambda c: c["environment"]["integrations"][0].__setitem__("required_by", ["api"]))
        result = cmp2_run(root, steps=("s5_credentials",))
        # HF1-9 (old -> new): one `s5_environment` finding "...which api use: <keys>" -> the api cases are TIED to the
        # integration, so each api case gets its own stand-gap card (four automate api rows: TS-10, 12, 14, 15) and the
        # keys leave `s5_environment` (FR-10: one statement of each fact)
        check_eq("K2 variant `required_by: [api]`: no s5_environment finding any more", by_check(result, "s5_environment"), [])
        found = by_check(result, "s5_integrations")
        check_eq("one pointer per api case", len(found), 4)
        # OH3-8 (old -> new): the pointer named the keys -> it speaks of access; the keys are on the cards' fix line
        fixes = " ".join(row["remedy"]["change"] for row in result["stand_gaps"])
        for key in CMP2_AWS:
            check_in(f"the cards' fix names {key}", key, fixes)
        check_in("and who needs them, in the project's own words", "\"api\" needs it", found[0]["message"])
        check_eq("the cards are the api cases'", sorted(row["case"] for row in result["stand_gaps"]),
                 sorted(cmp2_case_id(n) for n in (10, 12, 14, 15)))
        check_eq("and nothing is left out then", info_of(result, "s5_environment"), [])
    finally:
        cleanup(root)


def test_the_integration_scope_follows_env_probes_order_and_errs_toward_a_card() -> None:
    """C6: `not_required` and `environments` apply first; names this story does not hold still ask."""
    def asked(change, **kw) -> tuple:
        def edit(cfg):
            change(cfg["environment"])
        root = cmp2_story("qa-gate-k2-scope-", config=edit, **kw)
        try:
            result = cmp2_run(root, steps=("s5_credentials",))
            # HF1-9: what an integration asks is `s5_integrations`'; `s5_environment` keeps the login keys
            return (by_check(result, "s5_integrations"), info_of(result, "s5_environment"),
                    by_check(result, "s5_environment"))
        finally:
            cleanup(root)

    def integ(**fields):
        return lambda env: env["integrations"][0].update(fields)

    found, _, _ = asked(integ(required_by=["role-matrix-area"]))
    # HF8-11 (old -> new): one question for the whole story -> a required_by that holds no id of this story or the project is
    # the project's own words: ONE line of the brief, no question (the line itself is pinned in the integrations test)
    check_eq("a required_by of names that are not this story's ids is a line, not a question", len(found), 0)
    # old -> new: one finding whatever `required_by` named -> a name the story holds ties its cases (one card each),
    # a name it does not hold is a line for the whole story (HF8-11; was one question)
    for name, given, expected in (("a plan row id", ["TS-10"], 1), ("an obligation id the plan does not hold", ["OB-12"], 0),
                                  ("the profile of an automate row", ["e2e-ui"], 2)):
        check_eq(f"findings raised when required_by names {name}",
                 len(asked(integ(required_by=given))[0]), expected)
    found, _, _ = asked(integ(applicability="required"))
    check_eq("`applicability: required` is asked", len(found), 1)
    check_in("without inventing a row that uses it", "the project does not say which tests use it", found[0]["message"])
    found, notes, _ = asked(integ(applicability="not_required", required_by=["api"]))
    check_eq("`not_required` wins over a required_by: it applies first", found, [])
    check_in("and says why, in env_probe's words", "outside selected scope", notes[0])
    found, notes, _ = asked(integ(environments=["preview"], required_by=["api"]))
    check_eq("an integration scoped to another stand is not asked on this one", found, [])
    check_in("and says so", "outside selected scope", notes[0])
    check_eq("scoped to this stand it is asked (the four api cases)",
             len(asked(integ(environments=["localhost"], required_by=["api"]))[0]), 4)

    def login_key(env):
        env["integrations"][0]["keys"] = ["AUTH_PASSWORD", "AWS_ACCESS_KEY"]
    found, _, env_found = asked(login_key, env_lines=["AUTH_USERNAME=a"] + [f"{k}=x" for k in CMP2_EXTRA_KEYS])
    check_eq("a key that is also a login key stays in the login question", len(env_found), 1)
    check_in("the login key is named", "AUTH_PASSWORD", env_found[0]["message"])
    check_not_in("while the integration's own key is not asked", "AWS_ACCESS_KEY", env_found[0]["message"])

    def case_names_it(env):
        env["integrations"][0].update(required_by=["api"], keys=["TC014_READONLY_USER_TOKEN"])
    found, _, env_found = asked(case_names_it)
    check_eq("a key a case names through check.env is case_preconditions' to ask, once (FR-10)",
             (found, env_found), ([], []))


def test_an_integration_the_config_writes_badly_is_ignored_not_a_crash() -> None:
    for label, junk in (("absent", None), ("empty", []),
                        ("an entry that is not an object", ["aws", 3]),
                        ("keys that is not a list", [{"name": "x", "keys": "AWS_ACCESS_KEY",
                                                      "required_by": ["api"]}]),
                        ("keys with a non-string in them", [{"name": "x", "keys": [None, 3, ""],
                                                             "required_by": ["api"]}])):
        def edit(cfg, junk=junk):
            if junk is None:
                cfg["environment"].pop("integrations")
            else:
                cfg["environment"]["integrations"] = junk
        root = cmp2_story("qa-gate-k2-junk-", config=edit)
        try:
            result = cmp2_run(root, steps=("s5_credentials",))
            check_eq(f"{label}: no finding and no 'step unavailable'", by_check(result, "s5_environment"), [])
        finally:
            cleanup(root)


def test_a_case_that_cannot_be_read_keeps_every_integration_key_wanted() -> None:
    """The needs of the story are unknown, and unknown is never read as `needs nothing`."""
    broken = [(1, "TS-1", '[{"id": "PC-1", "kind": "toggle"}]')]
    root = cmp2_story("qa-gate-k2-broken-", extra=broken)
    try:
        # the extra case is written with a precondition line the validator refuses
        result = cmp2_run(root, steps=("s5_credentials",))
        # HF1-9 (old -> new): the keys were in the `s5_environment` finding; they are now ONE `s5_integrations` question
        # (no case can be tied to the integration while the cases cannot be read), and `s5_environment` holds only login keys
        check_eq("nothing in the login question", by_check(result, "s5_environment"), [])
        found = by_check(result, "s5_integrations")
        check_eq("one finding", len(found), 1)
        for key in CMP2_AWS:
            # OH3-8 (old -> new): in the message -> in the first move of the fix
            check_in(f"{key} is asked again", key, found[0]["fix"])
        check_eq("with nothing said to be left out", info_of(result, "s5_environment"), [])
    finally:
        cleanup(root)


def test_the_story_ids_integrations_are_scoped_by() -> None:
    """C6: the obligation ids come from the plan rows' `coverage_obligations[].obligation_id`."""
    root = cmp2_story("qa-gate-story-ids-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        plan = json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))
        for row in plan["rows"]:
            row["coverage_obligations"] = [{"obligation_id": "OB-" + row["id"].split("-")[1]}]
        (task / "work" / "test-plan.json").write_text(json.dumps(plan), encoding="utf-8")
        ids = gate_preflight.Rehearsal(task, "A")._story_ids()
        check_eq("the profiles of its automate rows", ids["profiles"], ["api", "e2e-ui"])
        check_in("its plan rows", "TS-10", ids["rows"])
        check_in("and the obligations of those rows", "OB-12", ids["obligations"])
        def edit(cfg):
            cfg["environment"]["integrations"][0]["required_by"] = ["OB-12", "never-heard-of"]
        cmp2_edit(root, edit)
        result = cmp2_run(root, steps=("s5_credentials",))
        # HF1-9 (old -> new): "...which OB-12 use" in one finding -> the obligation ties its row's case (TS-12), whose card
        # is the only one raised; the name the story does not hold ties nothing (equality only)
        check_eq("an obligation of the story ties the case of its row, and no other",
                 [row["case"] for row in result["stand_gaps"]], [cmp2_case_id(12)])
        check_eq("one pointer, the case's", [f["check"] for f in result["findings"]], ["s5_integrations"])
    finally:
        cleanup(root)


def test_f3a_an_e2e_row_is_keyed_to_the_profile_named_as_its_level() -> None:
    root = cmp2_story("qa-gate-f3a-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        keyed = gate_preflight.s5_profiles(cfg, task)
        check_eq("the e2e rows are keyed to e2e-ui", keyed["e2e-ui"]["cases"],
                 [cmp2_case_id(4), cmp2_case_id(8)])
        check_in("by the new step, said in its own words", "equals the profile id", keyed["e2e-ui"]["keyed_on"])
        check_eq("the api rows are keyed by the capability fit, as before", keyed["api"]["cases"],
                 [cmp2_case_id(n) for n in (10, 12, 14, 15)])
        check_in("on the capability", "capabilities", keyed["api"]["keyed_on"])
        # C5: a capability fit still wins over an equal id
        both = dict(cfg, profiles=[{"profile_id": "ui-a", "capabilities": ["e2e-ui"]},
                                   {"profile_id": "e2e-ui", "capabilities": ["web"]},
                                   {"profile_id": "api", "capabilities": ["api"]}])
        won = gate_preflight.s5_profiles(both, task)
        check_eq("a capability fit wins over a profile whose id equals the level",
                 sorted(won), ["api", "ui-a"])
        # ... and the id step comes BEFORE the single-profile fallback
        two = dict(cfg, profiles=[{"profile_id": "e2e-ui", "capabilities": ["web"]},
                                  {"profile_id": "other", "capabilities": ["web"]}])
        check_eq("two profiles that fit nothing: the one whose id is the level; the api rows, "
                 "which fit no profile, are left out",
                 sorted(gate_preflight.s5_profiles(two, task)), ["e2e-ui"])
        one = dict(cfg, profiles=[{"profile_id": "solo", "capabilities": ["web"]}])
        check_eq("one profile, no fit: the single-profile fallback still applies",
                 sorted(gate_preflight.s5_profiles(one, task)), ["solo"])
        three = dict(cfg, profiles=[{"profile_id": "x", "capabilities": ["web"]},
                                    {"profile_id": "y", "capabilities": ["web"]}])
        check_eq("two profiles and none fits or is named: nothing is keyed (a wrong question is "
                 "worse than none)", gate_preflight.s5_profiles(three, task), {})
    finally:
        cleanup(root)


def test_ep1_41f_a_device_level_is_keyed_by_the_fits_levels_of_its_surface() -> None:
    """EP1-41f: after the capability fit and the id fit, before the single-profile fallback, the plan level is told by the
    `fits_levels` of a surface row to the ONE profile that holds that surface's capability. Two such profiles key nothing;
    a web or API project never reads the table (0 reads, a broken table changes nothing); a broken table in a project that
    needs it leaves the cases unkeyed (asked about), never a crash."""
    import surfaces
    root = cmp2_story("qa-gate-41f-")
    real_rows, reads = surfaces.rows, {"n": 0}
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        web, api = {"profile_id": "web-suite", "capabilities": ["web"]}, {"profile_id": "api", "capabilities": ["api"]}
        phone = {"profile_id": "phone", "capabilities": ["native"]}
        surfaces.rows = lambda: (reads.__setitem__("n", reads["n"] + 1), real_rows())[1]
        for name, profiles, expect_ui in (
                ("web + api: the level fits nothing, the table is not read", [web, api], []),
                ("web + api + one native: the device profile takes the e2e-ui rows", [web, api, phone], ["phone"]),
                ("two native profiles: the fit is not unique, nothing is keyed", [web, api, phone, dict(phone, profile_id="tablet")], [])):
            reads["n"] = 0
            keyed = gate_preflight.s5_profiles(dict(cfg, profiles=profiles), task)
            got = sorted(p for p, v in keyed.items() if cmp2_case_id(4) in v["cases"])
            check_eq(f"41f: {name}", got, expect_ui)
            if expect_ui:
                check_in("41f: said in its own words", "fits a test surface", keyed["phone"]["keyed_on"])
                check_eq("41f: the api rows are keyed by their capability as before", keyed["api"]["cases"],
                         [cmp2_case_id(n) for n in (10, 12, 14, 15)])
            if not expect_ui and len(profiles) == 2:
                check_eq("41f: a web + API project reads the table 0 times", reads["n"], 0)
        # the id step still beats the surface step
        named = dict(cfg, profiles=[{"profile_id": "e2e-ui", "capabilities": ["web"]}, phone])
        check_eq("41f: a profile whose id is the level wins over the surface fit",
                 [p for p, v in gate_preflight.s5_profiles(named, task).items() if cmp2_case_id(4) in v["cases"]], ["e2e-ui"])
        # a broken table: the web project is untouched, the device project asks
        def broken():
            raise ValueError("table broken")
        surfaces.rows = broken
        check_eq("41f: a broken table leaves a web + API project as it was", sorted(gate_preflight.s5_profiles(dict(cfg, profiles=[web, api]), task)), ["api"])
        check_eq("41f: a broken table leaves the device level unkeyed, no crash",
                 [p for p, v in gate_preflight.s5_profiles(dict(cfg, profiles=[web, api, phone]), task).items() if cmp2_case_id(4) in v["cases"]], [])
    finally:
        surfaces.rows = real_rows
        cleanup(root)


def test_the_executor_question_now_reaches_the_e2e_profile() -> None:
    """The first of the users of `s5_profiles`: the e2e rows used to be keyed to nothing."""
    def edit(cfg):
        cfg["gate_rehearsal"].pop("skip_executor")
        for profile in cfg["profiles"]:
            profile["commands"]["one_test"]["argv"] = ["a-launcher-nobody-installed-t218", "<test-file>"]
    root = cmp2_story("qa-gate-f3a-executor-", config=edit)
    try:
        found = by_check(cmp2_run(root, steps=("s5_executor",)), "s5_executor")
        by_profile = {f["profile"]: f for f in found}
        check_eq("one question per profile, e2e-ui among them", sorted(by_profile), ["api", "e2e-ui"])
        check_eq("with the e2e cases on it", by_profile["e2e-ui"]["cases"],
                 [cmp2_case_id(4), cmp2_case_id(8)])
    finally:
        cleanup(root)


# --- §5: the page objects wait less than the stand takes to load a page ----------------------------

def with_limits(load=110, wait=30, **extra):
    """A config edit recording the 01.10 measurement of cmp2 and the page objects' wait."""
    def edit(cfg):
        measured = dict({"value": load, "route": "/workflows/<id>/edit",
                         "command": "browser, signed in, a full load", "at": "2026-10-01"}, **extra)
        if load is not None:
            cfg["environments"][0]["measured"] = {"e2e_page_load_s": measured}
        if wait is not None:
            cfg["profiles"][1]["page_object_max_wait_s"] = wait
    return edit


def limit_cards(root) -> list:
    return by_check(cmp2_run(root, steps=("s5_stand_limits",)), "e2e_stand_limit")


def test_k5_a_page_that_loads_slower_than_the_page_objects_wait_is_one_card() -> None:
    root = cmp2_story("qa-gate-k5-", config=with_limits(110, 30))
    try:
        result = cmp2_run(root)
        cards = by_check(result, "e2e_stand_limit")
        check_eq("K5: load 110 against wait 30 is exactly one card", len(cards), 1)
        card = cards[0]
        check_eq("it is the person's", card["class"], gate_preflight.PERSON_DECIDES)
        check_eq("it lists the e2e cases", card["cases"], [cmp2_case_id(4), cmp2_case_id(8)])
        check_not_in("the api cases are not on it", cmp2_case_id(10), card["message"])
        for needle in ("110 s", "30 s", "/workflows/<id>/edit", "localhost", cmp2_case_id(4), cmp2_case_id(8)):
            check_in(f"the message says {needle}", needle, card["message"])
        # C7 + 0d C2: every option has an executor, named in the card (FR-9); the third door,
        # accept-as-blocked, was dropped because nothing outside this file reads its block
        check_in("(a) the handed door is a line the person writes - the word of the data file for `handed` (t-357)",
                 f"to run it yourself, write `{card['id']}: run`", card["fix"])
        check_eq("(a) and the block it passes travels as data, unprinted: the handed block, at S5, option handed",
                 card["waives"], [{"block": "executor unavailable: e2e-ui", "stage": "S5", "option": "handed"}])
        for banned in ("waiver.py", "--block", "--stage", "--decision", "executor unavailable"):
            check_not_in(f"t-357: the card shows no {banned!r}", banned, card["fix"])
        check_in("(a) names where the person runs them, with the stand that loads in time",
                 "on another stand where the page loads in time", card["fix"])
        check_in("(b) the gate-A answer form", "`<case id>: manual`", card["fix"])
        check_in("the card says it offers two", "one of two", card["fix"])
        check_not_in("C2: no option is a waiver on the stand limit - nothing reads that block (FR-9)",
                     "e2e stand limit", json.dumps(card["waives"]))
        check_not_in("nor a third answer of any wording", "(c)", card["fix"])
        check_eq("the options travel machine-readable: the two doors that remain",
                 [o["id"] for o in card["options"]], ["a", "b"])
        check_eq("(a) is the handed_to_person action contract.py already reads",
                 card["options"][0]["action"], "handed_to_person")
        check("the message still opens with the block text an older waiver is matched against (FR-4)",
              card["message"].startswith("e2e stand limit: e2e-ui"))
        check_eq("an api profile is never carded", [f for f in cards if f.get("profile") == "api"], [])
        check_eq("nothing about a measured limit is left as info when it is a card",
                 [m for m in info_of(result, "e2e_stand_limit")], [])
    finally:
        cleanup(root)


def test_k5_strict_greater_than_at_and_beyond_the_wait() -> None:
    for load, expected in ((29, 0), (30, 0), (30.5, 1), (31, 1)):
        root = cmp2_story("qa-gate-k5-edge-", config=with_limits(load, 30))
        try:
            check_eq(f"K5: load {load} against wait 30 -> {expected} card(s)", len(limit_cards(root)), expected)
        finally:
            cleanup(root)


def test_k5_nothing_recorded_is_not_measured_and_never_a_card() -> None:
    root = cmp2_story("qa-gate-k5-none-")
    try:
        result = cmp2_run(root, steps=("s5_stand_limits",))
        check_eq("K5: no card", by_check(result, "e2e_stand_limit"), [])
        notes = info_of(result, "e2e_stand_limit")
        check_eq("K5: one info line", len(notes), 1)
        check_in("it says not measured", "is not measured", notes[0])
        check_in("and for which profile, on which stand", "`e2e-ui`: e2e page load on localhost", notes[0])
    finally:
        cleanup(root)
    root = cmp2_story("qa-gate-k5-none-words-")
    try:
        notes = info_of(cmp2_run(root, steps=("s5_stand_limits",)), "e2e_stand_limit")
        check_not_in("C3: the line says no field path (`measured`, `[]`)", "e2e_page_load_s", notes[0])
        check_not_in("nor a bracket", "[]", notes[0])
    finally:
        cleanup(root)
    for label, edit, needle in (
            ("a wait recorded, no load", with_limits(None, 30), "page load is not recorded"),
            ("a load recorded, no wait", with_limits(110, None), "wait is not recorded")):
        root = cmp2_story("qa-gate-k5-half-", config=edit)
        try:
            result = cmp2_run(root, steps=("s5_stand_limits",))
            check_eq(f"{label}: no card", by_check(result, "e2e_stand_limit"), [])
            check_in(f"{label}: an info line says what is missing", needle,
                     info_of(result, "e2e_stand_limit")[0])
        finally:
            cleanup(root)


def test_k5_a_limit_that_cannot_be_read_is_one_defect_and_no_card() -> None:
    bad = (("a string", "110"), ("zero", 0), ("a negative", -3), ("a bool", True), ("false", False),
           ("a list", [110]), ("NaN", float("nan")))
    for label, value in bad:
        root = cmp2_story("qa-gate-k5-bad-", config=with_limits(value, 30))
        try:
            cards = limit_cards(root)
            check_eq(f"{label} as the load: one finding", len(cards), 1)
            check_eq(f"{label}: and it is the factory's, not a card", cards[0]["class"],
                     gate_preflight.FACTORY_DEFECT)
            check_in(f"{label}: it says so", "the recorded limit cannot be read", cards[0]["message"])
        finally:
            cleanup(root)
    for label, wait in (("a bool", True), ("zero", 0), ("a string", "30")):
        root = cmp2_story("qa-gate-k5-badwait-", config=with_limits(110, wait))
        try:
            cards = limit_cards(root)
            check_eq(f"{label} as the wait: one defect", [c["class"] for c in cards],
                     [gate_preflight.FACTORY_DEFECT])
            check_in(f"{label}: saying which limit, in words", "the wait of the page objects",
                     cards[0]["message"])
            check_not_in(f"{label}: and no field path in the sentence (C3)", "page_object_max_wait_s",
                         cards[0]["message"])
            check_in(f"{label}: the field is in the fix, where the person is told where to write",
                     "page_object_max_wait_s", cards[0]["fix"])
        finally:
            cleanup(root)


def test_a_measurement_older_than_the_stand_is_not_a_measurement() -> None:
    """C7: `at` before the stand's `verified` date (2026-09-18) describes another build."""
    root = cmp2_story("qa-gate-k5-stale-", config=with_limits(110, 30, at="2026-09-17"))
    try:
        result = cmp2_run(root, steps=("s5_stand_limits",))
        check_eq("no card", by_check(result, "e2e_stand_limit"), [])
        check_in("the info line says why", "older than the stand's last verification",
                 info_of(result, "e2e_stand_limit")[0])
    finally:
        cleanup(root)
    for at, cards in (("2026-09-18", 1), ("2026-10-01T09:00:00", 1), ("no date at all", 1)):
        root = cmp2_story("qa-gate-k5-fresh-", config=with_limits(110, 30, at=at))
        try:
            check_eq(f"`at` {at!r} is not older than the stand: the limit stands", len(limit_cards(root)), cards)
        finally:
            cleanup(root)


def test_the_other_stand_is_named_only_when_its_own_load_fits() -> None:
    def edit(load_elsewhere):
        def apply(cfg):
            with_limits(110, 30)(cfg)
            cfg["environments"][1]["measured"] = {"e2e_page_load_s": {
                "value": load_elsewhere, "route": "/", "command": "browser", "at": "2026-10-01"}}
        return apply
    for load, needle in ((30, "on preview"), (31, "on another stand where the page loads in time")):
        root = cmp2_story("qa-gate-k5-other-", config=edit(load))
        try:
            check_in(f"another stand at {load} s -> {needle}", needle, limit_cards(root)[0]["fix"])
        finally:
            cleanup(root)


def test_a_card_a_person_has_answered_is_closed_in_all_the_ways_it_can_still_be() -> None:
    """The card offers two doors (C2). The block text of the third, dropped one is still honoured
    when an older waiver file holds it: `add()` keeps passing it (FR-4), only the OPTION is gone."""
    root = cmp2_story("qa-gate-k5-answers-", config=with_limits(110, 30))
    task = root / "qa-factory" / "artifacts" / CMP2_TICKET
    try:
        check_eq("control: the card stands", len(limit_cards(root)), 1)
        pipe = task / "pipeline.json"
        original = pipe.read_text(encoding="utf-8")
        for label, match in (("(a) the handed door", "executor unavailable: e2e-ui"),
                             ("an older waiver on the dropped third door", "e2e stand limit: e2e-ui")):
            data = json.loads(original)
            data["stage_overrides"] = [{"stage": "S5", "match": match, "decision": "my word", "by": "human"}]
            pipe.write_text(json.dumps(data), encoding="utf-8")
            check_eq(f"{label}: not asked again", by_check(cmp2_run(root, steps=("s5_stand_limits",)), "e2e_stand_limit"), [])
        pipe.write_text(original, encoding="utf-8")
        # (b) `<case id>: manual` moves the rows off `automate`: nothing is left to run on the stand
        plan = json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))
        for row in plan["rows"]:
            if row["id"] in ("TS-4", "TS-8"):
                row["disposition"] = "manual-agent"
        (task / "work" / "test-plan.json").write_text(json.dumps(plan), encoding="utf-8")
        result = cmp2_run(root, steps=("s5_stand_limits",))
        check_eq("(b) the cases moved to a check by an agent: no card", by_check(result, "e2e_stand_limit"), [])
        check_eq("and no e2e rows, so nothing is said about a measurement either",
                 info_of(result, "e2e_stand_limit"), [])
    finally:
        cleanup(root)


def test_the_stand_limit_step_can_be_switched_off() -> None:
    def edit(cfg):
        with_limits(110, 30)(cfg)
        cfg["gate_rehearsal"]["skip_stand_limits"] = True
    root = cmp2_story("qa-gate-k5-off-", config=edit)
    try:
        result = cmp2_run(root, steps=("s5_stand_limits",))
        check_eq("no card", by_check(result, "e2e_stand_limit"), [])
        check_eq("and no line", info_of(result, "e2e_stand_limit"), [])
    finally:
        cleanup(root)


# --- C5: the reporter step and the e2e limit ---------------------------------------------------------

# A stand-in for the project's pytest: a script NAMED `pytest` (so the profile's command is
# pytest-shaped and the gate picks the test from its own collect), which records the node id it
# was handed and writes the JUnit report the rehearsal reads.
REPORT_RUNNER = """import sys
from pathlib import Path
chosen = sys.argv[2]
with Path(__file__).with_name("launches.log").open("a") as _f:
    _f.write(chosen + chr(10))
Path(sys.argv[1].split("=", 1)[1]).write_text(
    '<?xml version="1.0"?><testsuite name="s" tests="1" failures="0" errors="0" skipped="0" '
    'time="0.1"><testcase classname="c" name="' + chosen + '"/></testsuite>', encoding="utf-8")
"""
COLLECT = ("testproject1_test_harness/tests/workflow/test_a_first.py::test_one\n"
           "testproject1_test_harness/tests/ui/test_b_page.py::test_two\n\n2 tests collected\n")


def reporter_story(prefix: str, limits=None) -> Path:
    root = cmp2_story(prefix)
    runner = root / "pytest"
    runner.write_text(REPORT_RUNNER, encoding="utf-8")

    def edit(cfg):
        cfg["gate_rehearsal"].pop("skip_reporter")
        for profile in cfg["profiles"]:
            profile["commands"]["one_test"]["argv"] = [sys.executable, str(runner), "--junitxml={report_path}"]
        if limits:
            limits(cfg)
    cmp2_edit(root, edit)
    return root


def launches_of(root: Path) -> list:
    log = root / "launches.log"
    return log.read_text(encoding="utf-8").split() if log.is_file() else []


def test_the_reporter_proves_a_profile_with_one_of_its_own_tests() -> None:
    root = reporter_story("qa-gate-c5-own-")
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / CMP2_TICKET, "A")
        r.collect_stdout = COLLECT
        r.check_s5_reporter()
        check_eq("each profile ran exactly one test, the e2e profile's from under its own root and "
                 "not the project's first node",
                 sorted(launches_of(root)),
                 sorted(["testproject1_test_harness/tests/workflow/test_a_first.py::test_one",
                         "testproject1_test_harness/tests/ui/test_b_page.py::test_two"]))
        check_eq("and the rehearsal found no card", r.findings, [])
    finally:
        cleanup(root)
    check_eq("`under` narrows the collect to a directory",
             gate_preflight.first_collected_node(COLLECT, "testproject1_test_harness/tests/ui"),
             "testproject1_test_harness/tests/ui/test_b_page.py::test_two")
    check_eq("a directory nothing was collected under is empty, never the project's first node",
             gate_preflight.first_collected_node(COLLECT, "testproject1_test_harness/tests/other"), "")
    check_eq("a sibling directory with the same beginning is not below it",
             gate_preflight.first_collected_node(COLLECT, "testproject1_test_harness/tests/u"), "")
    check_eq("no directory is the first node, as before", gate_preflight.first_collected_node(COLLECT),
             "testproject1_test_harness/tests/workflow/test_a_first.py::test_one")


def test_the_reporter_skips_a_profile_whose_e2e_limit_card_is_open() -> None:
    root = reporter_story("qa-gate-c5-skip-", with_limits(110, 30))
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / CMP2_TICKET, "A")
        r.collect_stdout = COLLECT
        r.check_s5_reporter()
        check_eq("only the api profile ran a test", launches_of(root),
                 ["testproject1_test_harness/tests/workflow/test_a_first.py::test_one"])
        check_in("and the skip is said, not silent (FR-41)", "`e2e-ui`: one test was not run",
                 [row["message"] for row in r.info])
    finally:
        cleanup(root)
    root = reporter_story("qa-gate-c5-fits-", with_limits(30, 30))
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / CMP2_TICKET, "A")
        r.collect_stdout = COLLECT
        r.check_s5_reporter()
        check_eq("a load that fits the wait is rehearsed", len(launches_of(root)), 2)
    finally:
        cleanup(root)


# --- §3: the stand's runtime probe is derived and checked at the gate ---------------------------------

class stub_stand:
    """What docker and the probe would say. Nothing here starts either: `runtime_probe.containers`,
    `.content_candidates` and `gate_preflight.run_probe` are replaced, and every call is recorded."""

    def __init__(self, containers=(("api-c", "img"), ("ui-c", "img")), candidates=None, probe=None,
                 compared=("src/a.py",)):
        self.containers = list(containers)
        self.candidates = candidates or (lambda profile_checkout: [self.containers[0][0]])
        self.probe = probe or (lambda argv: {"record": {"result": "matched", "comparisons": [
            {"file": "src/a.py", "container_sha256": "x", "local_sha256": "x"}]}})
        # The files of the story the checkout holds. The cmp2 fixture has no checkouts on disk, so
        # by default this says one file is there; `compared=None` leaves the real filesystem
        # question in place (the C4 tests are about exactly that).
        self.compared = compared
        self.probe_calls, self.candidate_calls, self.docker_calls = [], [], []
        self.candidate_cfgs = []

    def __enter__(self):
        import runtime_probe
        self.rp, self.held = runtime_probe, (runtime_probe.containers, runtime_probe.content_candidates,
                                             gate_preflight.run_probe, runtime_probe.compared_files)
        self.rp.containers = lambda timeout=20: self.docker_calls.append("docker ps") or list(self.containers)

        def candidates(files, checkout, app_root, running, timeout=20, cfg=None):
            self.candidate_calls.append((str(checkout), app_root))
            self.candidate_cfgs.append(cfg)
            return self.candidates(Path(str(checkout)).name)
        self.rp.content_candidates = candidates
        if self.compared is not None:
            self.rp.compared_files = lambda files, checkout: list(self.compared)

        def run_probe(argv, cwd, timeout):
            self.probe_calls.append((list(argv), str(cwd), timeout))
            return self.probe(list(argv))
        gate_preflight.run_probe = run_probe
        return self

    def __exit__(self, *exc):
        self.rp.containers, self.rp.content_candidates = self.held[0], self.held[1]
        gate_preflight.run_probe, self.rp.compared_files = self.held[2], self.held[3]


def probes_on(cfg):
    cfg["gate_rehearsal"].pop("skip_runtime_probe")


def argv_text(argv: list) -> str:
    return " ".join(str(a) for a in argv)


def test_k3_a_stand_that_matches_is_derived_and_shown_with_its_argv() -> None:
    """The first typed run of cmp2 was refused for want of a probe, twice, in S5. The derived probe is
    the factory's own repair: a `factory_fixable` finding that carries the write argv as a LIST in
    its `argv` field (t-261, t-279 K-FLIP; the driver's `GATE_REPAIRS` row `s5_runtime_probe` runs it)."""
    root = cmp2_story("qa-gate-k3-", config=probes_on)
    cfg_path = root / "qa-factory" / "config.json"
    before = cfg_path.read_bytes()
    try:
        by_checkout = {"testproject1": ["api-c"], "testproject1-ui": ["ui-c"]}   # the folder's name, however cased
        with stub_stand(candidates=lambda name: by_checkout[name.lower()]) as stand:
            result = cmp2_run(root)
        check_eq("K-FLIP: no info line of the derived probe - it is a finding now",
                 [row for row in result["info"] if row["check"] == "s5_runtime_probe"], [])
        notes = by_check(result, "s5_runtime_probe")
        check_eq("K-FLIP: one finding per profile", sorted(n["profile"] for n in notes), ["api", "e2e-ui"])
        check_eq("K-FLIP: and every one is `factory_fixable`",
                 sorted({n["class"] for n in notes}), [gate_preflight.FACTORY_FIXABLE])
        api = [n for n in notes if n["profile"] == "api"][0]
        argv = api["argv"]
        check_eq("the argv is the exact write command, carrying the story's folder",
                 argv[2:], ["--suggest", "--write", "--profile", "api", "--environment", "localhost",
                            "--container", "api-c", "--checkout", "../../testproject1", "--app-root", "/app",
                            "--task-root", str((root / "qa-factory" / "artifacts" / CMP2_TICKET).resolve())])
        check_eq("K-FLIP: the argv is a LIST of strings in the field, head tokens portable",
                 (type(argv).__name__, argv[:2]), ("list", ["{python}", "{plugin_root}/scripts/runtime_probe.py"]))
        import shlex
        check_eq("K-FLIP: `fix` is words, never that argv joined (t-357: a person reads it in the rehearsal text; the driver reads the field)",
                 api["fix"], "the factory registers this probe for the profile itself, from what the running stand proved; "
                             "nothing is asked of you")
        check_not_in("t-357: so `fix` names no script and no flag", "runtime_probe", api["fix"] + api["message"])
        check_not_in("t-357: ...nor `--suggest`", "--suggest", api["fix"])
        check_in("t-357: the argv is still whole in the field the driver runs", shlex.join(argv), shlex.join(api["argv"]))
        check("its script is the one next to this one", argv[1].endswith("runtime_probe.py"))
        check_not_in("the sentence does not (C3: a command line is not a sentence for a person)",
                     "runtime_probe", api["message"])
        check_not_in("nor any flag of it", "--", api["message"])
        ui = [n for n in notes if n["profile"] == "e2e-ui"][0]
        check_in("the e2e profile's container and checkout are its own",
                 "--container ui-c --checkout ../../testproject1-ui", argv_text(ui["argv"]))
        check_eq("each profile's probe ran once", len(stand.probe_calls), 2)
        for call, _cwd, _timeout in stand.probe_calls:
            check("the rehearsal's own run writes no evidence", "--no-evidence" in call)
            check("and compares against this story", "--task-root" in call)
            check("and is not the write command", "--suggest" not in call)
        check_eq("config.json is byte for byte what it was", cfg_path.read_bytes(), before)
        check_eq("K-FLIP (was C8): a derived probe is `factory_fixable` - the driver's repair row exists "
                 "(t-261) - and never a question",
                 sorted({f["class"] for f in result["findings"] if f["check"] == "s5_runtime_probe"}),
                 [gate_preflight.FACTORY_FIXABLE])
    finally:
        cleanup(root)


def test_k3_the_rehearsal_with_a_derived_probe_writes_nothing() -> None:
    root = cmp2_story("qa-gate-k3-ro-", config=probes_on)
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with stub_stand(candidates=lambda name: ["api-c"] if name.lower() == "testproject1" else ["ui-c"]):
            gate_preflight.run(task, "A")
        after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        check_eq("no file was added or removed", sorted(after), sorted(before))
        check_eq("and none was changed", [k for k in before if after.get(k) != before[k]], [])
    finally:
        cleanup(root)


def test_k3_two_candidate_checkouts_without_a_profile_id_are_one_card() -> None:
    def edit(cfg):
        probes_on(cfg)
        for repo in cfg["implementation_repos"]:
            repo.pop("execution_profile_id")
        cfg["profiles"] = cfg["profiles"][:1]   # one profile in play: one card
    root = cmp2_story("qa-gate-k3-checkout-", config=edit)
    try:
        with stub_stand() as stand:
            cards = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("K3: exactly one card", len(cards), 1)
        check_eq("and it is the person's", cards[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("it names both repositories", "testproject1-backend, testproject1-ui", cards[0]["message"])
        check_not_in("without the flag that answers it (C3)", "--checkout", cards[0]["message"])
        check_in("which travels whole in a field", "--checkout <path", cards[0]["refusal"])
        check_eq("nothing was run: the checkout is not known", stand.probe_calls, [])
    finally:
        cleanup(root)


def test_k3_one_card_per_profile_when_the_container_is_ambiguous() -> None:
    """C4: two profiles with the same ambiguity are two cards, not one for the story."""
    root = cmp2_story("qa-gate-k3-two-", config=probes_on)
    try:
        with stub_stand(containers=(("c1", "i"), ("c2", "i"), ("c3", "i")),
                        candidates=lambda name: ["c1", "c2"]) as stand:
            cards = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("K3: two profiles, two cards", sorted(c["profile"] for c in cards), ["api", "e2e-ui"])
        check_in("each names the profile and the stand",
                 "I cannot tell which running container serves the api tests on localhost",
                 [c["message"] for c in cards])
        check_in("and the containers it could be", "c1, c2", cards[0]["message"])
        check_in("with the way to answer and the way out", "or say this stand is not a container one",
                 cards[0]["fix"])
        api = [c for c in cards if c["profile"] == "api"][0]
        check("the person's word passes it (FR-4), as a line they write (t-357)", _word_passes(api))
        check_eq("t-357: the block it passes travels as data", api["waives"][0]["block"], "runtime probe: api")
        check_not_in("t-357: and the text names no flag", "--block", api["fix"])
        check_eq("AT one candidate is derived, BEYOND at two it is asked: nothing ran", stand.probe_calls, [])
    finally:
        cleanup(root)


def test_fb8_gate_a_config_absence_mismatch_and_not_shipped_line() -> None:
    """FB-8: (1) the container pick is given the gate's OWN config (not a fresh load); (2) a mismatch caused by a file ABSENT
    from the container counts it (the probe's `differing_files`: 1 of the 2 files here); (3) a matched reading names the files
    it did not compare."""
    import hooklib
    marker = {"also": ["Taskfile"], "except": []}

    def edit(cfg):
        probes_on(cfg)
        cfg.setdefault("execution", {})["non_runtime_files"] = marker
        cfg["execution"]["runtime_probes"] = {"e2e-ui": {"argv": ["x"], "cwd": ".", "timeout_s": 30}}
    root = cmp2_story("qa-gate-fb8-cfg-", config=edit)
    held = hooklib.load_config
    try:
        hooklib.load_config = lambda *a, **k: {"poison": True}
        with stub_stand(candidates=lambda name: ["api-c"]) as stand:
            cmp2_run(root, steps=("s5_runtime_probe",))
        got = stand.candidate_cfgs[0] if stand.candidate_cfgs else None
        check_eq("FB8 (R8): content_candidates gets the gate's own config, not load_config()",
                 (isinstance(got, dict) and got.get("execution", {}).get("non_runtime_files"), isinstance(got, dict) and "poison" in got),
                 (marker, False))
    finally:
        hooklib.load_config = held
        cleanup(root)
    root = cmp2_story("qa-gate-fb8-mis-", config=edit)
    try:
        absent = {"record": {"result": "mismatched", "differing_files": ["src/testproject1/a.py"], "comparisons": [
            {"file": "src/testproject1/a.py", "container_sha256": None, "local_sha256": "bbb", "note": "not in the container"},
            {"file": "src/testproject1/b.py", "container_sha256": "ccc", "local_sha256": "ccc"}]}}
        with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv: absent):
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("FB8: one card", len(found), 1)
        check_in("FB8: an absence-only mismatch counts the absent file: 1 of the files differ", " 1 of the files the story changed differ",
                 found[0]["message"])
        check_in("FB8: and names it", "src/testproject1/a.py", found[0]["message"])
        check_not_in("FB8: not the equal one", "src/testproject1/b.py", found[0]["message"])
        shipped = {"record": {"result": "matched", "not_shipped_files": ["Makefile"], "comparisons": [
            {"file": "src/a.py", "container_sha256": "x", "local_sha256": "x"},
            {"file": "Makefile", "container_sha256": None, "local_sha256": "y", "note": "not part of the running application, and not in the container"}]}}
        with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv: shipped):
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_in("FB8: the matched line says 1 file was compared and names the one that was not",
                 "(1 file(s) compared by content; not compared, because they are not in the container: Makefile)", found[0]["message"])
        with stub_stand(candidates=lambda name: ["api-c"]):
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_not_in("FB8 CONTROL: with no not-shipped list the line is the old one", "not compared", found[0]["message"])
    finally:
        cleanup(root)


def test_k3_a_candidate_with_stale_content_is_one_mismatch_and_no_ambiguity_card() -> None:
    def edit(cfg):
        probes_on(cfg)
        cfg["execution"] = {"runtime_probes": {"e2e-ui": {"argv": ["x"], "cwd": ".", "timeout_s": 30}}}
    root = cmp2_story("qa-gate-k3-stale-", config=edit)
    try:
        stale = {"record": {"result": "mismatched", "comparisons": [
            {"file": "src/testproject1/a.py", "container_sha256": "aaa", "local_sha256": "bbb"},
            {"file": "src/testproject1/b.py", "container_sha256": "ccc", "local_sha256": "ccc"}]}}
        with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv: stale) as stand:
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("K3: exactly one finding", len(found), 1)
        check_eq("and it is the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("it says the stand runs other code than this story's",
                 "the stand runs other code than this story's", found[0]["message"])
        check_in("with the file that differs", "src/testproject1/a.py", found[0]["message"])
        check_not_in("and not the one that matches", "src/testproject1/b.py", found[0]["message"])
        check_not_in("it is not the ambiguity card", "I cannot tell which running container", found[0]["message"])
        check_eq("the registered probe of the other profile was not run again", len(stand.probe_calls), 1)
    finally:
        cleanup(root)


def test_k3_what_the_probe_cannot_say_is_info_and_what_cannot_be_identified_is_a_fact() -> None:
    root = cmp2_story("qa-gate-k3-unknown-", config=lambda c: (probes_on(c), c["profiles"].pop(1)))
    try:
        unknown = {"record": {"result": "unknown", "error": "no expected revision"}}
        with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv: unknown):
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        check_eq("unknown is never a card: the one finding is the factory's own repair (K-FLIP)",
                 [f["class"] for f in by_check(result, "s5_runtime_probe")], [gate_preflight.FACTORY_FIXABLE])
        notes = by_check(result, "s5_runtime_probe")
        check_eq("it is one finding", len(notes), 1)
        check_in("quoting the probe's own error", "no expected revision", notes[0]["message"])
        check_in("still carrying the write argv (C3)", "--suggest", notes[0]["argv"])
        with stub_stand(candidates=lambda name: []) as stand:
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        check_eq("C3/F3d: no container holds the files (a built bundle): never a card",
                 by_check(result, "s5_runtime_probe"), [])
        check_in("a fact about the stand, said out loud", "no running container holds the files",
                 info_of(result, "s5_runtime_probe")[0])
        check_eq("and nothing is run", stand.probe_calls, [])
        with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv: {"timed_out": True}):
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("a probe that does not answer in time is the factory's defect",
                 [f["class"] for f in found], [gate_preflight.FACTORY_DEFECT])
        check_in("with the time it was given", "120s", found[0]["message"])
    finally:
        cleanup(root)


def test_k3_docker_that_does_not_answer_is_one_card_with_the_refusal_verbatim() -> None:
    import runtime_probe
    root = cmp2_story("qa-gate-k3-nodocker-", config=lambda c: (probes_on(c), c["profiles"].pop(1)))
    try:
        with stub_stand(containers=()) as stand:
            _spec, refusal = runtime_probe.suggest(json.loads((root / "qa-factory" / "config.json").read_text(
                encoding="utf-8")), root, "api", "localhost", "", "../../testproject1", "/app", Path("."))
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("one card", len(found), 1)
        check_eq("the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("carrying the plain half of suggest()'s refusal (C3: the flag half is not for a person)",
                 refusal.plain, found[0]["message"])
        check_not_in("and not its instruction", "--container", found[0]["message"])
        check_eq("the whole refusal travels in a field for whoever acts on it", found[0]["refusal"], str(refusal))
        check_in("which has the instruction", "--container <name>", found[0]["refusal"])
        check_eq("nothing was compared", stand.candidate_calls, [])
    finally:
        cleanup(root)


def test_k3_a_probe_that_is_registered_is_left_alone() -> None:
    for label, registered in (("by its profile", {"api": {"argv": ["x"]}, "e2e-ui": {"argv": ["x"]}}),
                              ("by `*`", {"*": {"argv": ["x"]}})):
        def edit(cfg, registered=registered):
            probes_on(cfg)
            cfg["execution"] = {"runtime_probes": registered}
        root = cmp2_story("qa-gate-k3-registered-", config=edit)
        try:
            with stub_stand() as stand:
                result = cmp2_run(root, steps=("s5_runtime_probe",))
            check_eq(f"registered {label}: nothing is derived", stand.candidate_calls, [])
            check_eq(f"registered {label}: nor run again", stand.probe_calls, [])
            check_eq(f"registered {label}: nor said", by_check(result, "s5_runtime_probe"), [])
        finally:
            cleanup(root)


def test_k3_the_step_stays_quiet_where_it_has_nothing_to_compare() -> None:
    for label, edit in (
            ("a profile the person took over", lambda cfg: None),
            ("no implementation repository recorded", lambda cfg: cfg.pop("implementation_repos")),
            ("the project says no", lambda cfg: cfg["gate_rehearsal"].__setitem__("skip_runtime_probe", True))):
        def apply(cfg, edit=edit):
            probes_on(cfg)
            edit(cfg)
            if label.startswith("the project"):
                cfg["gate_rehearsal"]["skip_runtime_probe"] = True
        root = cmp2_story("qa-gate-k3-quiet-", config=apply)
        try:
            if label.startswith("a profile"):
                pipe = root / "qa-factory" / "artifacts" / CMP2_TICKET / "pipeline.json"
                data = json.loads(pipe.read_text(encoding="utf-8"))
                data["stage_overrides"] = [
                    {"stage": "S5", "match": f"executor unavailable: {p}", "decision": "I run them",
                     "by": "human"} for p in ("api", "e2e-ui")]
                pipe.write_text(json.dumps(data), encoding="utf-8")
            with stub_stand() as stand:
                result = cmp2_run(root, steps=("s5_runtime_probe",))
            check_eq(f"{label}: no finding", by_check(result, "s5_runtime_probe"), [])
            check_eq(f"{label}: nothing run", stand.probe_calls + stand.candidate_calls, [])
            if not label.startswith("no implementation"):   # that one says so, as Q1 requires
                check_eq(f"{label}: and no line either", info_of(result, "s5_runtime_probe"), [])
        finally:
            cleanup(root)
    root = cmp2_story("qa-gate-k3-norows-", base=False, config=probes_on)   # no automate row at all
    try:
        with stub_stand() as stand:
            check_eq("no automate rows: nothing", by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe"), [])
        check_eq("and docker is never asked", stand.candidate_calls, [])
    finally:
        cleanup(root)


def test_k3_a_stand_the_story_did_not_choose_is_a_card_with_the_refusal() -> None:
    root = cmp2_story("qa-gate-k3-nostand-", config=lambda c: (probes_on(c), c["profiles"].pop(1)))
    try:
        pipe = root / "qa-factory" / "artifacts" / CMP2_TICKET / "pipeline.json"
        data = json.loads(pipe.read_text(encoding="utf-8"))
        del data["environment"]
        pipe.write_text(json.dumps(data), encoding="utf-8")
        with stub_stand() as stand:
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("one card", len(found), 1)
        check_in("it carries the refusal naming both stands", "localhost, preview", found[0]["message"])
        check_not_in("without its flag (C3)", "--environment", found[0]["message"])
        check_in("which travels whole in a field", "--environment <name>", found[0]["refusal"])
        check_eq("nothing was asked of docker", stand.candidate_calls, [])
    finally:
        cleanup(root)


def test_k3_the_container_is_chosen_by_what_it_holds() -> None:
    """The content test end to end through the gate: only `subprocess.run` is replaced, and the
    candidate is the container that holds every file the story changed."""
    import types
    import runtime_probe
    def edit(cfg):
        probes_on(cfg)
        cfg["profiles"].pop(1)
        cfg["implementation_repos"][0]["local_path"] = "backend"
    root = cmp2_story("qa-gate-k3-content-", config=edit)
    try:
        (root / "backend" / "src").mkdir(parents=True)
        (root / "backend" / "src" / "a.py").write_text("a", encoding="utf-8")
        (root / "backend" / "src" / "b.py").write_text("b", encoding="utf-8")
        work = root / "qa-factory" / "artifacts" / CMP2_TICKET / "work"
        (work / "impl-diff.txt").write_text("+++ b/src/a.py\n+++ b/src/b.py\n+++ b/README.md\n", encoding="utf-8")
        asked = []

        def fake_run(argv, **kwargs):
            asked.append(list(argv))
            if argv[:2] == ["docker", "ps"]:
                return types.SimpleNamespace(returncode=0, stderr="", stdout="holds-all\ti\nlacks-one\ti\nslow\ti\n")
            name, paths = argv[2], argv[4:]
            if name == "slow":
                raise subprocess_module.TimeoutExpired(argv, 1)
            have = paths if name == "holds-all" else paths[:1]
            return types.SimpleNamespace(returncode=0 if have == paths else 1, stderr="",
                                         stdout="".join(f"abc  {p}\n" for p in have))
        import subprocess as subprocess_module
        held = runtime_probe.subprocess
        runtime_probe.subprocess = types.SimpleNamespace(
            run=fake_run, TimeoutExpired=subprocess_module.TimeoutExpired, CompletedProcess=subprocess_module.CompletedProcess)
        held_probe = gate_preflight.run_probe
        calls = []
        gate_preflight.run_probe = lambda argv, cwd, timeout: calls.append(list(argv)) or {
            "record": {"result": "matched", "comparisons": []}}
        try:
            result = cmp2_run(root)
        finally:
            runtime_probe.subprocess = held
            gate_preflight.run_probe = held_probe
        check_eq("one probe ran, against the container that holds both files",
                 [a[a.index("--container") + 1] for a in calls], ["holds-all"])
        check_eq("and no card was raised: the one finding is the factory's repair (K-FLIP)",
                 [f["class"] for f in by_check(result, "s5_runtime_probe")], [gate_preflight.FACTORY_FIXABLE])
        execs = [a for a in asked if a[:2] == ["docker", "exec"]]
        check_eq("one `docker exec` per container, the production files only", len(execs), 3)
        check("README.md, a document, was never compared", all("README.md" not in " ".join(a) for a in execs))
    finally:
        cleanup(root)


# --- the four users of `s5_profiles` (C5) and the switch for the new steps -----------------------------

def test_the_users_of_the_profile_keying_are_the_ones_the_report_lists() -> None:
    """A guard for the list the report names: if a fifth caller appears, this fails and the list is
    reread (the keying changed what every one of them sees: e2e rows now belong to a profile)."""
    users, inside = [], 0
    for path in sorted(SCRIPTS.glob("*.py")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "s5_profiles(" in line and "def s5_profiles" not in line:
                users.append(path.name)
            if path.name == "gate_preflight.py" and "self.keyed_profiles()" in line:
                inside += 1
    # t-300 N1a: `stand_profiles` (the profiles a stand-identity question is about; the build check at the S5/S6 entry
    # reads it) is the second call inside gate_preflight.py - the fifth user of the keying, named here on purpose;
    # `story_step.py` (`_hand_detail`, C2-3 core) is the sixth
    check_eq("`s5_profiles` is called by controller (`_handed_cases`), by the rehearsal's own cache, by "
             "`stand_profiles` (t-300) and by story_step (`_hand_detail`, C2-3), and by no other script", sorted(users),
             ["controller.py", "gate_preflight.py", "gate_preflight.py", "story_step.py"])
    check_eq("the rehearsal asks the cache in seven places: executor, toolchain, reporter, stand "
             "limits, runtime probe, story ids, dependencies", inside, 7)


def test_the_cmp2_rehearsal_is_the_one_a_person_can_read() -> None:
    """The render of the whole story: the INFO block and the questions, as printed."""
    root = cmp2_story("qa-gate-render-", config=lambda c: with_limits(110, 30)(c))
    try:
        text = gate_preflight.render(cmp2_run(root))
        check_in("the stand limit is a question of the gate", "e2e stand limit: e2e-ui", text)
        check_in("the info block counts what is not asked", "14 preconditions are not asked", text)
        check_not_in("no seeded reason leaks into the packet", "seeded by the case itself", text)
    finally:
        cleanup(root)


# --- the fix wave after the critic of t-224 (t-218 section 0d): C1-C5, Q1, Q2, D4 ----------------------

NONE_BLOCK = "preconditions no machine can check"


def none_card_of(root) -> dict:
    found = by_check(cmp2_run(root, steps=("case_preconditions",)), "case_preconditions")
    cards = [f for f in found if f["message"].startswith(NONE_BLOCK)]
    return cards[0] if cards else {}


def brief_of(message: str, findings=None) -> list:
    rows = findings or [{"id": "x-1", "check": "x", "class": gate_preflight.PERSON_DECIDES,
                         "message": message, "fix": ""}]
    return gate_preflight.brief_lines({"gate": "A", "next_stage": "S5", "can_proceed": False,
                                       "by_class": {}, "findings": rows})


def test_c1_the_none_card_opens_with_a_lead_that_survives_the_packets_cut() -> None:
    """The gate packet shows the first 200 characters of a finding. On the real cmp2 cases the card was
    786 characters and its question and the one real need sat behind the designers' reasons."""
    root = cmp2_story("qa-gate-c1-", rewritten=False)
    try:
        card = none_card_of(root)
        message = card["message"]
        lead = gate_preflight.none_card_lead(15, 15)
        check("the real cmp2 card is long, so the cut is real", len(message) > 600)
        check("it opens with the lead", message.startswith(lead))
        check("the lead fits what the packet shows", len(lead) <= gate_preflight.BRIEF_CUT)
        check_in("the count is among the first 200 characters", "15 preconditions of 15 cases", message[:200])
        check_in("and the question", "which of these are real needs", message[:200])
        for reason in (CMP2_NEEDS_PREVIEW, CMP2_SUPERADMIN, "seeded by the case itself"):
            check_not_in(f"the lead never includes a reason: {reason[:24]}", reason, lead)
        check("the reasons follow the lead", message.index(CMP2_NEEDS_PREVIEW) > len(lead))
        check_in("and the real need is whole in the full text, named by its case",
                 f'"{CMP2_NEEDS_PREVIEW}" ({cmp2_case_id(17)})', message)
        shown = brief_of("", [card])
        check_eq("the packet shows the first 200 characters and marks the cut",
                 shown[0], "- [your call] " + message[:200] + "…")
        check_in("and says so, with where the rest is", "… marks a line cut here", shown[-1])
        check_in("t-357: where the rest is, in words - the rehearsal section of the same message",
                 "the whole list is under \"Rehearsal of gate A\" below", shown[-1])
        for banned in ("gate_preflight.py", "--text", "--gate"):
            check_not_in(f"t-357: no command is named for it ({banned!r})", banned, shown[-1])
    finally:
        cleanup(root)
    for count in (1, 2, 15, 10 ** 3, 10 ** 9):
        lead = gate_preflight.none_card_lead(count, count)
        check(f"the lead fits 200 for any count ({count}): only digits vary", len(lead) <= 200)
        check_in(f"and carries the count {count}", f"{count} precondition", lead)
        check_in(f"and the question ({count})", "which of these are real needs", lead)
    # one row: a count of one, and no "and N more" anywhere
    root = cmp2_story("qa-gate-c1-one-", rewritten=False, base=False,
                      extra=[(1, "TS-1", [_pc("PC-1", "data", "x", [], "needs the preview stand")])])
    try:
        message = none_card_of(root)["message"]
        check("one row: the lead still carries the count 1",
              message.startswith(gate_preflight.none_card_lead(1, 1)))
        check_in("in the singular", "1 precondition of 1 case cannot", message)
        check_not_in("and nothing is counted as 'more'", " more", message)
    finally:
        cleanup(root)
    # no row: no card at all, as before
    root = cmp2_story("qa-gate-c1-none-", base=False, extra=[(1, "TS-1", [_seeded("data the case creates")])])
    try:
        check_eq("no `none` item, no card", none_card_of(root), {})
    finally:
        cleanup(root)
    # a reason longer than 200 characters on its own: the lead is still whole, the reason follows
    long_reason = "the stand must hold " + "a very specific state " * 25
    root = cmp2_story("qa-gate-c1-long-", rewritten=False, base=False,
                      extra=[(1, "TS-1", [_pc("PC-1", "data", "x", [], long_reason)])])
    try:
        message = none_card_of(root)["message"]
        lead = gate_preflight.none_card_lead(1, 1)
        check("the reason is longer than the whole packet line", len(long_reason) > 200)
        check("the lead is still within 200 and opens the message", len(lead) <= 200 and message.startswith(lead))
        check_not_in("it holds no part of the reason", long_reason[:20], lead)
        check_in("the reason is whole in the text", long_reason.strip(), message)
        check_in("and the packet marks the cut", "…", brief_of(message)[0])
    finally:
        cleanup(root)
    # the cut itself: AT 200 nothing is cut, BEYOND at 201 it is, and marked
    check_eq("AT 200 characters: shown whole, no mark, no pointer line", brief_of("m" * 200),
             ["- [your call] " + "m" * 200])
    beyond = brief_of("m" * 201)
    check_eq("BEYOND at 201: cut at 200 and marked", beyond[0], "- [your call] " + "m" * 200 + "…")
    check_eq("with the one pointer line", len(beyond), 2)
    many = brief_of("", [{"id": f"x-{n}", "check": "x", "class": gate_preflight.PERSON_DECIDES,
                          "message": "m" * 250 if n == 0 else f"q{n}", "fix": ""} for n in range(7)])
    check_eq("seven rows and a cut: still ONE pointer line, saying both", len(many), 6)
    check_in("it counts the rest and says what '…' means", "+2 more and … marks a line cut here", many[-1])


def test_c2_the_stand_limit_card_offers_only_doors_that_have_an_executor() -> None:
    """Option (c) `e2e stand limit: <profile>` was read by nothing outside gate_preflight.py (FR-9)."""
    root = cmp2_story("qa-gate-c2-", config=with_limits(110, 30))
    try:
        card = limit_cards(root)[0]
        check_not_in("no option names the waiver block of the stand limit", "e2e stand limit",
                     card["fix"])
        check_eq("two options remain", [o["id"] for o in card["options"]], ["a", "b"])
        check_in("the handed door is still there, as a line the person writes (t-357)", f"write `{card['id']}: run`", card["fix"])
        check_in("...and it still passes the handed block the driver reads", "executor unavailable: e2e-ui",
                 [d["block"] for d in card["waives"]])
        check_in("and the gate-A answer form", "<case id>: manual", card["fix"])
        pipe = root / "qa-factory" / "artifacts" / CMP2_TICKET / "pipeline.json"
        data = json.loads(pipe.read_text(encoding="utf-8"))
        data["stage_overrides"] = [{"stage": "S5", "match": "e2e stand limit: e2e-ui",
                                    "decision": "written down earlier", "by": "human"}]
        pipe.write_text(json.dumps(data), encoding="utf-8")
        check_eq("a waiver file that already holds the block still passes the card (FR-4)",
                 limit_cards(root), [])
    finally:
        cleanup(root)


# FR-6: a sentence a person reads has no flag, no field path, no script name. The scan has two halves:
# the literals of every message the new checks write (static: nothing there may even be a `.py`), and
# the messages those checks actually produce on the cmp2 story (runtime: what the values add).

NEW_CHECK_FUNCTIONS = ("_e2e_limit", "check_s5_stand_limits", "_stand_limit_card", "check_s5_runtime_probe",
                       "_probe_derived", "_probe_card", "_probe_defect", "_derive_probe",
                       # t-683 D12: the sentences that moved out of `_derive_probe` stay under the same scan
                       "_probe_refused", "_probe_no_container", "_probe_no_candidates", "_probe_which_container",
                       "_probe_unreadable", "_probe_matched", "_probe_mismatched", "_probe_unknown",
                       "_probe_not_applicable", "_probe_person_confirmed",
                       "_integration_keys", "check_s5_credentials", "_none_card", "none_card_lead",
                       "not_asked_line", "_stand_account",
                       # HF1-9 (GW1-13): the sentences of the integration cards and of the story-level question
                       "_integration_cases", "_integration_cards", "_integration_gap_row", "_integration_question")
_MESSAGE_ARG = {"add": 2, "note": 1, "_probe_card": 2, "_probe_derived": 2, "_probe_defect": 2}


def message_offences(text: str, static: bool = False) -> list:
    import re
    found = []
    if re.search(r"(?<![\w-])--[A-Za-z]", text):
        found.append("a flag")
    if "[]." in text:
        found.append("a field path (`[].`)")
    if re.search(r"`[A-Za-z_][\w-]*(?:\[\])?(?:\.[A-Za-z_][\w-]*(?:\[\])?)+`", text):
        found.append("a backticked field path")
    if static:
        if re.search(r"\.py\b", text):
            found.append("`.py`")
    else:   # a product file the story changed is the story's own word; a plugin script is not
        for name in sorted(p.name for p in SCRIPTS.glob("*.py")):
            if re.search(r"(?<![\w/.-])" + re.escape(name) + r"(?![\w])", text):
                found.append(f"the plugin script {name}")
    return found


def message_literals(source: str, functions=NEW_CHECK_FUNCTIONS) -> list:
    """[(function, literal piece)] of every string that lands in a message or note in `functions`."""
    import ast
    out = []

    def pieces(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                yield from pieces(part)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            yield from pieces(node.left)
            yield from pieces(node.right)
        elif isinstance(node, ast.IfExp):
            yield from pieces(node.body)
            yield from pieces(node.orelse)
        elif isinstance(node, ast.Tuple):
            for item in node.elts:
                yield from pieces(item)

    for fn in ast.walk(ast.parse(source)):
        if not (isinstance(fn, ast.FunctionDef) and fn.name in functions):
            continue
        for node in ast.walk(fn):
            targets = []
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in _MESSAGE_ARG:
                    index = _MESSAGE_ARG[node.func.attr]
                    targets.append(node.args[index] if len(node.args) > index else next(
                        (k.value for k in node.keywords if k.arg == "message"), None))
                if isinstance(node.func, ast.Attribute) and node.func.attr == "append" \
                        and fn.name in ("_e2e_limit", "not_asked_line"):
                    targets.extend(node.args)
                targets.extend(k.value for k in node.keywords if k.arg in ("why", "what"))
            elif isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id in ("message", "why", "detail") for t in node.targets):
                targets.append(node.value)
            elif isinstance(node, ast.Return) and fn.name in ("_stand_account", "none_card_lead", "not_asked_line") \
                    and node.value is not None:
                targets.append(node.value)
            for target in targets:
                if target is not None:
                    out.extend((fn.name, piece) for piece in pieces(target))
    return out


def scan_messages(source: str) -> list:
    return [(fn, piece, why) for fn, piece in message_literals(source)
            for why in message_offences(piece, static=True)]


def probe_solo(cfg):
    probes_on(cfg)
    cfg["profiles"].pop(1)


def scenario_messages() -> list:
    """[(label, [every message and info line the step wrote])] over the situations of the new checks."""
    out = []

    def run(label, steps, config=None, stand=None, keep=lambda text: True, **kw):
        root = cmp2_story("qa-gate-c3-", config=config, **kw)
        try:
            if stand is None:
                result = cmp2_run(root, steps=steps)
            else:
                with stand:
                    result = cmp2_run(root, steps=steps)
            out.append((label, [text for text in [f["message"] for f in result["findings"]]
                                + [row["message"] for row in result["info"]] if keep(text)]))
        finally:
            cleanup(root)

    def record(value):
        return lambda cfg: (cfg["environments"][0].__setitem__("measured", {"e2e_page_load_s": value}),
                            cfg["profiles"][1].__setitem__("page_object_max_wait_s", 30))
    limits = ("s5_stand_limits",)
    run("a page slower than the wait", limits, with_limits(110, 30))
    run("nothing recorded", limits)
    run("a limit that is not a number", limits, with_limits(True, True))
    run("a measurement older than the stand", limits, with_limits(110, 30, at="2026-09-17"))
    run("a record with no command and no date", limits, record({"value": 110}))
    probe = ("s5_runtime_probe",)
    mismatch = {"record": {"result": "mismatched", "comparisons": [
        {"file": "src/testproject1/a.py", "container_sha256": "aaa", "local_sha256": "bbb"}]}}
    for label, kw in (
            ("a stand that matches", {}),
            ("a stand that does not", {"probe": lambda argv: mismatch}),
            ("a probe that cannot say", {"probe": lambda argv: {"record": {"result": "unknown", "error": "no expected revision"}}}),
            ("a probe that prints nothing readable", {"probe": lambda argv: {"unreadable": "exit 2: --container is required"}}),
            ("a probe that times out", {"probe": lambda argv: {"timed_out": True}}),
            ("an ambiguous container", {"candidates": lambda name: ["c1", "c2"]}),
            ("a built bundle", {"candidates": lambda name: []}),
            ("a docker that does not answer", {"containers": ()}),
            ("a story that changes nothing here", {"compared": []})):
        run(label, probe, probe_solo, stub_stand(**kw))
    run("a stand nobody chose", probe, probe_solo, stub_stand(),
        pipeline={"environment": ""})
    run("two checkouts, none named", probe, lambda cfg: (probe_solo(cfg), [r.pop("execution_profile_id") for r in cfg["implementation_repos"]]),
        stub_stand())
    run("no checkout recorded", probe, lambda cfg: (probes_on(cfg), [r.pop("local_path") for r in cfg["implementation_repos"]]),
        stub_stand())
    # TC_014's own finding is the `env` check's, written before t-224 (its `per <config field>` is
    # listed in the report as an analog, not scanned here): only what the new kinds say is.
    not_tc14 = lambda text: not text.startswith(cmp2_case_id(14))  # noqa: E731
    run("the none card", ("case_preconditions",), keep=not_tc14, rewritten=False)
    run("the seeded line and the account line", ("case_preconditions",), keep=not_tc14)
    account = [{"id": "PC-1", "kind": "account", "what": "an account", "partitions": [],
                "legacy": {"stand_account": "ghost"}, "rewritten": {"stand_account": "ghost"}}]
    run("an account the stand does not hold", ("case_preconditions",), base=False,
        extra=[(1, "TS-1", account)])
    run("no stand to look the account up on", ("case_preconditions",), base=False,
        extra=[(1, "TS-1", account)], pipeline={"environment": ""})
    run("an integration the story needs", ("s5_credentials",),
        lambda cfg: cfg["environment"]["integrations"][0].__setitem__("required_by", ["api"]))
    run("an integration it does not", ("s5_credentials",))
    run("an integration whose users the project names in prose", ("s5_credentials",),
        lambda cfg: cfg["environment"]["integrations"][0].__setitem__("required_by", ["api: AWS parameters and tools"]))
    return out


def test_c3_the_new_checks_speak_in_the_storys_words() -> None:
    source = (SCRIPTS / "gate_preflight.py").read_text(encoding="utf-8")
    literals = message_literals(source)
    check_eq("the scan reaches the messages of every new check that writes one literally",
             sorted({"_e2e_limit", "check_s5_stand_limits", "_stand_limit_card", "_probe_card",
                     "_probe_defect", "_derive_probe", "_none_card", "none_card_lead",
                     "not_asked_line", "_stand_account", "check_s5_runtime_probe", "check_s5_credentials"}
                    - {fn for fn, _ in literals}), [])
    check("and finds a good many literals, so it is not scanning nothing", len(literals) > 40)
    check_eq("STATIC: no literal of a message has a flag, a field path, a `.py`", scan_messages(source), [])
    # the negative control: ONE planted flag in a scratch copy of the source makes the scan fail
    for label, old, new in (
            ("a flag", "so I cannot check that it runs this story's code before ",
             "so I cannot check --container that it runs this story's code before "),
            ("a field path", "the page load recorded for {stand_name}", "the page load recorded for {stand_name} (`environments[].measured`)"),
            ("a script name", "does not say how or when it was measured", "does not say how or when it was measured (runtime_probe.py)")):
        scratch = source.replace(old, new, 1)
        check(f"control: the scratch copy really differs ({label})", scratch != source)
        check(f"control: the scan fails on {label} planted in a message", bool(scan_messages(scratch)))
    # RUNTIME: what the values add (a refusal, a route, a probe's own words)
    scenarios = scenario_messages()
    check("every scenario produced a message to scan", all(texts for _label, texts in scenarios))
    check("and there are many of them", len(scenarios) >= 20)
    for label, texts in scenarios:
        check_eq(f"RUNTIME ({label}): nothing a person would read is an instruction for a command line",
                 [(text[:60], message_offences(text)) for text in texts if message_offences(text)], [])
    # the negative control of the runtime half
    first = next(texts for _label, texts in scenarios)[0]
    for planted in (first + " pass --container <name>", first + " (see `a[].b`)", first + " in runtime_probe.py"):
        check(f"control: a planted token is caught at runtime ({planted[-24:]})", bool(message_offences(planted)))
    check_eq("control: a clean sentence is not", message_offences("the stand runs other code than this story's"), [])


def test_c4_a_story_that_changes_nothing_in_the_checkout_is_one_line_and_never_docker() -> None:
    """runtime_probe.content_candidates returned every running container when no changed file was in the
    checkout, and the probe then reported `mismatched` on zero compared files: a false card."""
    import types
    import runtime_probe
    import subprocess as subprocess_module

    class docker:
        """The subprocess `runtime_probe` talks to docker through, and the gate's own probe run, both
        recorded. `running` containers answer `docker ps`, and every one holds every file asked about."""
        def __init__(self, running):
            self.running, self.asked, self.probes = running, [], []

        def __enter__(self):
            def fake_run(argv, **kwargs):
                self.asked.append(list(argv))
                if argv[:2] == ["docker", "ps"]:
                    return types.SimpleNamespace(returncode=0, stderr="", stdout="".join(
                        f"c{n}\timg\n" for n in range(self.running)))
                return types.SimpleNamespace(returncode=0, stderr="", stdout="".join(
                    f"abc  {path}\n" for path in argv[4:]))
            self.held = (runtime_probe.subprocess, gate_preflight.run_probe)
            runtime_probe.subprocess = types.SimpleNamespace(
                run=fake_run, TimeoutExpired=subprocess_module.TimeoutExpired,
                CompletedProcess=subprocess_module.CompletedProcess)
            gate_preflight.run_probe = lambda argv, cwd, timeout: self.probes.append(list(argv)) or {
                "record": {"result": "matched", "comparisons": [
                    {"file": "src/a.py", "container_sha256": "a", "local_sha256": "a"}]}}
            return self

        def __exit__(self, *exc):
            runtime_probe.subprocess, gate_preflight.run_probe = self.held

    def story_with(diff, present):
        root = cmp2_story("qa-gate-c4-", config=probe_solo_backend)
        work = root / "qa-factory" / "artifacts" / CMP2_TICKET / "work"
        if diff is None:          # W1: no diff file at all (`[]` is an EMPTY file, which says the same)
            (work / "impl-diff.txt").unlink(missing_ok=True)
        else:
            (work / "impl-diff.txt").write_text("".join(f"+++ b/{name}\n" for name in diff), encoding="utf-8")
        for name in present:
            (root / "backend" / name).parent.mkdir(parents=True, exist_ok=True)
            (root / "backend" / name).write_text(name, encoding="utf-8")
        return root

    def probe_solo_backend(cfg):
        probe_solo(cfg)
        cfg["implementation_repos"][0]["local_path"] = "backend"

    for label, diff in (("every changed file lies outside the checkout", ["src/x.py", "src/y.py"]),
                        ("the diff names only documents", ["README.md", "docs/a.md"]),
                        ("the diff file is empty", []),
                        ("there is no diff file at all", None)):
        # W1: a diff that is NOT RECORDED (absent, or a file with nothing in it) is not "the story
        # changes nothing": the first says nothing is known (FR-41), the second claims it of the code.
        recorded = bool(diff)
        for running in (1, 3):
            root = story_with(diff, ["src/other.py"])
            try:
                with docker(running) as stand:
                    result = cmp2_run(root, steps=("s5_runtime_probe",))
                check_eq(f"{label}, {running} container(s): no finding (no false mismatch, no false ambiguity)",
                         by_check(result, "s5_runtime_probe"), [])
                notes = info_of(result, "s5_runtime_probe")
                check_eq(f"{label}, {running}: one info line", len(notes), 1)
                if recorded:
                    check_in(f"{label}, {running}: it says the story changes nothing in the checkout",
                             "the story changes nothing in `backend`", notes)
                    check_not_in(f"{label}, {running}: and not that no diff is recorded",
                                 "no implementation diff is recorded", notes[0])
                else:
                    check_in(f"{label}, {running}: it says no implementation diff is recorded",
                             "no implementation diff is recorded", notes)
                    check_not_in(f"{label}, {running}: and NEVER that the story changes nothing",
                                 "changes nothing", notes[0])
                check_eq(f"{label}, {running}: docker was not called at all", stand.asked, [])
                check_eq(f"{label}, {running}: and no probe ran", stand.probes, [])
            finally:
                cleanup(root)
    # SOME files inside the checkout: today's behaviour, only the files that are there are compared
    root = story_with(["src/a.py", "src/gone.py", "README.md"], ["src/a.py"])
    try:
        with docker(1) as stand:
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        check_eq("some files inside: no card, the derived probe is the one factory_fixable finding",
                 [f["class"] for f in by_check(result, "s5_runtime_probe")], [gate_preflight.FACTORY_FIXABLE])
        check_in("the container is derived and its code verified", "runs this story's code",
                 by_check(result, "s5_runtime_probe")[0]["message"])
        execs = [a for a in stand.asked if a[:2] == ["docker", "exec"]]
        check_eq("docker was asked, about the one file the checkout holds", [a[4:] for a in execs],
                 [["/app/src/a.py"]])
        check_eq("and the probe ran once", len(stand.probes), 1)
    finally:
        cleanup(root)
    root = story_with(["src/a.py", "src/gone.py"], ["src/a.py"])
    try:
        with docker(3) as stand:
            cards = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("some files inside and three containers that hold them: the ambiguity card, as before",
                 len(cards), 1)
        check_in("it is that card", "I cannot tell which running container", cards[0]["message"])
    finally:
        cleanup(root)


def test_fb8_gate_a_only_non_runtime_asks_no_container() -> None:
    """FB-8 (E12): a story whose only compared file is a Makefile asks no which-container question when no running container
    holds it (a compare of nothing), still asks when two hold it, and picks the one that holds it."""
    import types
    import runtime_probe
    import subprocess as subprocess_module

    def run_with(holders: set, containers: int):
        def fake_run(argv, **kwargs):
            if argv[:2] == ["docker", "ps"]:
                return types.SimpleNamespace(returncode=0, stderr="", stdout="".join(f"c{n}\timg\n" for n in range(containers)))
            have = argv[2] in holders
            return types.SimpleNamespace(returncode=0 if have else 1, stderr="",
                                         stdout="".join(f"abc  {path}\n" for path in argv[4:]) if have else "")
        probes = []
        held = (runtime_probe.subprocess, gate_preflight.run_probe)
        runtime_probe.subprocess = types.SimpleNamespace(run=fake_run, TimeoutExpired=subprocess_module.TimeoutExpired,
                                                         CompletedProcess=subprocess_module.CompletedProcess)
        gate_preflight.run_probe = lambda argv, cwd, timeout: probes.append(list(argv)) or {
            "record": {"result": "matched", "comparisons": [{"file": "Makefile", "container_sha256": "a", "local_sha256": "a"}]}}
        root = cmp2_story("qa-gate-fb8-", config=lambda cfg: (probe_solo(cfg), cfg["implementation_repos"][0].__setitem__("local_path", "backend")))
        try:
            work = root / "qa-factory" / "artifacts" / CMP2_TICKET / "work"
            (work / "impl-diff.txt").write_text("+++ b/Makefile\n", encoding="utf-8")
            (root / "backend").mkdir(parents=True, exist_ok=True)
            (root / "backend" / "Makefile").write_text("all:\n", encoding="utf-8")
            return by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe"), probes
        finally:
            runtime_probe.subprocess, gate_preflight.run_probe = held
            cleanup(root)
    cards, probes = run_with(set(), 2)
    check_eq("FB8 (E12): two running containers, none holds the Makefile: no which-container card",
             [c for c in cards if "I cannot tell which running container" in c["message"]], [])
    check_eq("FB8 (E12): and no probe ran on a guess", probes, [])
    cards, probes = run_with({"c1"}, 2)
    check_eq("FB8 (E12): exactly one holds it: no card, that container is the one probed", (len(probes), [c["class"] for c in cards]),
             (1, [gate_preflight.FACTORY_FIXABLE]))
    cards, probes = run_with({"c0", "c1"}, 2)
    check_eq("FB8 (E12) CONTROL: both hold it: the ambiguity card, as for any other file",
             len([c for c in cards if "I cannot tell which running container" in c["message"]]), 1)


def test_c5_an_integration_out_of_scope_is_not_asked_even_when_a_case_cannot_be_read() -> None:
    """`integration_readiness` applies `not_required` and `environments` first. The step applied the
    `preconditions not readable` branch before it, and asked the keys of an integration nobody needs."""
    broken = [(1, "TS-1", '[{"id": "PC-1", "kind": "toggle"}]')]

    def asked(change) -> tuple:
        def edit(cfg):
            change(cfg["environment"]["integrations"][0])
        root = cmp2_story("qa-gate-c5-", config=edit, extra=broken)
        try:
            result = cmp2_run(root, steps=("s5_credentials",))
            # HF1-9: an integration's keys are `s5_integrations`' (old: `s5_environment`)
            return by_check(result, "s5_integrations"), info_of(result, "s5_environment")
        finally:
            cleanup(root)

    found, notes = asked(lambda i: i.update(applicability="not_required"))
    check_eq("`not_required` and a case that cannot be read: no finding", found, [])
    check_in("and it says why, in env_probe's words", "outside selected scope", notes)
    found, notes = asked(lambda i: i.update(environments=["preview"]))
    check_eq("an integration of another stand and a case that cannot be read: no finding", found, [])
    found, _ = asked(lambda i: i.update(applicability="required"))
    check_eq("`required` and a case that cannot be read: today's behaviour, the keys are asked", len(found), 1)
    for key in CMP2_AWS:
        # OH3-8 (old -> new): the keys were in the message; the message says access, the first move of the fix names them
        check_in(f"{key} is asked", key, found[0]["fix"])
    found, _ = asked(lambda i: None)
    check_eq("saying nothing about itself and a case that cannot be read: unknown keeps the keys", len(found), 1)
    found, _ = asked(lambda i: i.update(environments=["localhost"], required_by=["api"]))
    check_eq("scoped to this stand and unreadable: asked", len(found), 1)


def test_q1_a_profile_with_no_recorded_checkout_is_one_line_and_never_docker() -> None:
    def no_paths(cfg):
        probes_on(cfg)
        for repo in cfg["implementation_repos"]:
            repo.pop("local_path")
    root = cmp2_story("qa-gate-q1-", config=no_paths)
    try:
        use_project(root)
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with stub_stand(compared=None) as stand:
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        check_eq("no entry has a path: no finding, no card", by_check(result, "s5_runtime_probe"), [])
        notes = [row for row in result["info"] if row["check"] == "s5_runtime_probe"]
        check_eq("one line per profile", sorted(n["profile"] for n in notes), ["api", "e2e-ui"])
        for note in notes:
            check_in(f"{note['profile']}: it names the profile", f"`{note['profile']}`", note["message"])
            check_in(f"{note['profile']}: and says what is not checked and why", "no checkout is recorded",
                     note["message"])
            check_in(f"{note['profile']}: and what S5 will do instead", "written from the request template",
                     note["message"])
        check_eq("docker was not asked, nothing was compared, nothing ran",
                 (stand.docker_calls, stand.candidate_calls, stand.probe_calls), ([], [], []))
        after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        check_eq("and nothing was written", after, before)
    finally:
        cleanup(root)
    root = cmp2_story("qa-gate-q1-norepos-", config=lambda c: (probes_on(c), c.pop("implementation_repos")))
    try:
        with stub_stand(compared=None) as stand:
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        check_eq("no repository at all: the same one line per profile, not silence",
                 len(info_of(result, "s5_runtime_probe")), 2)
        check_eq("and no docker", stand.docker_calls, [])
    finally:
        cleanup(root)
    # one entry with a path and one without: the one with is probed, the one without gets the line
    root = cmp2_story("qa-gate-q1-mixed-", config=lambda c: (probes_on(c), c["implementation_repos"][1].pop("local_path")))
    try:
        with stub_stand(candidates=lambda name: ["api-c"]) as stand:
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        check_eq("the profile whose repository has a path is probed once", len(stand.probe_calls), 1)
        check_in("and it is the api one", "api", stand.probe_calls[0][0] if stand.probe_calls else [])
        by_profile = {row["profile"]: row["message"] for row in result["info"] if row["check"] == "s5_runtime_probe"}
        found = {f["profile"]: f for f in by_check(result, "s5_runtime_probe")}
        check_in("api: its stand runs the story's code (the factory_fixable repair, K-FLIP)", "runs this story's code",
                 found["api"]["message"])
        check_eq("api: it is the factory's repair", found["api"]["class"], gate_preflight.FACTORY_FIXABLE)
        check_in("e2e-ui: no checkout recorded; the api repository is not a stand-in for it",
                 "no checkout is recorded", by_profile["e2e-ui"])
        check_eq("one docker question, for the profile that has a checkout", stand.docker_calls, ["docker ps"])
        check_eq("no card for either, and nothing for e2e-ui at all", sorted(found), ["api"])
    finally:
        cleanup(root)


def record_edit(record, wait=30):
    def edit(cfg):
        cfg["environments"][0]["measured"] = {"e2e_page_load_s": record}
        if wait is not None:
            cfg["profiles"][1]["page_object_max_wait_s"] = wait
    return edit


def test_q2_a_page_load_with_no_command_or_date_is_the_factorys_defect() -> None:
    """A number nobody can trace is not a measurement (command hygiene 6b). The route is not required."""
    full = {"value": 110, "route": "/workflows/<id>/edit", "command": "browser, signed in", "at": "2026-10-01"}
    root = cmp2_story("qa-gate-q2-value-", config=record_edit({"value": 110}))
    try:
        found = limit_cards(root)
        check_eq("a record with `value` only: one finding", len(found), 1)
        check_eq("the factory's own", found[0]["class"], gate_preflight.FACTORY_DEFECT)
        check_in("it says the record is incomplete, in words", "the recorded limit is incomplete", found[0]["message"])
        check_in("the fix names the missing parts: `command`", "`command`", found[0]["fix"])
        check_in("and `at`", "`at`", found[0]["fix"])
        check_eq("the finding carries them as a field too", found[0].get("missing"), ["command", "at"])
        check_not_in("the message does not (a field name is not a sentence)", "`command`", found[0]["message"])
        check_not_in("nor the other", "`at`", found[0]["message"])
        check_not_in("no card of the stand limit either", "cannot run here", found[0]["message"])
        pipe = root / "qa-factory" / "artifacts" / CMP2_TICKET / "pipeline.json"
        data = json.loads(pipe.read_text(encoding="utf-8"))
        data["stage_overrides"] = [{"stage": "S5", "match": "the recorded limit is incomplete",
                                    "decision": "I know", "by": "human"}]
        pipe.write_text(json.dumps(data), encoding="utf-8")
        check_eq("a person's word passes it (FR-4)", limit_cards(root), [])
    finally:
        cleanup(root)
    for label, record, missing in (("no date", dict(full, at=None), ["at"]),
                                   ("no command", {k: v for k, v in full.items() if k != "command"}, ["command"]),
                                   ("a blank command", dict(full, command="   "), ["command"]),
                                   ("a command that is not text", dict(full, command=7), ["command"])):
        root = cmp2_story("qa-gate-q2-part-", config=record_edit(record))
        try:
            found = limit_cards(root)
            check_eq(f"{label}: one defect naming only what is missing", [(f["class"], f.get("missing")) for f in found],
                     [(gate_preflight.FACTORY_DEFECT, missing)])
        finally:
            cleanup(root)
    root = cmp2_story("qa-gate-q2-full-", config=record_edit({k: v for k, v in full.items() if k != "route"}))
    try:
        found = limit_cards(root)
        check_eq("a complete record without a `route` is accepted: the card of the stand limit", len(found), 1)
        check_eq("and it is the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
    finally:
        cleanup(root)
    for label, value in (("zero", 0), ("not a number", "110"), ("a bool", True)):
        root = cmp2_story("qa-gate-q2-bad-", config=record_edit({"value": value}))
        try:
            found = limit_cards(root)
            check_in(f"{label}: today's defect, `cannot be read`, wins over `incomplete`",
                     "the recorded limit cannot be read", found[0]["message"])
        finally:
            cleanup(root)
    root = cmp2_story("qa-gate-q2-nowait-", config=record_edit({"value": 110}, wait=None))
    try:
        check_eq("a value only and no wait recorded: still the defect, the record is what is wrong",
                 [f.get("missing") for f in limit_cards(root)], [["command", "at"]])
    finally:
        cleanup(root)


def test_d4_a_probe_that_prints_nothing_readable_is_the_factorys_defect_like_a_timeout() -> None:
    root = cmp2_story("qa-gate-d4-", config=probe_solo)
    try:
        with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv: {"timed_out": True}):
            timeout = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("control: a timeout is one factory defect", [f["class"] for f in timeout],
                 [gate_preflight.FACTORY_DEFECT])
        garbled = ("exit 2: runtime_probe: --container and --checkout are both required")
        for label, answer in (("not JSON at all", {"unreadable": "the probe answered no provenance JSON (" + garbled + ")"}),
                              ("JSON with no `result`", {"record": {"error": "x", "comparisons": []}}),
                              ("an empty record", {"record": {}}),
                              ("a blank `result`", {"record": {"result": "  "}})):
            with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv, a=answer: a):
                result = cmp2_run(root, steps=("s5_runtime_probe",))
            found = by_check(result, "s5_runtime_probe")
            check_eq(f"{label}: one finding, the factory's own, as for a timeout",
                     [f["class"] for f in found], [gate_preflight.FACTORY_DEFECT])
            check_in(f"{label}: in the story's words", "the probe answered in a form the factory cannot read",
                     [f["message"] for f in found])
            check_eq(f"{label}: no flag, script or field name in the sentence",
                     [message_offences(f["message"]) for f in found], [[]])
            check_eq(f"{label}: the same way out as the timeout", [f["fix"] for f in found], [timeout[0]["fix"]])
            check_eq(f"{label}: and not an `unknown` line", info_of(result, "s5_runtime_probe"), [])
            check_eq(f"{label}: what it printed travels in a field", ["detail" in f for f in found], [True])
        with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv: {"unreadable": "the probe answered no provenance JSON (" + garbled + ")"}):
            found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_in("the raw text is kept for the people who can read it", "--container",
                 [f.get("detail", "") for f in found])
        pipe = root / "qa-factory" / "artifacts" / CMP2_TICKET / "pipeline.json"
        data = json.loads(pipe.read_text(encoding="utf-8"))
        data["stage_overrides"] = [{"stage": "S5", "match": "runtime probe: api", "decision": "go on",
                                    "by": "human"}]
        pipe.write_text(json.dumps(data), encoding="utf-8")
        for answer in ({"unreadable": "x"}, {"timed_out": True}):
            with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv, a=answer: a):
                check_eq(f"a person's word passes it ({sorted(answer)[0]})",
                         by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe"), [])
        # unchanged: a verdict is a verdict
        data["stage_overrides"] = []
        pipe.write_text(json.dumps(data), encoding="utf-8")
        for verdict, expected in (("matched", (1, 0)), ("unknown", (1, 0))):
            with stub_stand(candidates=lambda name: ["api-c"],
                            probe=lambda argv, v=verdict: {"record": {"result": v, "comparisons": []}}):
                result = cmp2_run(root, steps=("s5_runtime_probe",))
            check_eq(f"{verdict} is one finding (the factory's repair, K-FLIP) and no info line",
                     (len(by_check(result, "s5_runtime_probe")), len(info_of(result, "s5_runtime_probe"))), expected)
    finally:
        cleanup(root)


# --- t-238 (t-218 section 0e): the second fix wave ----------------------------------------------------------

def test_w3_a_verdict_outside_the_vocabulary_is_the_factorys_defect() -> None:
    """The probe's verdicts are matched / mismatched / unknown / not_applicable. Anything else was an INFO
    line that read as a stand that had been checked (D4's sibling)."""
    root = cmp2_story("qa-gate-w3-", config=lambda c: (probes_on(c), c["profiles"].pop(1)))
    try:
        for label, verdict, named in (("upper case", "MATCHED", "MATCHED"), ("a number", 7, "7"),
                                      ("zero", 0, "0"), ("a word of its own", "partial", "partial"),
                                      ("a bool", True, "True"), ("a list", ["matched"], "['matched']")):
            with stub_stand(candidates=lambda name: ["api-c"],
                            probe=lambda argv, v=verdict: {"record": {"result": v, "comparisons": []}}):
                result = cmp2_run(root, steps=("s5_runtime_probe",))
            found = by_check(result, "s5_runtime_probe")
            check_eq(f"W3 {label}: one finding, the factory's own", [f["class"] for f in found],
                     [gate_preflight.FACTORY_DEFECT])
            said = found[0]["message"] if found else ""
            check_in(f"W3 {label}: it names the value", named, said)
            check_in(f"W3 {label}: in the story's words", "a verdict the factory does not know", said)
            check_eq(f"W3 {label}: no flag, script or field name in the sentence", message_offences(said), [])
            check_eq(f"W3 {label}: and NO info line reads as a stand that was checked",
                     info_of(result, "s5_runtime_probe"), [])
        for label, answer in (("no `result` key", {"record": {"comparisons": []}}), ("None", {"record": {"result": None}}),
                              ("an empty string", {"record": {"result": ""}}), ("blank", {"record": {"result": "  "}})):
            with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv, a=answer: a):
                found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
            check_in(f"W3 {label}: nothing at all is still `no verdict` (the probe's timeout's case)",
                     "the probe answered in a form the factory cannot read", found[0]["message"] if found else "")
        # the four words keep their four branches: (findings, info lines), and the words themselves
        for verdict, expected in (("matched", (1, 0)), ("unknown", (1, 0)), ("not_applicable", (0, 1)),
                                  ("mismatched", (1, 0)), (" matched ", (1, 0))):
            with stub_stand(candidates=lambda name: ["api-c"],
                            probe=lambda argv, v=verdict: {"record": {"result": v, "comparisons": [],
                                                                      "reason": "no changed file in this checkout"}}):
                result = cmp2_run(root, steps=("s5_runtime_probe",))
            check_eq(f"W3 {verdict!r}: still its own branch (findings, info lines)",
                     (len(by_check(result, "s5_runtime_probe")), len(info_of(result, "s5_runtime_probe"))), expected)
        with stub_stand(candidates=lambda name: ["api-c"],
                        probe=lambda argv: {"record": {"result": "not_applicable",
                                                       "reason": "no changed file in this checkout"}}):
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        note = info_of(result, "s5_runtime_probe")[0]
        check_in("W4: a probe that says not_applicable is one info line carrying the probe's own reason",
                 "no changed file in this checkout", note)
        check_not_in("W4: and it is not a card, not a probe to register (no argv rides on it)", "argv",
                     json.dumps([r for r in result["info"] if r["check"] == "s5_runtime_probe"]))
    finally:
        cleanup(root)


def test_w5_the_info_lines_carry_the_portable_argv_and_the_stored_one_is_read_with_this_machine() -> None:
    root = cmp2_story("qa-gate-w5-", config=probes_on)
    try:
        use_project(root)
        by_checkout = {"testproject1": ["api-c"], "testproject1-ui": ["ui-c"]}
        with stub_stand(candidates=lambda name: by_checkout[name.lower()]) as stand:
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        notes = by_check(result, "s5_runtime_probe")
        check_eq("W5: one finding per profile (the info lines of the derived probe became findings, K-FLIP)",
                 len(notes), 2)
        for note in notes:
            check_eq(f"W5 {note['profile']}: the argv it carries opens with the PORTABLE head",
                     note["argv"][:2], ["{python}", "{plugin_root}/scripts/runtime_probe.py"])
        shown = json.dumps([result["info"], result["findings"]])
        check_not_in("W5: nothing the rehearsal shows names this machine's interpreter", sys.executable, shown)
        check_not_in("W5: nor the plugin's location on it", str(SCRIPTS).replace("\\", "\\\\"), shown)
        for call, _cwd, _timeout in stand.probe_calls:
            check_eq("W5: the probe the rehearsal RUNS itself is run with this machine's interpreter",
                     call[0], sys.executable)
        # the other reader of the config's probes: the stand's identity for the reporter's rehearsal key. Since t-300 B1 it
        # reads through the REHEARSAL reader (execution_request.rehearsal_probe), never through run_suite.probe_runtime
        import execution_request
        held = execution_request.rehearsal_probe
        seen = []
        execution_request.rehearsal_probe = lambda spec, accepts=None: seen.append(spec) or {"observed_runtime_identity": "build-1"}
        try:
            cfg = dict(json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")))
            cfg["execution"] = {"runtime_probes": {"api": {
                "argv": ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--profile", "api"], "cwd": "."}}}
            rehearsal = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / CMP2_TICKET, "A")
            rehearsal.config = cfg
            identity = rehearsal._observed_identity("api", root)
        finally:
            execution_request.rehearsal_probe = held
        check_eq("W5: the identity reader got this machine's interpreter and plugin path",
                 (identity, seen[0]["argv"][0], Path(seen[0]["argv"][1]).is_file()), ("build-1", sys.executable, True))
    finally:
        cleanup(root)


# --- t-300 N1a: the rehearsal reader of the stand's identity, the fifth verdict, the profiles a stand question is about ---

FAKE_PROBE = '''\
"""A stand-in for runtime_probe.py: prints the record `mode.json` (next to it) asks for, as the real probe does under
--no-evidence: no evidence file named and the marker `observed_without_evidence`. Its argv travels in `argv_seen`."""
import json
import os
import sys

argv = sys.argv[1:]
mode = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode.json")))
rehearsal = "--no-evidence" in argv
record = {"profile_id": "api", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
          "expected_source_revision": "a" * 40, "observed_runtime_identity": mode.get("identity", "image:sha256:" + "b" * 64),
          "evidence_refs": [] if rehearsal else ["evidence/runtime-provenance-api.json"], "result": mode["result"],
          "provenance": mode["provenance"], "argv_seen": argv}
if mode.get("confirmation"):
    record["person_confirmation"] = mode["confirmation"]
if rehearsal and mode.get("marker", True):
    record["observed_without_evidence"] = True
print(json.dumps(record))
'''
MATCHED_PROV = {"technical_verification": True, "source_linkage": "exact", "identity_kind": "oci_label",
                "deployed_source_revision": "a" * 40, "verified_source_revisions": ["a" * 40]}
CONFIRMED_PROV = {"technical_verification": False, "identity_kind": "person_confirmed"}
CONFIRMATION = {"words": "yes, it is deployed", "at": "2026-10-02T11:00:00+00:00", "task": CMP2_TICKET,
                "kind": "deployed", "revision": "a" * 40}


def test_t300_k30_the_identity_reader_of_gate_a_is_a_rehearsal_and_takes_the_fifth_word() -> None:
    """R1 (`_observed_identity`): the probe runs with `--task-root` and `--no-evidence` (it used to write an evidence file on
    every rehearsal), through the rehearsal reader - a `matched` it printed without an evidence file is an identity
    here, `run_suite.probe_runtime` is left strict - and a build the person confirmed is an identity too."""
    import execution_request
    root = cmp2_story("qa-gate-t300-k30-")
    probe_dir = root / "fake-probe"
    try:
        probe_dir.mkdir()
        script = probe_dir / "runtime_probe.py"
        script.write_text(FAKE_PROBE, encoding="utf-8")
        use_project(root)
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        spec = {"argv": [sys.executable, str(script), "--profile", "api"], "cwd": ".", "timeout_s": 60}
        cfg = dict(json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")))
        cfg["execution"] = {"runtime_probes": {"api": spec}}
        rehearsal = gate_preflight.Rehearsal(task, "A")
        rehearsal.config = cfg

        def identity(**mode) -> str:
            (probe_dir / "mode.json").write_text(json.dumps(mode), encoding="utf-8")
            return rehearsal._observed_identity("api", root)

        matched = {"result": "matched", "provenance": MATCHED_PROV}
        check_eq("K30: a rehearsal `matched` (no evidence file, the marker) is the stand's identity",
                 identity(**matched), "image:sha256:" + "b" * 64)
        read = execution_request.rehearsal_probe({**spec, "cwd": str(root), "task_root": str(task.resolve())})
        argv = read["argv_seen"]
        check_eq("K30: the argv the reader ran ENDS with --no-evidence (the probe wrote nothing)", argv[-1], "--no-evidence")
        check_eq("K30: and names this story (`--task-root`), not the newest pipeline of the project",
                 argv[argv.index("--task-root") + 1], str(task.resolve()))
        check_eq("K30: the identity of a build the PERSON confirmed is an identity too",
                 identity(result="person_confirmed", provenance=CONFIRMED_PROV, confirmation=CONFIRMATION,
                          identity="person-confirmed:2026-10-02T11:00:00+00:00"), "person-confirmed:2026-10-02T11:00:00+00:00")
        check_eq("K30: `unknown` is no identity", identity(result="unknown", provenance={"technical_verification": False}), "")
        check_eq("K30: `mismatched` is no identity",
                 identity(result="mismatched", provenance=dict(MATCHED_PROV, deployed_source_revision="d" * 40)), "")
        check_eq("K30 CONTROL: the same matched record WITHOUT the marker (nothing says it was a rehearsal) is no identity",
                 identity(marker=False, **matched), "")
        # the strict reader is NOT what this goes through: run_suite.probe_runtime still refuses the rehearsal record
        import run_suite
        (probe_dir / "mode.json").write_text(json.dumps(matched), encoding="utf-8")
        try:
            run_suite.probe_runtime({**spec, "cwd": str(root), "argv": spec["argv"] + ["--no-evidence"]})
            raised = False
        except Exception as exc:
            raised = "unverified provenance" in str(exc)
        check_eq("K30: and `run_suite.probe_runtime` is still STRICT: a matched printed under --no-evidence raises there", raised, True)
    finally:
        cleanup(root)


def test_t300_k31_a_confirmed_build_is_an_info_line_at_gate_a_not_a_factory_defect() -> None:
    root = cmp2_story("qa-gate-t300-k31-", config=lambda c: (probes_on(c), c["profiles"].pop(1)))
    try:
        with stub_stand(candidates=lambda name: ["api-c"],
                        probe=lambda argv: {"record": {"result": "person_confirmed", "comparisons": [],
                                                       "person_confirmation": {"words": "yes", "at": "2026-10-02T11:00:00+00:00"}}}):
            result = cmp2_run(root, steps=("s5_runtime_probe",))
        found = by_check(result, "s5_runtime_probe")
        said = info_of(result, "s5_runtime_probe")
        check_eq("K31: person_confirmed is NOT a finding (it was a factory defect before t-300)", [f["class"] for f in found], [])
        check_eq("K31: it is one INFO line", len(said), 1)
        check_in("K31: that says whose word it is", "confirmed by the person for this story", said[0] if said else "")
        check_eq("K31: in the story's words (no flag, script or field name)", message_offences(said[0]) if said else None, [])
        check_not_in("K31: nothing is registered on that evidence (no argv rides on the line)", "argv",
                     json.dumps([r for r in result["info"] if r["check"] == "s5_runtime_probe"]))
        with stub_stand(candidates=lambda name: ["api-c"],
                        probe=lambda argv: {"record": {"result": "MATCHED", "comparisons": []}}):
            control = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("K31 CONTROL: a spelling outside the five (`MATCHED`) is still the factory's defect",
                 [f["class"] for f in control], [gate_preflight.FACTORY_DEFECT])
    finally:
        cleanup(root)


def test_t345_r8_the_two_new_texts_of_the_probe_verdicts_obey_the_human_text_rules() -> None:
    """t-345 R8: the INFO sentence of a `person_confirmed` verdict and the probe's own error QUOTED in the `unknown` finding are text a
    person reads (FR-6). The package's checker is `human_text.problems` (references/human-text.json, the rules of
    human-questions.md): run over the text the gate really produces - the INFO line, and the finding for EVERY outcome sentence
    the probe can put into its `error` (references/build-identity-methods.json). The whole-question rules (filler, floor, answer
    block) are not asked of a fragment; every shape rule is, in both kinds."""
    import human_text
    import stand_identity as SI
    fragment = {"filler", "too_short", "no_how_to_answer"}

    def broken(text: str) -> list:
        return [(kind, f["rule"], f["found"]) for kind in ("report", "question") for f in human_text.problems(text, kind=kind)
                if f["rule"] not in fragment]
    slots = dict(container="api-c", why="Error response from daemon: Container 0a1b is not running", label="org.opencontainers.image.revision",
                 value="'unknown'", path="/usr/share/nginx/html/build-sha.txt", app_root="/app", limit=4096, code=1, command="python build.py",
                 expected="rev-1")
    root = cmp2_story("qa-gate-t345-r8-", config=lambda c: (probes_on(c), c["profiles"].pop(1)))
    try:
        with stub_stand(candidates=lambda name: ["api-c"],
                        probe=lambda argv: {"record": {"result": "person_confirmed", "comparisons": [],
                                                       "person_confirmation": {"words": "yes", "at": "2026-10-02T11:00:00+00:00"}}}):
            info = info_of(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
        check_eq("R8: the INFO sentence of a confirmed build obeys the rules", (len(info), broken(info[0]) if info else None), (1, []))
        sentences = dict(SI.data()["outcomes"])
        sentences["a probe with no message"] = "which build the stand runs could not be read"
        for name, template in sentences.items():
            error = template.format(**slots)
            with stub_stand(candidates=lambda name: ["api-c"], probe=lambda argv, error=error: {"record": {"result": "unknown", "error": error}}):
                found = by_check(cmp2_run(root, steps=("s5_runtime_probe",)), "s5_runtime_probe")
            check_eq(f"R8: the finding that quotes the probe's `{name}` obeys the rules", (len(found), broken(found[0]["message"]) if found else None), (1, []))
        # NEGATIVE CONTROL: the checker is not asleep - the sentence the probe used to quote for a failed command carried `exit 1`
        old = "the way you gave failed (exit 1): boom"
        check_eq("R8 NEGATIVE CONTROL: a quoted `exit 1` IS caught by the same checker", [rule for _k, rule, _f in broken(old)], ["exit_code", "exit_code"])
    finally:
        cleanup(root)


def test_ep1_41f_the_probe_picks_the_stand_of_the_profile_it_probes() -> None:
    """`Rehearsal._probe_picks` asks `pick_environment` for the PROFILE's stand: with a device row and a web row, the web
    profile's probe is about the web stand (the story's selected stand is empty here) and the device profile's about the device;
    a project with no `surface` anywhere gets the answer it always had, and the story's own stand still wins."""
    import types
    import runtime_probe as rp

    def prof(pid, word):
        return {"profile_id": pid, "capabilities": [word], "commands": {"one_test": {"argv": ["t"], "cwd": "."}}}

    def picks(cfg, profile, selected=""):
        fake = types.SimpleNamespace(config=cfg, _selected_environment=lambda: {"name": selected})
        return gate_preflight.Rehearsal._probe_picks(fake, rp, profile)[0]
    mixed = {"profiles": [prof("e2e-ui", "web"), prof("android", "native")],
             "environments": [{"name": "web-stand"}, {"name": "emu", "surface": "android"}]}
    check_eq("probe picks: the web profile's stand is the web row, the device profile's the device row",
             (picks(mixed, "e2e-ui"), picks(mixed, "android")), ("web-stand", "emu"))
    check_eq("probe picks (F-6): the story is on the web stand, the device profile's probe is STILL about the device",
             (picks(mixed, "android", "web-stand"), picks(mixed, "e2e-ui", "web-stand")), ("emu", "web-stand"))
    web_only = {"profiles": [prof("e2e-ui", "web")], "environments": [{"name": "a"}, {"name": "b"}]}
    check_eq("probe picks: no `surface` anywhere - the story's own stand still wins", picks(web_only, "e2e-ui", "b"), "b")
    plain = {"profiles": [prof("e2e-ui", "web")], "environments": [{"name": "a"}, {"name": "b"}]}
    check_eq("probe picks: no `surface` anywhere - two stands are still no pick, as before", picks(plain, "e2e-ui"), "")


def test_t300_k32_stand_profiles_are_the_profiles_of_the_cases_a_stage_will_run() -> None:
    root = cmp2_story("qa-gate-t300-k32-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))

        def plan(**dispositions) -> None:
            rows = [plan_row(row, level=CMP2_ROW_LEVEL.get(row, "e2e-ui"), disposition=disposition)
                    for row, disposition in dispositions.items()]
            (task / "work" / "test-plan.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")

        def profiles(*dispositions) -> list:
            return sorted(gate_preflight.stand_profiles(cfg, task, dispositions))

        # TS-10 is an api row, TS-4 and TS-8 are e2e-ui rows (CMP2_ROW_LEVEL)
        plan(**{"TS-10": "automate", "TS-4": "manual-agent", "TS-8": "manual-human"})
        check_eq("K32: S5 asks about the automate rows only", profiles("automate"), ["api"])
        check_eq("K32: S6 adds the manual-agent rows (the stand a manual capture drives)", profiles("automate", "manual-agent"), ["api", "e2e-ui"])
        plan(**{"TS-10": "automate", "TS-4": "manual-human", "TS-8": "manual-human"})
        check_eq("K32: a manual-human row is NEVER included, even when the caller names it (Q14-A)",
                 (profiles("automate", "manual-agent"), profiles("automate", "manual-agent", "manual-human")), (["api"], ["api"]))
        check_eq("K32: s5_profiles' own automate reading is unchanged (the same answer as stand_profiles over automate)",
                 sorted(gate_preflight.s5_profiles(cfg, task, gate_preflight.s5_automate_rows(task))), profiles("automate"))
        plan(**{"TS-4": "manual-agent"})
        check_eq("K32: with only a manual-agent e2e row, S5 has nothing to ask and S6 asks about that profile",
                 (profiles("automate"), profiles("automate", "manual-agent")), ([], ["e2e-ui"]))
        plan(**{"TS-10": "skip", "TS-4": "unverifiable"})
        check_eq("K32: skip and unverifiable rows reach no stand", profiles("automate", "manual-agent"), [])
        check_eq("K32: no dispositions asked, no profiles", profiles(), [])
    finally:
        cleanup(root)


def _passes(message: str, match: str, stage: str) -> bool:
    """Whether a recorded word for the block `match` at `stage` passes THIS message, decided the way
    `waiver.split_overridden` decides it (`add()` calls it): the block text as the override's `match`,
    normalised as `add()` normalises the message - not a substring of the raw text."""
    from waiver import split_overridden
    pipeline = {"stage_overrides": [{"stage": stage, "match": match, "decision": "my word", "by": "human"}]}
    # t-357 F5: what the matcher is shown is the message AND the block its door names (`matched_text`, the one `add()` uses)
    shown = gate_preflight.matched_text(" ".join(str(message).split()), [{"block": match}])
    return split_overridden([shown], pipeline, stage)[0] == []


def _word_passes(finding: dict) -> bool:
    """Whether the person's word the finding OFFERS passes it (t-357): the door it carries (`waives`) passes its
    message, AND the words of its text name the finding by its own id (`<id>: accept`), so what a person writes is
    what the finding is listed under."""
    doors = finding.get("waives") or []
    named = f"`{finding['id']}: " in finding["message"] + " " + finding["fix"]
    return bool(doors) and named and _passes(finding["message"], doors[0]["block"], doors[0]["stage"])


def test_w2_the_older_cards_open_with_the_block_their_word_is_matched_against() -> None:
    """FR-4: a card that offers a person's word must be PASSED by that word. Eight older cards had a message
    that did not contain their block (and a ninth when the guard's own text carries a `"`, which the
    command writes as `'`). These are the sites no other test of this file reaches; the sweep after them
    walks every one."""
    import controller
    import stage_guard
    import planning_contract
    import question_register
    root = story("qa-gate-w2-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "TP1-15045"
        (task / "state" / "events.jsonl").write_text("", encoding="utf-8")

        def rehearse(method: str) -> list:
            r = gate_preflight.Rehearsal(task, "A")
            getattr(r, method)()
            return r.findings

        class Broken:
            """A controller whose decision cannot be assembled (a quote in the reason: the block is
            matched against the message, whatever the message quotes)."""
            def __init__(self, root): pass
            def build_gate_decision(self, gate, words): raise ValueError('a "quoted" reason')
            def check_decision(self, payload): return []

        class Raises(Broken):
            def build_gate_decision(self, gate, words): return {}
            def check_decision(self, payload): raise RuntimeError('validation "broke"')
        held = controller.Controller
        try:
            for label, fake, opening in (("assembling", Broken, "gate A decision cannot be assembled"),
                                         ("validating", Raises, "gate A decision validation raised")):
                controller.Controller = fake
                found = rehearse("check_gate_decision")
                check_eq(f"W2 {label}: one finding, the factory's own", [f["class"] for f in found],
                         [gate_preflight.FACTORY_DEFECT])
                check("W2 " + label + ": the message OPENS with its block", found[0]["message"].startswith(opening))
                check("W2 " + label + ": and the word the fix offers passes it", _word_passes(found[0]))
        finally:
            controller.Controller = held
        held = stage_guard.dispatch_errors
        try:
            stage_guard.dispatch_errors = lambda *a, **k: [
                'the "S5" window is closed: record it', "a plain problem", 'x' * 70 + ' "quoted"']
            found = rehearse("check_stage_guard")
            check_eq("W2 stage guard: one finding per problem", len(found), 3)
            for f in found:
                check(f"W2 stage guard: the word passes it ({f['message'][36:70]!r})", _word_passes(f))
            check_not_in("W2 stage guard: the `\"` of the guard's own text is written as `'` in the message too",
                         '"', found[0]["message"])

            def boom(*a, **k):
                raise RuntimeError('boom "x"')
            stage_guard.dispatch_errors = boom
            found = rehearse("check_stage_guard")
            check("W2 stage guard raising: the word passes it", _word_passes(found[0]))
            # t-357: the guard's own message ends with ITS command (`stage_guard.waiver_hint`: a script, flags, a block).
            # That tail is cut off, the door is the one every card has, and it carries the block the guard's hint named.
            plain = "stage S5 cannot start - required stages are not done: S4=running."
            hinted = plain + " " + stage_guard.waiver_hint("TP1-15045", "S5", plain)
            stage_guard.dispatch_errors = lambda *a, **k: [hinted]
            found = rehearse("check_stage_guard")
            check_eq("t-357: a guard message that carries its own command: one finding", len(found), 1)
            for banned in ("waiver.py", "--block", "--decision", "--stage", "Your word passes this"):
                check_not_in(f"t-357: its command tail is cut off ({banned!r})", banned, found[0]["message"] + found[0]["fix"])
            check("t-357: and the door is the one every card has (the id, the word, the block the hint named)",
                  _word_passes(found[0]))
            check_eq("t-357: the block of the door is the guard's own phrase for it",
                     found[0]["waives"][0]["block"], "required stages are not done")
            check_in("t-357: and the refusal itself is kept whole in the message", plain, found[0]["message"])
        finally:
            stage_guard.dispatch_errors = held
        # an open question nobody can answer as it stands (sites with no other test in this file)
        (task / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"open_questions": [{"id": "Q-1", "question": "Where?"}]}), encoding="utf-8")
        found = rehearse("check_open_questions")
        check_eq("W2 open question: one finding", len(found), 1)
        check("W2 open question: the word passes it", _word_passes(found[0]))
        # K1: the finding names EVERY defect of the question, not the first one
        from contract import question_errors
        defects = question_errors({"id": "Q-1", "question": "Where?"})
        check("K1 open question: the bare question has several defects", len(defects) >= 2, str(defects))
        check("K1 open question: the one finding counts them and carries each",
              f"{len(defects)} defect(s)" in found[0]["message"]
              and all(defect in found[0]["message"] for defect in defects), found[0]["message"][:400])
        # K1: nine violations of the plan contract are nine findings, none dropped by a cut at eight
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": [{"id": "TS-1"}]}), encoding="utf-8")
        held_errors = planning_contract.gate_plan_errors
        try:
            planning_contract.gate_plan_errors = lambda rows, mode, version: [f"violation number {i}" for i in range(9)]
            found = rehearse("check_planning_contract")
        finally:
            planning_contract.gate_plan_errors = held_errors
        check_eq("K1 plan contract: nine violations, nine findings", len(found), 9)
        check("K1 plan contract: the ninth is among them",
              any("violation number 8" in f["message"] for f in found), str([f["message"][-30:] for f in found]))
        # a branch of a register question that is not written (the planning contract stubbed)
        held = (planning_contract.has_branch_fields, planning_contract.variant_errors, question_register.load)
        try:
            planning_contract.has_branch_fields = lambda rows, cases, plan_created=None: True   # t-261: the real signature
            question_register.load = lambda root: {"questions": [{"id": "Q-1"}]}
            planning_contract.variant_errors = lambda *a, **k: [
                {"message": 'a "quoted" branch is missing', "owner": "strategist", "kind": "k",
                 "where": "TS-1", "question": "Q-1"},
                {"message": "another is missing", "owner": "designer", "kind": "k", "where": "TC-001", "question": "Q-1"}]
            found = rehearse("check_question_branches")
        finally:
            planning_contract.has_branch_fields, planning_contract.variant_errors, question_register.load = held
        check_eq("W2 question branches: one finding per branch", len(found), 2)
        for f in found:
            check("W2 question branches: the word passes it", _word_passes(f))
    finally:
        cleanup(root)


def test_c3_a_code_reading_draft_is_judged_by_its_own_checker() -> None:
    """t-1676 (RN1-12) C3: a draft with `evidence: "code-reading"` rests on an oracle and an S1 fact, never on a triage verdict; the rehearsal
    reads it through `bug_records.code_reading_problems` and says "code-reading bug draft is not ready" for a defect of it. Mutation (named,
    not run): remove the `is_code_reading` branch in `check_bug_drafts` -> this test."""
    import question_register as QR
    q7 = {"id": "Q7", "question": "What should the cart keep?", "severity": "blocker", "source_says": [],
          "readings": [{"reading": "the price shown when added is kept", "from": "person", "if_chosen": "x"}, {"reading": "refreshed", "from": "person", "if_chosen": "y"}]}
    fact = {"id": "XPANBFLFA-167 price sync / subtotal", "path": "MyBooks/src/lib/services/cartService.ts", "line": 103}
    draft = {"title": "The cart total uses the current price", "impact": "money", "violates": "requirement:R-24", "evidence": "code-reading",
             "oracle": {"question": "Q7", "quote": "the price shown when added is kept"}, "fact": fact, "check_state": "not_executed",
             "manual_steps": ["add a book at 6, change its price to 8, open the cart"], "confirmation": "unconfirmed",
             "red_test_none": "no run spoke: the defect is read from the code"}

    def findings_of(body: dict, settled: bool = True, extra: dict = None) -> list:
        root = temp_dir("qa-gate-c3-")
        try:
            (root / "qa-factory").mkdir(parents=True, exist_ok=True)
            (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
            task = root / "qa-factory" / "artifacts" / "LOCAL-1"
            (task / "work" / "bug-drafts").mkdir(parents=True)
            (task / "pipeline.json").write_text(json.dumps({"ticket": "LOCAL-1"}), encoding="utf-8")
            (task / "work" / "bug-drafts" / "price.json").write_text(json.dumps(body), encoding="utf-8")
            for other_name, other in (extra or {}).items():
                (task / "work" / "bug-drafts" / other_name).write_text(json.dumps(other), encoding="utf-8")
            (task / "work" / "context-bundle.json").write_text(json.dumps({"facts": [fact]}), encoding="utf-8")
            (task / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [q7]}), encoding="utf-8")
            if settled:
                (task / "work" / "question-answers.jsonl").write_text(json.dumps({"id": "Q7", "status": "answered", "reading": "a", "words": "a", "where": "gate_a",
                                                                                 "at": "2026-11-01T12:00:00", "row_hash": QR._hash(q7)}) + "\n", encoding="utf-8")
            r = gate_preflight.Rehearsal(task, "B")
            r.check_bug_drafts()
            return r.findings
        finally:
            cleanup(root)
    got = findings_of(draft)
    check_eq("C3 rehearsal: a valid code-reading draft raises no finding (never `without a triage verdict`)", got, [])
    got = findings_of(draft, settled=False)
    check_eq("C3 rehearsal: an invalid one is `code-reading bug draft is not ready`, once per problem",
             [f["message"].startswith("price code-reading bug draft is not ready") for f in got], [True])
    check_not_in("C3 ... and never `without a triage verdict`", "without a triage verdict", " ".join(f["message"] for f in got))
    check_in("C3 ... naming the question and the door", "Q7 is not settled", got[0]["message"] if got else "")
    # C-P1 (t-1682): two code-reading drafts on one requirement: the refusal names the other file, it is not a TypeError text
    got = findings_of(draft, extra={"twin.json": dict(draft, title="the same bug again")})
    text = " ".join(f["message"] for f in got)
    check_in("C3 (C-P1) two drafts on R-24: the rehearsal says `also a code-reading draft` and names the file", "twin.json is also a code-reading draft for R-24", text)
    check_not_in("C3 (C-P1) ... never a TypeError text", "TypeError", text)
    got = findings_of(dict(draft, evidence="Code-Reading"))
    check_eq("C3 evidence `Code-Reading` is judged as a triage draft (refused for its missing triage_ref)",
             [f["message"].startswith("price bug draft without a triage verdict") for f in got][:1], [True])


def test_w2_the_gate_b_cards_about_a_bug_draft_open_with_their_block() -> None:
    """Six cards of gate B said "{case} is red ..." / "{case}'s bug draft ..." and offered a word whose block
    was "{case} bug draft without ...": the word passed none of them. Every shape, one story each."""
    draft = {"title": "a removed node is drawn at the origin", "impact": "degraded",
             "violates": "requirement:R-4", "case": "TC-004",
             "triage_ref": {"instance_id": "test_removed_node[chromium]", "attempt_id": "a3"},
             "manual_steps": ["open the diff", "the removed node sits at the corner"], "red_test_none": "manual check only",
             "mechanism": {"status": "unknown", "why": "the cards of this test are about other fields"}}     # t-2187 N8: a new draft is asked for its cause
    table_reviewed = "| Plan row | Case | Reviewed |\n|---|---|---|\n| TS-4 | TC-004 | {} |\n"
    table_silent = "| Plan row | Case |\n|---|---|\n| TS-4 | TC-004 |\n"

    def bug_story(changes: dict, verdict: str = "APP_BUG", table: str = table_reviewed.format("yes")) -> list:
        root = temp_dir("qa-gate-w2b-")
        try:
            (root / "qa-factory").mkdir(parents=True, exist_ok=True)
            (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
            task = root / "qa-factory" / "artifacts" / "TP1-15045"
            (task / "work" / "bug-drafts").mkdir(parents=True)
            (task / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045"}), encoding="utf-8")
            body = {k: v for k, v in dict(draft, **changes).items() if v is not None}
            (task / "work" / "bug-drafts" / "removed-node.json").write_text(json.dumps(body), encoding="utf-8")
            (task / "work" / "triage.json").write_text(json.dumps({"triage": [
                {"instance_id": "test_removed_node[chromium]", "attempt_id": "a3", "verdict": verdict}]}), encoding="utf-8")
            findings = task / "work" / "test-cases" / "critic-findings.md"
            findings.parent.mkdir(parents=True)
            findings.write_text("## Roll-call\n\n" + table, encoding="utf-8")
            r = gate_preflight.Rehearsal(task, "B")
            r.check_bug_drafts()
            return r.findings
        finally:
            cleanup(root)
    for label, found, opening in (
            ("no triage verdict", bug_story({"triage_ref": None}), "TC-004 bug draft without a triage verdict"),
            ("a verdict that is not APP_BUG", bug_story({}, verdict="TEST_BUG"), "TC-004 bug draft without an APP_BUG verdict"),
            ("a case the critic never read", bug_story({}, table=table_reviewed.format("no")),
             "TC-004 bug draft from an unreviewed case"),
            ("a case whose review is not stated", bug_story({}, table=table_silent),
             "TC-004 bug draft from a case whose review is not stated"),
            ("no manual steps", bug_story({"manual_steps": None}), "TC-004 bug draft without manual steps"),
            ("a field missing", bug_story({"title": None}), "TC-004 bug draft is incomplete")):
        check_eq(f"W2 {label}: exactly one card", len(found), 1)
        check(f"W2 {label}: the message OPENS with its block", found[0]["message"].startswith(opening))
        check(f"W2 {label}: and the word the fix offers passes it", _word_passes(found[0]))
    # X7-5 (P28): the red test travels with the bug - an ordinary draft with neither field is refused naming both
    found = bug_story({"red_test_none": None})
    check_eq("X7-5 a draft without red_test/red_test_none: exactly one card", len(found), 1)
    check("X7-5 ... it OPENS with its block and names both fields",
          found[0]["message"].startswith("TC-004 bug draft without its red test")
          and "`red_test`" in found[0]["message"] and "`red_test_none`" in found[0]["message"], found[0]["message"][:200])
    check("X7-5 ... and the word the fix offers passes it", _word_passes(found[0]))
    check_eq("X7-5 `red_test_none: manual check only` passes", bug_story({"red_test_none": "manual check only"}), [])
    check_eq("X7-5 a draft created before 2026-11-04 is untouched", bug_story({"red_test_none": None, "created": "2026-11-03"}), [])
    # a long case id: the block is cut at 60 characters, the message carries the whole of it
    found = bug_story({"case": "TP1-15045_TC_004 TP1-15045_TC_005"}, table=table_reviewed.format("yes").replace("TC-004", "X"),
                      verdict="TEST_BUG")
    check("W2: a case id longer than the cut block still passes", _word_passes(found[0]))


def test_t2187_n2_the_rehearsal_reads_the_manifestations_and_the_cause() -> None:
    """t-2187 N2 (5.3, F-2 (a), F-5 (a)): the rehearsal asks the roll-call about EVERY case of a merged draft, turns a manifestation or a cause
    that does not stand into a finding with the person's door, and asks a new triage draft for `mechanism` only once `BUG_MECHANISM_CUTOFF`
    is a day (both worlds). Mutation (named, not run): `named` back to the label's tokens -> the unreviewed-second-case key; the cutoff
    guard removed -> the `None` key."""
    import contract
    line = "const q = f(1);"
    good = {"statement": "s", "status": "confirmed", "basis": [{"id": "b1", "kind": "code_line", "path": "src/P.tsx", "line": 2, "quote": line}]}
    rows = [{"instance_id": "t1", "attempt_id": "a1", "case": "TC-004", "verdict": "APP_BUG"},
            {"instance_id": "t2", "attempt_id": "a1", "case": "TC-005", "verdict": "APP_BUG"}]

    def man(n, **over):
        return {"action": f"a{n}", "start_state": "s", "seen": "x", "case": f"TC-00{n + 3}", "evidence": "e", "red_test_none": "manual",
                "triage_row": {"instance_id": f"t{n}", "attempt_id": "a1"}, **over}
    base = {"title": "t", "impact": "degraded", "violates": "requirement:R-4", "case": "TC-004", "manual_steps": ["open"], "red_test_none": "manual",
            "triage_ref": {"instance_id": "t1", "attempt_id": "a1"}, "mechanism": good, "manifestations": [man(1), man(2)]}

    def findings_of(changes: dict, second_reviewed: str = "yes", cutoff=None, drop=()) -> list:
        root = temp_dir("qa-gate-n2-")
        held = contract.BUG_MECHANISM_CUTOFF
        try:
            (root / "qa-factory").mkdir(parents=True, exist_ok=True)
            (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "P.tsx").write_text("a\n" + line + "\n", encoding="utf-8")
            task = root / "qa-factory" / "artifacts" / "TP1-15045"
            (task / "work" / "bug-drafts").mkdir(parents=True)
            (task / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045"}), encoding="utf-8")
            body = {k: v for k, v in dict(base, **changes).items() if v is not None and k not in drop}
            (task / "work" / "bug-drafts" / "qty.json").write_text(json.dumps(body), encoding="utf-8")
            (task / "work" / "triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
            findings = task / "work" / "test-cases" / "critic-findings.md"
            findings.parent.mkdir(parents=True)
            findings.write_text("## Roll-call\n\n| Plan row | Case | Reviewed |\n|---|---|---|\n| TS-4 | TC-004 | yes |\n"
                                f"| TS-5 | TC-005 | {second_reviewed} |\n", encoding="utf-8")
            contract.BUG_MECHANISM_CUTOFF = cutoff
            r = gate_preflight.Rehearsal(task, "B")
            r.check_bug_drafts()
            return r.findings
        finally:
            contract.BUG_MECHANISM_CUTOFF = held
            cleanup(root)
    check_eq("N2 control: a merged draft whose cause stands, whose manifestations stand and whose cases were reviewed: no card", findings_of({}), [])
    found = findings_of({}, second_reviewed="no")
    check_eq("N2 5.3: the SECOND case of a merged draft is in the roll-call's unreviewed list: one card, opening with its block, naming that case",
             [(f["message"].startswith("TC-004 bug draft from an unreviewed case"), "TC-005 never reached the case critic" in f["message"]) for f in found], [(True, True)])
    check("N2 5.3: ... and the word the card offers passes it", all(_word_passes(f) for f in found))
    found = findings_of({"manifestations": [man(1), man(2, evidence="")]})
    check_eq("N2 5.3: a broken manifestation: one card, opening with its block", [f["message"].startswith("TC-004 bug draft manifestations do not stand") for f in found], [True])
    check("N2 5.3: ... naming the fault, and its word passes", "lacks evidence" in found[0]["message"] and _word_passes(found[0]), found[0]["message"][:200])
    broken = dict(good, basis=[{"id": "b1", "kind": "code_line", "path": "src/Nope.tsx", "line": 1, "quote": "x"}])
    found = findings_of({"mechanism": broken})
    check_eq("N2 F-2: a merge whose basis does not stand: ONE card (the merge's), opening with its block, with the first problem and the doors",
             [(f["message"].startswith("TC-004 bug draft merges manifestations without a confirmed cause"), "a `code_line` basis does not stand" in f["message"],
               "possibly_same_cause" in f["fix"]) for f in found], [(True, True, True)])
    check("N2 F-2: ... its word passes", _word_passes(found[0]))
    found = findings_of({"mechanism": broken, "manifestations": [man(1)]})
    check_eq("N2 F-2: ONE manifestation and a broken cause: the cause's own card, not the merge's",
             [f["message"].startswith("TC-004 bug draft cause does not stand") for f in found], [True])
    check_eq("N2 F-2: an unknown cause on a merge: the merge's card", [f["message"].startswith("TC-004 bug draft merges manifestations") for f in
             findings_of({"mechanism": {"status": "unknown", "why": "w"}})], [True])
    check_eq("N2 old draft: no mechanism, no manifestations: nothing new", findings_of({}, drop=("mechanism", "manifestations")), [])
    # F-5 (a): both worlds of the cutoff
    plain = dict(drop=("mechanism", "manifestations"))
    check_eq("N2 F-5: cutoff None, a new draft without `mechanism`: no card", findings_of({"created": "2099-01-01"}, **plain), [])
    found = findings_of({"created": "2026-11-12"}, cutoff="2026-11-10", **plain)
    check_eq("N2 F-5: cutoff a day, a draft made after it without `mechanism`: one card opening with its block",
             [f["message"].startswith("TC-004 bug draft without its cause") for f in found], [True])
    check("N2 F-5: ... the word it offers passes", _word_passes(found[0]))
    check_eq("N2 F-5: AT the cutoff day it is asked; the day before it is not",
             (len(findings_of({"created": "2026-11-10"}, cutoff="2026-11-10", **plain)), findings_of({"created": "2026-11-09"}, cutoff="2026-11-10", **plain)), (1, []))
    check_eq("N2 F-5: a draft that carries `mechanism` (the empty outcome, unknown with the reason) is not asked",
             findings_of({"created": "2026-11-12", "mechanism": {"status": "unknown", "why": "w"}, "manifestations": [man(1)]}, cutoff="2026-11-10"), [])
    cr = {"title": "t", "impact": "money", "violates": "requirement:R-24", "evidence": "code-reading", "created": "2026-11-12"}
    check_not_in("N2 F-5: a code-reading draft is never asked for `mechanism`", "without its cause",
                 " ".join(f["message"] for f in findings_of(cr, cutoff="2026-11-10", drop=("case", "triage_ref", "mechanism", "manifestations", "manual_steps", "red_test_none"))))


def test_g1_9_the_rehearsal_reads_the_drafts_through_the_one_reader() -> None:
    """G1-9 (t-1078): `check_bug_drafts` takes its files from `bug_records.draft_paths` (F-2 (a): `work/bug-drafts/*.json`,
    then the old flat `bug-drafts/*.json`) and the verdicts from `bug_records.triage_verdicts`. A draft in the OLD home
    is judged like any other (a reader without the old home is the M4 mutation); a `*.md` in either home is no draft."""
    import bug_records
    root = temp_dir("qa-gate-g19-")
    try:
        (root / "qa-factory").mkdir(parents=True, exist_ok=True)
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        task = root / "qa-factory" / "artifacts" / "TP1-15045"
        (task / "bug-drafts").mkdir(parents=True)
        (task / "work" / "bug-drafts").mkdir(parents=True)
        body = {"title": "t", "impact": "degraded", "violates": "requirement:R-4", "case": "TC-004",
                "manual_steps": ["open the diff", "look at the corner"], "red_test_none": "manual check only",
                "mechanism": {"status": "unknown", "why": "the card of this test is about the verdict"}}     # t-2187 N8: a new draft is asked for its cause
        (task / "bug-drafts" / "old-home.json").write_text(json.dumps(body), encoding="utf-8")
        (task / "work" / "bug-drafts" / "laid-by-hand.md").write_text("# a draft nobody's writer produced", encoding="utf-8")
        (task / "work" / "triage.json").write_text(json.dumps({"triage": [
            {"instance_id": "test_removed_node[chromium]", "attempt_id": "a3", "verdict": "APP_BUG"}]}), encoding="utf-8")
        r = gate_preflight.Rehearsal(task, "B")
        r.check_bug_drafts()
        check_eq("G1-9: a draft in the old home is judged: one card, and it names that file",
                 [("old-home.json" in f["message"], f["message"].startswith("TC-004 bug draft without a triage verdict"))
                  for f in r.findings], [(True, True)])
        check_eq("G1-9: the verdicts are the one helper's (instance+attempt, and the bare instance)",
                 r._draft_triage_verdicts(), bug_records.triage_verdicts([
                     {"instance_id": "test_removed_node[chromium]", "attempt_id": "a3", "verdict": "APP_BUG"}]))
        (task / "bug-drafts" / "old-home.json").unlink()
        r = gate_preflight.Rehearsal(task, "B")
        r.check_bug_drafts()
        check_eq("G1-9: only a *.md is left: no draft, no card (it is not the writer's file)", r.findings, [])
    finally:
        cleanup(root)


def _template(node) -> str:
    """The text of a message or block expression with every value left as `{<its source>}`."""
    import ast
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_template(v) if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}"
                       for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _template(node.left) + _template(node.right)
    return "{" + ast.unparse(node) + "}"


def test_w2_every_card_that_offers_a_word_contains_its_block() -> None:
    """THE SWEEP, as a test, so the class stays closed: every `add()` of gate_preflight.py that offers a
    person's word (`waiver_command`) is proved to contain its block in the message the word is matched
    against - by the SOURCE (the message's text contains the block's text, values left as they are named)
    or by a RUN (the tripwire at the top of this file saw it, and `waiver.split_overridden` passed it).
    Run last: the record is what the whole file did."""
    import ast
    source = (SCRIPTS / "gate_preflight.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def waiver_calls(node):
        return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "waiver_command"]
    norm = lambda text: " ".join(text.split()).lower()  # noqa: E731
    sites, inside = {}, 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add":
            blocks = [_template(c.args[0]) for c in waiver_calls(node) if c.args]
            if blocks:
                inside += len(blocks)
                message = node.args[2] if len(node.args) > 2 else next(k.value for k in node.keywords if k.arg == "message")
                sites[node.lineno] = (_template(message), blocks)
    every = len(waiver_calls(tree))
    check("the census finds the add() calls that offer a word", len(sites) >= 18)
    check_eq("t-357: every waiver_command lives inside an add() call (the stage guard's door no longer sits in a `fix` "
             "variable; its card is proved by a RUN, above)", every - inside, 0)
    handed = "{HANDED_MATCH_PREFIX}"   # `_handed()` reads that word from the overrides; the card is skipped before add()
    proved_by_source = proved_by_run = 0
    unproved = []
    for line, (message, blocks) in sorted(sites.items()):
        owed = [b for b in blocks if not b.startswith(handed)]
        if not owed:
            continue
        by_source = all(norm(b) in norm(message) for b in owed)
        by_run = line in WAIVER_SEEN
        proved_by_source += by_source
        proved_by_run += by_run
        if not (by_source or by_run):
            unproved.append((line, owed, message[:60]))
    check_eq("STATIC/RUN: every card that offers a word is proved to contain its block, by the source or by a run",
             unproved, [])
    check("the two proofs are both in use (the source one is not the only one)", proved_by_source > 5 and proved_by_run > 5)
    # RUNTIME: every card this file's runs produced, judged the way the waiver matcher judges it
    bad = [(line, message[:70], match) for line, rows in sorted(WAIVER_SEEN.items()) for message, match, stage in rows
           if not match.startswith(gate_preflight.HANDED_MATCH_PREFIX)
           and not _passes(message, match, stage)]
    check_eq("RUNTIME: no card of any run in this file offers a word that does not pass it", bad, [])
    check("and the tripwire saw a good many of them (it is not recording nothing)",
          sum(len(rows) for rows in WAIVER_SEEN.values()) > 40)
    # the negative control: a planted message that does NOT contain its block must be caught by the same logic
    from waiver import split_overridden
    check("control: a message without its block, and no door that names it, is NOT passed by its word",
          split_overridden(["the gate A decision cannot even be assembled: boom"], {"stage_overrides": [
              {"stage": "S5", "match": "gate A decision cannot be assembled", "decision": "x", "by": "human"}]}, "S5")[0] != [])
    scratch = source.replace('block = f"gate {self.gate} decision cannot be assembled"\n            self.add(check, FACTORY_DEFECT, f"{block} — ',
                             'block = f"gate {self.gate} decision cannot be assembled"\n            self.add(check, FACTORY_DEFECT, f"the gate {self.gate} decision cannot even be assembled: ', 1)
    check("control: the scratch copy really differs", scratch != source)
    scratch_tree = ast.parse(scratch)
    cut = [n for n in ast.walk(scratch_tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "add" and any(c.args and _template(c.args[0]) == "{block}" for c in waiver_calls(n))
           and "cannot even be assembled" in _template(n.args[2])]
    check("control: the static proof FAILS on the planted message that no longer opens with {block}",
          bool(cut) and all("{block}" not in norm(_template(n.args[2])) for n in cut))


# --- t-256 (spec t-227 section 0d): O4 the leftover `raise`, O6 the two card lines ---------------------------

def test_t256_o6_the_none_card_prints_the_token_for_each_case_it_names() -> None:
    root = cmp2_story("qa-gate-t256-none-", rewritten=False)
    try:
        card = none_card_of(root)
        shown = card["cases"][:gate_preflight.LIST_LIMIT]
        check_eq("the card names its cases (the packet and the applier both read them)", len(card["cases"]), 15)
        for case_id in shown:
            check_in(f"O6: the card prints the line to write for {case_id[-6:]}", f"`{case_id}: accept as blocked`", card["fix"])
        check_in("O6: the rest are counted, in the same form", "and 9 more of the same form", card["fix"])
        check_not_in("O6: not the old words, which applied nothing", "accept them as blocked", card["fix"])
        check_in("O6: the person's word still passes it (the block is the lead, t-241), as a line they write (t-357)",
                 f"write `{card['id']}: accept` with your reason", card["fix"])
        check_eq("O6: and the block it passes is the card's lead", [d["block"] for d in card["waives"]], [NONE_BLOCK[:60]])
        check("O6: the message still opens with the lead (the tripwire's invariant)", card["message"].startswith(NONE_BLOCK))
    finally:
        cleanup(root)
    # one case: no `and N more`
    root = cmp2_story("qa-gate-t256-one-", rewritten=False, base=False,
                      extra=[(1, "TS-1", [_pc("PC-1", "data", "x", [], "needs the preview stand")])])
    try:
        card = none_card_of(root)
        check_in("O6: one case, one line", f"`{cmp2_case_id(1)}: accept as blocked` — S5 then reports", card["fix"])
        check_not_in("O6: and no `more`", "more of the same form", card["fix"])
    finally:
        cleanup(root)


def test_t256_o4_a_raise_that_is_still_there_at_gate_a_is_the_factorys_to_repair() -> None:
    """The designer writes `unknown` with the ref `raise` and the S4 exit raises the question; a `raise` left at the
    gate would show the person a Then that waits for an answer nobody asked them for."""
    root = story("qa-gate-t256-raise-", with_fixes=False)
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        cases = task_root / "work" / "test-cases" / "workflows"

        def case(cid, oracles) -> None:
            (cases / f"{cid}.md").write_text(f"---\nid: {cid}\nplan_row: TS-1\nthen_oracles: {json.dumps(oracles)}\n---\n\n"
                                             "## Then\n1. a.\n2. b.\n", encoding="utf-8")
        case("TC-002", [{"then": 1, "source": "ac", "ref": "R-1"}, {"then": 2, "source": "unknown", "ref": "raise"}])
        case("TC-003", [{"then": 1, "source": "unknown", "ref": "Q7"}, {"then": 2, "source": "ac", "ref": "R-1"}])
        (cases / "TC-004.md").write_text("---\nid: TC-004\nplan_row: TS-1\n---\n\n## Then\n1. a.\n", encoding="utf-8")
        links = json.loads((task_root / "state" / "story-case-links.json").read_text(encoding="utf-8"))
        for cid in ("TC-002", "TC-003", "TC-004"):   # the rehearsal reads the PINNED versions
            links["links"].append({"case_id": cid, "version": "cv_x", "path": f"work/test-cases/workflows/{cid}.md"})
        (task_root / "state" / "story-case-links.json").write_text(json.dumps(links), encoding="utf-8")
        found = by_check(gate_preflight.run(task_root, "A"), "unraised_questions")
        check_eq("O4: exactly the case with a `raise` left is a finding (a Q-n and a legacy case are not)",
                 [(f["class"], f["where"]) for f in found], [(gate_preflight.FACTORY_FIXABLE, "TC-002")])
        check_in("the message opens with its block and names the Then", "question left unraised - TC-002: Then 2 says `unknown` with the ref `raise`",
                 found[0]["message"])
        check_in("the door is the factory's own step, which raises it and re-pins (no designer dispatch) - in words (t-357)",
                 "the factory raises the question and re-pins the case itself (no designer dispatch)", found[0]["fix"])
        check_not_in("t-357: no script and no flag", "critic_rollcall.py", found[0]["fix"])
        check_in("...and a person's word passes it, as a line they write", f"write `{found[0]['id']}: accept` with your reason", found[0]["fix"])
        check_eq("...for the block the message opens with", found[0]["waives"],
                 [{"block": "question left unraised", "stage": "S5", "option": "accept"}])
        check_eq("the rehearsal is not ready while it stands", gate_preflight.run(task_root, "A")["gate_ready"], False)
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "question left unraised", "decision": "go on",
                                        "at": "2026-10-01T10:00:00", "by": "human"}]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("a person's word records the pass and the block is not raised again",
                 by_check(gate_preflight.run(task_root, "A"), "unraised_questions"), [])
    finally:
        cleanup(root)


# --- t-357 (the owner's rule of 02.10): a person is never shown a script name, a flag or an exit code -------------

def _owner_rule_offences(text: str) -> list:
    """The shapes of `references/human-text.json` the owner's list names, found in a text of ours: the script name, the
    flag and the exit code. Checked by the shared checker (`human_text.problems`), never by a pattern of this file."""
    import human_text
    plugin = {path.name for path in SCRIPTS.glob("*.py")}
    rules = {item.get("id"): item for item in human_text.rules().get("forbidden") or []}
    out = [p["rule"] for p in human_text.problems(text, kind="report") if p["rule"] in ("flag", "exit_code")]
    # a `.py` that is the PERSON's file (a changed file of their repository, a test of theirs) is theirs to see; a
    # script of this plugin is not - the same line `message_offences` draws below. EVERY match of the shared pattern is
    # looked at (`problems` reports the first of a rule only, and the first may be the person's own file).
    if any(m.group(0) in plugin for m in re.finditer(str(rules["script_name"]["pattern"]), text)):
        out.insert(0, "script_name")
    return out


def test_t357_the_door_of_a_finding_is_a_line_in_words_never_a_command() -> None:
    """`Rehearsal.waiver_command` and `card_door`: the words, the id the finding is listed under, the block as data."""
    root = story("qa-gate-t357-door-")
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        words = r.waiver_command("some block", "S4")
        check_eq("the door: the word of the data file and the id slot, in plain words",
                 words, "to pass this check anyway, write `<check-id>: accept` with your reason")
        check_eq("handed: the word of the data file for `handed`, never the option's own name",
                 gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / "TP1-15045", "A").waiver_command(
                     "executor unavailable: x", "S5", "handed"), "to run it yourself, write `<check-id>: run`")
        r.add("probe", gate_preflight.PERSON_DECIDES, "a block of its own: what is wrong", words)
        r.add("probe", gate_preflight.PERSON_DECIDES, "a second block: what else", r.waiver_command("a second block"))
        check_eq("`add` replaces the slot with the finding's own id (the id is born there): first and second",
                 [f["fix"] for f in r.findings],
                 ["to pass this check anyway, write `probe-1: accept` with your reason",
                  "to pass this check anyway, write `probe-2: accept` with your reason"])
        check_eq("the block the line passes is data on the finding, with its stage (normalised, cut at 60)",
                 [f["waives"] for f in r.findings],
                 [[{"block": "some block", "stage": "S4", "option": "accept"}],
                  [{"block": "a second block", "stage": "S5", "option": "accept"}]])
        r.add("probe", gate_preflight.PERSON_DECIDES, "no door here", "just words")
        check_eq("a finding with no door carries no `waives`", "waives" in r.findings[-1], False)
        r.waiver_command("never added")
        r.add("probe", gate_preflight.PERSON_DECIDES, "a door asked for and then dropped by an override", "x")
        check_eq("a door asked for before an `add` belongs to THAT add (here: taken, not carried over to the next)",
                 [f["waives"][0]["block"] for f in r.findings if "waives" in f], ["some block", "a second block",
                                                                                   "never added"])
        check_not_in("no id slot is left in any text", "<check-id>", json.dumps([f["fix"] + f["message"] for f in r.findings]))
        # a story whose word list cannot be read: the door is still words, and still in the text (FR-41, FR-57)
        import hooklib
        real = hooklib.load_ref_json
        hooklib.load_ref_json = lambda name: {}
        try:
            dark = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / "TP1-15045", "A").waiver_command("b")
        finally:
            hooklib.load_ref_json = real
        check_eq("an unreadable word list: said in plain words, naming the id, no empty backquotes",
                 dark, "to pass this check anyway, say so in your own words, naming `<check-id>`, with your reason")
        for text in (words, dark):
            check_eq("and neither is a script, a flag or an exit code", _owner_rule_offences(text), [])
        check_in("NEGATIVE control: the checker is awake - the command this replaced is caught",
                 "script_name", _owner_rule_offences('waiver.py --task T --stage S5 --block "b" --decision "<your words>"'))
    finally:
        cleanup(root)


def test_t357_the_stand_gap_cards_of_gate_a_are_pointed_at_in_words() -> None:
    """The two findings that point at a stand-gap card (a precondition, a reporter) said "apply (...), theirs, handed
    (...) or accept" and a `waiver.py` line. Now: the card is the door, its words are the data file's."""
    root = story("qa-gate-t357-card-")
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        for returncode, said in ((1, "the run ended with an error"), (0, "the run ended normally"), (None, "")):
            r.findings.clear()
            r.stand_gaps.clear()
            r._reporter_card("s5_reporter", "api", ["TC-1"], "pytest", "tests/test_a.py::test_x",
                             {"why": "no report file was written", "returncode": returncode, "stdout": "", "stderr": ""},
                             ["pytest"])
            card, gap = r.findings[0], r.stand_gaps[0]
            check_eq(f"reporter (exit {returncode}): the finding points at the card and says how to answer, in words",
                     card["fix"], "answer the card: write the line it shows, with one of the words it lists")
            check_eq("...and the block it passes is data, option `any` (the word picks the option)",
                     card["waives"], [{"block": "stand gap: RP-api", "stage": "S5", "option": "any"}])
            check_eq(f"the gap's own sentence names the error in words, never `exit {returncode}`: {said or 'nothing'}",
                     ((said in gap["what"]) if said else ("the run ended" not in gap["what"]), "exit " in gap["what"]),
                     (True, False))
            check_eq("...so the card's missing line breaks no rule of the owner's list", _owner_rule_offences(gap["what"] + card["fix"]), [])
        # t-357 F5: the finding says the gap in words and by the card's own name - never by the block key - and a recorded
        # word still drops it (the block is matched from the finding's `waives`)
        r2 = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        args = ("pytest", "tests/test_a.py::test_x", {"why": "no report file was written", "returncode": 1, "stdout": "", "stderr": ""}, ["pytest"])
        r2._reporter_card("s5_reporter", "api", ["TC-1"], *args)
        first = r2.findings[0]
        # B-414 R1: a reporter gap is a LEVEL gap - the pointer names it by its tests, the way its card heads it, whatever else
        # the case holds
        check_eq("F5: a level gap is named by its tests, the way its card heads it",
                 first["message"].split(" — one existing test")[0], "the api tests")
        check_not_in("F5: no block key in the text a person reads", "stand gap: RP-", first["message"] + first["fix"])
        r2._reporter_card("s5_reporter", "web", ["TC-1"], *args)
        check_eq("F5: a second level gap over the SAME case: each keeps its own tests' name - one gap, one name",
                 [f["message"].split(" — one existing test")[0] for f in r2.findings], ["the api tests", "the web tests"])
        check("F5: and the word still passes the finding (the block is matched from `waives`)",
              all(_passes(f["message"], f["waives"][0]["block"], "S5") for f in r2.findings))
        pipeline = json.loads((root / "qa-factory" / "artifacts" / "TP1-15045" / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "stand gap: RP-api", "decision": "accept - ok", "by": "human"}]
        r3 = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / "TP1-15045", "A")
        r3.pipeline = pipeline
        r3._reporter_card("s5_reporter", "api", ["TC-1"], *args)
        check_eq("F5: a recorded word for the gap's block drops the finding although its text never spells the block", r3.findings, [])
        old = "api writes no machine-readable report the factory can read (no report file was written; exit 1 on tests/a.py::t)"
        check_in("NEGATIVE control: the sentence this replaced is caught", "exit_code", _owner_rule_offences(old))
        check_not_in("t-357: the pytest cure names no flag (the runner already asks for a JUnit report itself)", "--junitxml",
                     r.stand_gaps[0]["remedy"]["change"])
    finally:
        cleanup(root)


def test_b220_p2_the_reporter_card_carries_what_it_offers_and_whose_command_it_is() -> None:
    """The card's `remedy` carries two UNPRINTED fields for the answer reader (`gate_brief.read_stand_gap_answers`): `profile`
    (whose command a `command` line is about) and `offers` (the options this card takes). `apply` (`change`) only for a cure that is
    ONE change of the command (a row of report-cures.json with `add_argv`: vitest, dotnet - the others need a package, a config edit
    or an environment variable), and `command` - BOTH only while `probe_answers.live` is true (data; false in this release, t-409 H1)."""
    import contract as C
    import gate_brief
    import report_cures
    root = story("qa-gate-b220-offers-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        bad = {"why": "no report file was written", "returncode": 0, "stdout": "", "stderr": ""}

        def offers(launch: list, profile: str = "api") -> dict:
            r = gate_preflight.Rehearsal(task_root, "A")
            r._reporter_card("s5_reporter", profile, ["TC-1"], "none", "tests/a", bad, launch, argv=launch)
            return r.stand_gaps[0]["remedy"]

        rows = (("karma (a package and a config edit)", ["npx", "karma", "start"]), ("jest (a package)", ["npx", "jest"]),
                ("playwright (an environment variable)", ["npx", "playwright", "test"]), ("an unknown command", ["make", "check"]),
                ("pytest (a diagnosis, there is no flag to add)", ["poetry", "run", "pytest"]),
                ("vitest (its own reporter, one change)", ["npx", "vitest", "run"]), ("dotnet (its logger, one change)", ["dotnet", "test"]),
                ("vitest with the cure ALREADY in the command", ["npx", "vitest", "run", "--reporter=junit", "--outputFile={report_path}"]))
        # t-409 H1, the world of this release: `live` is false, so NOTHING that no code executes is offered - `change` included,
        # whatever the cure table holds (FR-9: `change` was recorded as a waiver that closed the card and changed nothing)
        for label, launch in rows:
            check_eq(f"H1 (live false): {label}: exactly `myself`, `run`, `accept`", offers(launch)["offers"], ["theirs", "handed", "accept"])
        check_eq("the card says whose command it is, for the answer reader", offers(["dotnet", "test"], "web")["profile"], "web")
        check_eq("the remedy is still valid by the contract, with the two extra fields", C.remedy_errors(offers(["dotnet", "test"])), [])
        check_eq("the shipped form is not live: no card offers `command` or `change` today",
                 [o for o in offers(["dotnet", "test"])["offers"] if o in ("command", "apply")], [])
        real_answers, real_path = gate_brief.probe_answers, report_cures.cures_path
        try:
            # the other world, so the switch is not dead: `live` true keeps the offers the code had before t-409
            gate_brief.probe_answers = lambda: {"live": True, "command": {"word": "command"}, "reporter_accept": "", "problem": ""}
            check_eq("H1 (live true): a LIVE `command` form is offered first", offers(["npx", "karma"])["offers"], ["command", "theirs", "handed", "accept"])
            check_eq("H1 (live true): and beside `change` when the cure is one change of the command (dotnet)", offers(["dotnet", "test"])["offers"],
                     ["command", "apply", "theirs", "handed", "accept"])
            check_eq("H1 (live true): vitest too", offers(["npx", "vitest", "run"])["offers"], ["command", "apply", "theirs", "handed", "accept"])
            check_eq("H1 (live true): a cure that needs a package is still not `change`", offers(["npx", "jest"])["offers"], ["command", "theirs", "handed", "accept"])
            gate_brief.probe_answers = lambda: (_ for _ in ()).throw(RuntimeError("the vocabulary is gone"))
            check_eq("a vocabulary that cannot be read offers LESS, never more: neither `command` nor `change`", offers(["dotnet", "test"])["offers"], ["theirs", "handed", "accept"])
            gate_brief.probe_answers = lambda: {"live": True, "command": {"word": "command"}, "reporter_accept": "", "problem": ""}
            report_cures.cures_path = lambda: root / "no-such-cure-table.json"
            check_eq("H1 (live true): a cure table that cannot be read offers LESS: no `change`", offers(["dotnet", "test"])["offers"], ["command", "theirs", "handed", "accept"])
        finally:
            gate_brief.probe_answers, report_cures.cures_path = real_answers, real_path
    finally:
        cleanup(root)


def _tests_folder(*names: str) -> Path:
    root = temp_dir("qa-first-test-")
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x\n", encoding="utf-8")
    return root


def test_b_deps_first_test_file_recognises_a_test_through_the_one_leaf() -> None:
    """B-407 B-deps B8, K-D-3: the names are `test_files.is_test_for("name", ...)`, the usual names of the markers file; the skipped
    trees and the sorted order are kept (E-D-6); when the names cannot be read the answer is TODAY's globs, exactly."""
    import test_files
    seen = []
    try:
        for name in ("FooTest.java", "foo_test.go", "FooTests.cs", "test_a.py", "a_test.py", "a.spec.ts", "a.test.js", "FooSpec.scala"):
            root = _tests_folder("readme.md", name)
            seen.append(root)
            found = gate_preflight.first_test_file(root)
            check_eq(f"K-D-3: {name} is found", Path(found).name if found else "", name)
        for name in ("Contest.cs", "Latest.java", "AUDIT.java", "testing.py", "helpers.py"):
            root = _tests_folder(name)
            seen.append(root)
            check_eq(f"K-D-3: {name} is not a test", gate_preflight.first_test_file(root), "")
        for name in ("test_data.json", "test_notes.md", "x.spec.json", "test"):
            root = _tests_folder(name)
            seen.append(root)
            check_eq(f"FIX 1: {name} has a test name but is no code file: it is never RUN as the one test", gate_preflight.first_test_file(root), "")
        # the extensions unknown (the markers readable, `code_extensions` empty): the leaf's own floor decides, never a refusal
        original = test_files.markers
        known, why = original()
        test_files.markers = lambda: (dict(known, code_extensions=[]), why)
        try:
            for name, expect in (("test_a.py", "test_a.py"), ("FooTest.java", "FooTest.java"), ("test_data.json", ""), ("test", "")):
                root = _tests_folder(name)
                seen.append(root)
                found = gate_preflight.first_test_file(root)
                check_eq(f"FIX 1: with `code_extensions` unknown, {name} is decided by CODE_EXTENSION_FLOOR", Path(found).name if found else "", expect)
        finally:
            test_files.markers = original
        root = _tests_folder("src/Main.java", "z_test.go", "node_modules/a_test.go", "vendor/b_test.go", ".hidden/c_test.go", "pkg/a_test.go", "pkg/Zeta.java")
        seen.append(root)
        check_eq("E-D-6: the sorted order is kept (files of a folder first, then folders by name)",
                 Path(gate_preflight.first_test_file(root)).relative_to(root).as_posix(), "z_test.go")
        (root / "z_test.go").unlink()
        check_eq("E-D-6: the skipped trees (node_modules, vendor, hidden) are not entered: the next one is pkg/a_test.go",
                 Path(gate_preflight.first_test_file(root)).relative_to(root).as_posix(), "pkg/a_test.go")
        check_eq("a folder that does not exist has no test file", gate_preflight.first_test_file(root / "nowhere"), "")
        # E-D-6: the names cannot be read -> today's rule (REPORTER_TEST_GLOBS), no more and no less
        original = test_files.markers
        test_files.markers = lambda: ({}, "unreadable")
        try:
            today = ("test_a.py", "a_test.py", "a.spec.ts", "a.spec.tsx", "a.spec.js", "a.test.ts", "a.test.tsx", "a.test.js", "FooTests.cs", "FooTest.cs")
            for name in today:
                root = _tests_folder("readme.md", name)
                seen.append(root)
                found = gate_preflight.first_test_file(root)
                check_eq(f"E-D-6 floor: {name} is found by today's globs when the names cannot be read", Path(found).name if found else "", name)
            import fnmatch
            check_eq("FIX 2: `*Test.cs` is the glob that matched `Contest.cs` where fnmatch ignores case (Windows); the floor is case-sensitive "
                     "on every platform", (fnmatch.fnmatchcase("Contest.cs", "*Test.cs"), fnmatch.fnmatchcase("FooTest.cs", "*Test.cs")), (False, True))
            for name in ("foo_test.go", "FooTest.java", "FooSpec.scala", "readme.md", "Contest.cs"):
                root = _tests_folder(name)
                seen.append(root)
                check_eq(f"E-D-6 floor: {name} is NOT found by today's globs (the widening is the markers', not the floor's)",
                         gate_preflight.first_test_file(root), "")
        finally:
            test_files.markers = original
        root = _tests_folder("foo_test.go")
        seen.append(root)
        check("E-D-6 control: with the names readable again the same folder has its test", bool(gate_preflight.first_test_file(root)))
    finally:
        for root in seen:
            cleanup(root)


def test_t357_render_says_whose_it_is_in_words_and_keeps_the_id() -> None:
    result = {"gate": "A", "task": "T-1", "next_stage": "S5", "can_proceed": False,
              "by_class": {gate_preflight.FACTORY_FIXABLE: 1, gate_preflight.FACTORY_DEFECT: 1, gate_preflight.PERSON_DECIDES: 1},
              "findings": [
                  {"id": "cases-1", "check": "cases", "class": gate_preflight.FACTORY_FIXABLE, "message": "m1",
                   "fix": "the factory re-pins the whole batch at the bytes on disk"},
                  {"id": "stage_guard-1", "check": "stage_guard", "class": gate_preflight.FACTORY_DEFECT, "message": "m2",
                   "fix": "to pass this check anyway, write `stage_guard-1: accept` with your reason"},
                  {"id": "vcs-1", "check": "vcs", "class": gate_preflight.PERSON_DECIDES, "message": "m3", "fix": ""}],
              "info": []}
    text = gate_preflight.render(result)
    check_in("the check id stays - it is the key a person's line names", "[stage_guard-1] m2", text)
    check_in("the fix is words", "fix: to pass this check anyway, write `stage_guard-1: accept` with your reason", text)
    for title in ("The factory repairs these before the gate (1):", "The factory cannot repair these (1):",
                  "Questions for you at this gate (1):"):
        check_in(f"the heading is words: {title}", title, text)
    check_not_in("t-357 F6: no heading promises a word door - a defect with no door (`role_permissions`) sits under the same heading",
                 "your word passes", gate_preflight.render(dict(result, findings=result["findings"] + [
                     {"id": "role_permissions-1", "check": "role_permissions", "class": gate_preflight.FACTORY_DEFECT,
                      "message": "a role of S5 is told to do what its charter does not allow",
                      "fix": "the charter is the factory's own file; record it as a finding about the factory"}])))
    for klass in (gate_preflight.FACTORY_FIXABLE, gate_preflight.FACTORY_DEFECT, gate_preflight.PERSON_DECIDES):
        check_not_in(f"t-357: the class name `{klass}` is the code's, not shown to a person", klass, text)
    check_eq("and the whole text breaks no rule of the owner's list", _owner_rule_offences(text), [])


def test_t357_no_literal_of_any_add_or_note_in_the_source_names_a_script_or_a_flag() -> None:
    """THE STATIC HALF of the sweep: the runs reach the texts the fixtures reach; the source holds the rest. Every string
    that lands in the message or the fix of an `add()` (and in a `note()`), values left as `{<source>}`."""
    import ast
    source = (SCRIPTS / "gate_preflight.py").read_text(encoding="utf-8")
    plugin = {path.name for path in SCRIPTS.glob("*.py")}
    sites = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("add", "note"):
            args = list(node.args[2:4] if node.func.attr == "add" else node.args[1:2])
            args += [k.value for k in node.keywords if k.arg in ("message", "fix")]
            sites.extend((node.lineno, _template(a)) for a in args)
    check("the census finds the texts of the add() and note() calls", len(sites) > 100)
    offences = [(line, text[:80]) for line, text in sites
                if any(name in text for name in plugin) or re.search(r"(?<![\w-])--[A-Za-z]", text)
                or re.search(r"(?<![\w])exit (?:code )?[0-9]+", text)]
    check_eq("STATIC: no text of an add() or note() names a script of the plugin, a flag or an exit code", offences, [])
    planted = [(0, _template(ast.parse('self.add(c, k, "m", "`controller.py --operation rework`")').body[0].value.args[3])),
               (0, _template(ast.parse('self.add(c, k, "the run ended (exit 1)")').body[0].value.args[2]))]
    check_eq("control: the same scan finds a planted script, flag and exit code",
             [bool(any(name in text for name in plugin) or re.search(r"(?<![\w-])--[A-Za-z]", text)
                   or re.search(r"(?<![\w])exit (?:code )?[0-9]+", text)) for _line, text in planted], [True, True])


def test_t357_every_text_of_every_run_of_this_file_obeys_the_owners_rule() -> None:
    """THE CLASS SWEEP: every finding (message and fix) and every INFO line any run of this file produced is held to
    the owner's rule - the handful of sites a test names is not the class. Run last: the record is what the file did.
    The texts a role or a tool wrote and the rehearsal only quotes (`quoted`) are the quoted party's: they stay."""
    offences = []
    for site, kind, text in TEXTS_SEEN:
        for rule in _owner_rule_offences(text):
            offences.append((site, kind, rule, text[:90]))
    check("the sweep saw a good many texts (it is not recording nothing)", len(TEXTS_SEEN) > 150)
    check_eq("SWEEP: no finding, fix or INFO line of any run names a script, a flag or an exit code", offences, [])
    # NEGATIVE control: the same loop over a planted record must find it, or the key above proves nothing
    planted = [("planted:1", "fix", 'waiver.py --task T --stage S5 --block "b" --decision "x"'),
               ("planted:2", "message", "the run ended (exit 2)"), ("planted:3", "fix", "add --junitxml to the command")]
    check_eq("control: a planted script, exit code and flag are each found",
             [(site, rule) for site, _k, text in planted for rule in _owner_rule_offences(text)],
             [("planted:1", "script_name"), ("planted:1", "flag"), ("planted:2", "exit_code"), ("planted:3", "flag")])


def test_b414_a_stand_gap_override_passes_only_the_finding_of_exactly_its_gap() -> None:
    """R15: `waiver.split_overridden` matches by substring, so `stand gap: PC-1` also passed the finding of `PC-10`, and `stand gap: RP-web`
    that of `RP-webapp`: a person's word about one gap passed another. `add` now shows it a view in which a `stand gap:` override is kept
    only when its id is EXACTLY one the finding's own doors name; every other override is unchanged."""
    root = story("qa-gate-b414-r15-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        path = task_root / "pipeline.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [
            {"stage": "S5", "match": "stand gap: PC-1", "decision": "accept - ok", "by": "human"},
            {"stage": "S5", "match": "stand gap: RP-web", "decision": "accept - ok", "by": "human"},
            {"stage": "S5", "match": "some other block", "decision": "ok", "by": "human"}]
        path.write_text(json.dumps(pipeline), encoding="utf-8")

        def raised(gap_id: str) -> bool:
            r = gate_preflight.Rehearsal(task_root, "A")
            r.stand_gaps.append({"id": gap_id, "case": "TC-1", "scope": "case"})
            r.add("case_preconditions", gate_preflight.PERSON_DECIDES, f"{gate_preflight.GAP_SLOT} — a stand gap", r.card_door(gap_id),
                  gap=gap_id, gap_case="TC-1")
            return bool(r.findings)
        check_eq("R15: the finding of exactly PC-1 is passed by `stand gap: PC-1`", raised("PC-1"), False)
        check_eq("R15: the finding of PC-10 is NOT passed by it (the old substring match passed it)", raised("PC-10"), True)
        check_eq("R15: the finding of exactly RP-web is passed", raised("RP-web"), False)
        check_eq("R15: the finding of RP-webapp is NOT passed by `stand gap: RP-web`", raised("RP-webapp"), True)
        check_eq("R15: a qualified id is its own gap: `PC-1@TC-007` is not passed by `stand gap: PC-1`", raised("PC-1@TC-007"), True)
        r = gate_preflight.Rehearsal(task_root, "A")
        r.add("other", gate_preflight.PERSON_DECIDES, "some other block is open", "x")
        check_eq("R15: an override that is not a stand gap's is unchanged: a finding whose text holds it is still passed", r.findings, [])
        check_eq("R15: the view keeps the other overrides whole",
                 [o["match"] for o in r._exact_gap_view([{"block": "stand gap: PC-1"}])["stage_overrides"]], ["stand gap: PC-1", "some other block"])
    finally:
        cleanup(root)


def test_b414_a_shared_precondition_id_is_qualified_in_the_rehearsal_and_its_door() -> None:
    root = story("qa-gate-b414-r14-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        check_eq("precondition_gap_id: an id one case declares is its own", gate_preflight.precondition_gap_id("TC-007", "PC-1", set()), "PC-1")
        check_eq("precondition_gap_id: a shared one is qualified with `@<case>`", gate_preflight.precondition_gap_id("TC-007", "PC-1", {"PC-1"}), "PC-1@TC-007")
        folder = task_root / "work" / "test-cases" / "workflows"
        item = {"id": "PC-1", "kind": "feature_flag", "what": "flag on", "partitions": [], "remedy": {"kind": "flag", "where": "a.yaml:1", "change": "on"},
                "check": {"http": {"path": "/v1/x", "status": 200, "json_path": "f", "equals": True}}}
        for case in ("TC-007", "TC-008"):
            (folder / f"{case}.md").write_text(f"---\nid: {case}\npreconditions: {json.dumps([item])}\n---\n\n## When\n1. x\n", encoding="utf-8")
        (task_root / "state" / "story-case-links.json").unlink()        # the cases are read from the authoring folder
        check_eq("shared_precondition_ids reads the raw ids of every case file", gate_preflight.shared_precondition_ids(task_root), {"PC-1"})
        original = gate_preflight.Rehearsal._check_one_precondition
        gate_preflight.Rehearsal._check_one_precondition = lambda self, item, ctx: ("unmet", "the flag is off")
        try:
            r = gate_preflight.Rehearsal(task_root, "A")
            r.check_case_preconditions()
        finally:
            gate_preflight.Rehearsal._check_one_precondition = original
        check_eq("R14: the rehearsal's gaps are `PC-1@TC-007` and `PC-1@TC-008`, the raw id kept, scope `case`, the check carried",
                 sorted((g["id"], g["pc_id"], g["scope"], next(iter(g["check"]))) for g in r.stand_gaps),
                 [("PC-1@TC-007", "PC-1", "case", "http"), ("PC-1@TC-008", "PC-1", "case", "http")])
        check_eq("R14: each finding's door is its own qualified gap", sorted(f["waives"][0]["block"] for f in r.findings), ["stand gap: PC-1@TC-007", "stand gap: PC-1@TC-008"])
    finally:
        cleanup(root)


def test_b426_d4_the_findings_of_two_cases_keep_their_order_and_the_gap_ids() -> None:
    """B-426 D4, characterisation (S9): the whole output of `check_case_preconditions` for two cases, pinned BEFORE the function was
    split into helpers. TC-007 holds a broken item (PC-1), a carded one (PC-2), a prose `none` one (PC-3) and an open one (PC-8); TC-008
    holds an open one (PC-5), one the case creates itself (PC-4) and one the stand's own account holds (PC-6). The order is per case:
    the defect, then the cards, then the question; after the last case the note, then the story-wide `none` card."""
    root = story("qa-gate-b426-d4-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        folder = task_root / "work" / "test-cases" / "workflows"

        def item(pid: str, kind: str, what: str, check: dict, **more) -> dict:
            return {"id": pid, "kind": kind, "what": what, "partitions": [], "check": check, **more}
        remedy = {"kind": "flag", "where": "a.yaml:1", "change": "on"}
        cases = {
            "TC-007": [item("PC-1", "env", "the runner account", {"env": "BROKEN_ONE"}),
                     item("PC-2", "feature_flag", "flag on", {"http": {"path": "/v1/x", "status": 200, "json_path": "f", "equals": True}},
                          remedy=remedy),
                     item("PC-3", "data", "a guardrail of another project", {"none": "no API lists guardrails of a project"}),
                     item("PC-8", "env", "an api key", {"env": "OPEN_ONE"}, partitions=["P-keyed"])],
            "TC-008": [item("PC-5", "env", "a second key", {"env": "OPEN_TWO"}),
                     item("PC-4", "data", "a row the case creates", {"case_seeds": "the case creates it"}),
                     item("PC-6", "account", "the stand's own account", {"stand_account": "default_user"})]}
        for case, items in cases.items():
            (folder / f"{case}.md").write_text(
                f"---\nid: {case}\npreconditions: {json.dumps(items)}\n---\n\n## Given\n| P-keyed | P-plain |\n\n## When\n1. x\n",
                encoding="utf-8")
        (task_root / "state" / "story-case-links.json").unlink()        # the cases are read from the authoring folder
        answers = {"PC-1": ("error", "OSError: refused"), "PC-2": ("unmet", "the flag is off"), "PC-3": ("uncheckable", "no machine can"),
                   "PC-8": ("uncheckable", "the key is not in an env file"), "PC-5": ("unmet", "the key is missing"),
                   "PC-4": ("seeded", ""), "PC-6": ("met", "")}
        original = gate_preflight.Rehearsal._check_one_precondition
        gate_preflight.Rehearsal._check_one_precondition = lambda self, item, ctx: answers[item["id"]]
        try:
            r = gate_preflight.Rehearsal(task_root, "A")
            r.check_case_preconditions()
        finally:
            gate_preflight.Rehearsal._check_one_precondition = original
        check_eq("B-426 D4: the findings in order, as (class, text[:60])",
                 [(f["class"], f["message"][:60]) for f in r.findings],
                 [(gate_preflight.FACTORY_DEFECT, "TC-007: 1 precondition(s) could not be checked on the stand "),
                  (gate_preflight.PERSON_DECIDES, "TC-007 — a stand gap (flag on): the exact change is known, s"),
                  (gate_preflight.PERSON_DECIDES, "TC-007: 1 of 2 partitions (P-keyed) need an api key — on thi"),
                  (gate_preflight.PERSON_DECIDES, "TC-008: the case needs a second key — on this stand 1 not me"),
                  (gate_preflight.PERSON_DECIDES, "preconditions no machine can check: 1 precondition of 1 case")])
        check_eq("B-426 D4: the stand gaps' ids, in order", [g["id"] for g in r.stand_gaps], ["PC-2"])
        check_eq("B-426 D4: the one note, after the last case: what is not asked (the seeded one and the stand's own account)",
                 [i["message"] for i in r.info if i["check"] == "case_preconditions"],
                 ["2 preconditions are not asked: 1 the case creates itself (TC-008), 1 is held by the stand's own account (TC-008)."])
    finally:
        cleanup(root)


def d12_digest(root: Path) -> str:
    """First 12 hex digits of the sha256 of everything `check_s5_runtime_probe` said on this story: each finding's class, message, fix,
    profile, detail and refusal (the `argv` of a derived probe names the temp folder, so only its flags are kept) and each note."""
    import hashlib
    result = cmp2_run(root, steps=("s5_runtime_probe",))
    said = [[f["class"], f["message"], f.get("fix"), f.get("profile"), f.get("detail"), f.get("refusal"),
             sorted(a for a in f.get("argv", []) if str(a).startswith("--"))] for f in by_check(result, "s5_runtime_probe")]
    said.append(info_of(result, "s5_runtime_probe"))
    return hashlib.sha256(json.dumps(said, sort_keys=True).encode("utf-8")).hexdigest()[:12]


D12_SAID = {
    "matched": "4f58b4abec3d", "mismatched": "f2db627722c8", "unknown": "ce1ecf7ff82a", "not_applicable": "f255014eff9a",
    "person_confirmed": "537dbd76c6fe", "a verdict outside the five": "d3e31b871631", "no verdict": "81aa00a9f272",
    "not a record": "9e9107fe563b", "unreadable": "38cb0cb95c65", "timed out": "cd7ff19cae63", "no candidate": "df32e01bc70b",
    "two candidates": "d5670d7e83af", "nothing to compare": "f08d0c086397", "no running container": "c6c3c616ca0e",
    "no checkout": "3bea2f853896"}   # GM2-2 O7 rewrite: `mismatched` and `no checkout` recomputed (their texts name the renamed repositories; was 7449cd3f0c4d / 12cd7159ae3c); the last two: the plain wording of the fix (EP1-24 F-5, EP1-24 F3 fix round);
    # "no running container": the refusal and the card name --no-container (EP1-28)


def test_t683_d12_every_exit_and_every_verdict_of_the_derived_probe_says_what_it_said() -> None:
    """t-683 D12 (I-pure): the characterisation `_derive_probe` is split against - one digest per way out of it. Captured on the tree
    BEFORE the split, so the five verdict branches, the foreign word, the three ways the probe gives none, and the five exits before
    the probe is run are the same sentences, classes, doors and flags afterwards."""
    def probe(record):
        return lambda argv: {"record": record}
    cases = {
        "matched": dict(),
        "mismatched": dict(probe=probe({"result": "mismatched", "comparisons": [
            {"file": "src/a.py", "container_sha256": "x", "local_sha256": "y"}]})),
        "unknown": dict(probe=probe({"result": "unknown", "error": "no expected revision"})),
        "not_applicable": dict(probe=probe({"result": "not_applicable", "reason": "nothing of the story is in the checkout"})),
        "person_confirmed": dict(probe=probe({"result": "person_confirmed"})),
        "a verdict outside the five": dict(probe=probe({"result": "MATCHED"})),
        "no verdict": dict(probe=probe({"result": "  "})),
        "not a record": dict(probe=lambda argv: {"record": [1]}),
        "unreadable": dict(probe=lambda argv: {"unreadable": "not json"}),
        "timed out": dict(probe=lambda argv: {"timed_out": True}),
        "no candidate": dict(candidates=lambda name: []),
        "two candidates": dict(candidates=lambda name: ["api-c", "ui-c"]),
        "nothing to compare": dict(compared=None),
        "no running container": dict(containers=()),
    }
    got = {}
    root = cmp2_story("qa-gate-d12-", config=probes_on)
    try:
        for label, options in cases.items():
            with stub_stand(**options):
                got[label] = d12_digest(root)
    finally:
        cleanup(root)

    def no_checkout(cfg):
        probes_on(cfg)
        for repo in cfg["implementation_repos"]:
            repo.pop("execution_profile_id")
        cfg["profiles"] = cfg["profiles"][:1]
    root = cmp2_story("qa-gate-d12-co-", config=no_checkout)
    try:
        with stub_stand():
            got["no checkout"] = d12_digest(root)
    finally:
        cleanup(root)
    check_eq("D12: what the derived probe said in each case, digest by digest (captured before the split)", got, D12_SAID)
    check_eq("D12: the fifteen ways are told apart (no two say the same)", len(set(got.values())), len(D12_SAID))


# --- GW1-27: the preconditions ask what the stand does not hold, and say where the answer goes -------------------------
# Killing test of each mutant (named, not run - D-0056): M-27.1 `account_role` takes the first of two -> test_manual_actor.py
# K-27.3; M-27.2 `_stand_account` back to `in roles` -> gw1_27_k1; M-27.3 `resolve_actor` back to `in roles` ->
# test_manual_actor.py K-27.3; M-27.4 the address read from `frontend_url` directly -> gw1_27_k5 (the record of the stand);
# M-27.5 `stand_frontend` on `env_error` -> `unmet` -> gw1_27_k6; M-27.6 the file out of the door -> gw1_27_k6; M-27.7 the door by
# `kind` -> gw1_27_k10; M-27.8 the `feature_flag` branch removed -> gw1_27_k11; M-27.9 the stand search of `stand_login_problem`
# back to `in roles` -> test_manual_actor.py K-27.3.
_GW_DOOR_TAIL = "or say it is not needed (S5 then reports it as not executed); or write `{case}: accept as blocked`."


def _gw_case(kind, check_, what="the case needs it"):
    return [{"id": "PC-1", "kind": kind, "what": what, "partitions": [], "legacy": check_, "rewritten": check_}]


def _gw_findings(items, config=None, env_lines=None, pipeline=None, rewritten=True, n=1) -> tuple:
    """(findings, info, root's cleanup is done) of the rehearsal step over ONE case that declares `items`."""
    root = cmp2_story("qa-gate-gw27-", base=False, extra=[(n, f"TS-{n}", items)], config=config, env_lines=env_lines,
                      pipeline=pipeline, rewritten=rewritten)
    try:
        result = cmp2_run(root, steps=("case_preconditions",))
        return by_check(result, "case_preconditions"), result["info"]
    finally:
        cleanup(root)


def _rename_default_user(cfg) -> None:
    roles = cfg["environments"][0]["credentials_by_role"]
    roles["default user"] = roles.pop("default_user")


def test_gw1_27_k1_k3_the_role_in_another_spelling_is_the_role_the_stand_holds() -> None:
    """14857 PC-1: the config says `default user`, the form teaches `default_user`; the gate asked about an account that was there."""
    found, info = _gw_findings(_gw_case("account", {"stand_account": "default_user"}), config=_rename_default_user)
    check_eq("K-27.1 `default_user` for a stand that writes `default user`, AUTH_* set: no finding", found, [])
    check_in("K-27.1 and it is counted as held by the stand's own account", "held by the stand's own account", info[0]["message"])
    found, _ = _gw_findings(_gw_case("account", {"stand_account": "Default-User"}), config=_rename_default_user)
    check_eq("K-27.3 `Default-User` is the same role", found, [])

    def twins(cfg):
        roles = cfg["environments"][0]["credentials_by_role"]
        roles["Admin"], roles["admin"] = "AUTH_USERNAME / AUTH_PASSWORD", "AUTH_USERNAME / AUTH_PASSWORD"
    found, _ = _gw_findings(_gw_case("account", {"stand_account": "ADMIN"}), config=twins)
    check_eq("K-27.3 two roles of one spelling and a third spelling: unmet, a question (a doubt is never an account)", len(found), 1)
    check_in("K-27.3 ... and it says which roles it could mean", "more than one account", found[0]["message"])
    found, _ = _gw_findings(_gw_case("account", {"stand_account": "admin"}), config=twins)
    check_eq("K-27.3 the exact key beside its twin is met", found, [])


def test_gw1_27_k2_default_is_the_stands_default_account() -> None:
    account = _gw_case("account", {"stand_account": "default"})
    found, _ = _gw_findings(account)
    check_eq("K-27.2 `default`, both AUTH_* keys set: no finding", found, [])
    found, _ = _gw_findings(_gw_case("account", {"stand_account": " default "}))
    check_eq("K-27.2 ` default ` is cut at the edges", found, [])
    found, _ = _gw_findings(account, env_lines=["AUTH_USERNAME=u"])
    check_eq("K-27.2 no secret: one question", len(found), 1)
    check_in("K-27.2 ... naming the missing key, never a value", "AUTH_PASSWORD", found[0]["message"])
    check_not_in("K-27.2 ... and not the key that is set", "AUTH_USERNAME", found[0]["message"])

    def own_keys(cfg):
        cfg["environment"].update({"user_key": "QA_LOGIN", "secret_keys": ["QA_PASS"]})
    found, _ = _gw_findings(account, config=own_keys, env_lines=["AUTH_USERNAME=u", "AUTH_PASSWORD=p", "QA_LOGIN=x"])
    check_in("K-27.2 the project's own keys are the ones looked up", "QA_PASS", found[0]["message"])

    def no_keys(cfg):
        cfg["environment"].pop("user_key")
        cfg["environment"].pop("secret_keys")
    found, _ = _gw_findings(account, config=no_keys)
    check_eq("K-27.2 without `environment.user_key` the keys are AUTH_USERNAME / AUTH_PASSWORD", found, [])
    found, _ = _gw_findings(account, config=lambda cfg: cfg.update(environments=[]))
    check_eq("K-27.2 `default` needs no row of a stand (POSITION: before the stand is looked up)", found, [])
    found, _ = _gw_findings(account, pipeline={"environment": ""})
    check_eq("K-27.2 ... nor a stand the story chose", found, [])


def test_gw1_27_k4_the_new_form_is_taught_and_validated() -> None:
    def line(spec):
        return json.dumps([{"id": "PC-1", "kind": "service", "what": "x", "check": {"stand_frontend": spec}}])
    check_eq("K-27.4 `stand_frontend` with its reason passes", gate_preflight.parse_preconditions(line("the case opens the page"))[1], [])
    for label, spec in (("empty", " "), ("not text", ["a"]), ("a number", 3)):
        errors = gate_preflight.parse_preconditions(line(spec))[1]
        check_eq(f"K-27.4 {label}: refused", len(errors), 1)
        check_in(f"K-27.4 {label}: by the name of the field", "check.stand_frontend", errors[0])
    check_in("K-27.4 the form teaches it", "stand_frontend", gate_preflight.PRECONDITION_FORM)
    check_in("K-27.4 and the closed list holds it", "stand_frontend", gate_preflight.PRECONDITION_CHECKS)


def test_gw1_27_k5_the_address_of_the_ui_is_read_by_the_one_reader() -> None:
    sentinel = "http://ui-sentinel.invalid:5173"
    ui = _gw_case("service", {"stand_frontend": "the case opens the page"})
    found, info = _gw_findings(ui)
    check_eq("K-27.5 the stand's entry carries the flat `frontend_url`: no finding", found, [])
    check_eq("K-27.5 and nothing is counted as held (only an account is)", info, [])

    def entry_frontend(cfg):
        entry = cfg["environments"][0]
        entry.pop("frontend_url")
        entry["frontend"] = {"url": sentinel}
    found, info = _gw_findings(ui, config=entry_frontend)
    check_eq("K-27.5 the record of the stand (`frontend.url`): no finding", found, [])
    check_not_in("K-27.5 the address is never printed", "ui-sentinel", json.dumps(info))

    def no_address(cfg):
        cfg["environments"][0].pop("frontend_url")
    found, _ = _gw_findings(ui, config=no_address)
    check_eq("K-27.5 no address: one question", len(found), 1)
    check_eq("K-27.5 ... the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
    check_in("K-27.5 ... says what is missing", "no address of this stand's UI is recorded", found[0]["message"])
    check_in("K-27.5 ... two stands: the door asks for the address itself (the one arm `stand-frontend` takes there; the file is named at "
             "one stand, see R2-F1)", "tell me the address itself", found[0]["fix"])
    check_not_in("K-27.5 the key of the config is not in the text a person reads", "environment.frontend", found[0]["message"] + found[0]["fix"])
    check_in("K-27.5 ... it is in the `remedy` the conductor reads", "frontend.url", found[0].get("remedy", ""))

    def block_only(cfg):
        cfg["environments"] = []
        cfg["environment"]["frontend"] = {"url_key": "UI_ADDRESS"}
    found, _ = _gw_findings(ui, config=block_only, env_lines=["AUTH_USERNAME=u", "AUTH_PASSWORD=p", f"UI_ADDRESS={sentinel}"])
    check_eq("K-27.5 `environments: []` and the block's `url_key` set: no finding (the block is the stand)", found, [])
    found, _ = _gw_findings(ui, config=block_only, env_lines=["AUTH_USERNAME=u", "AUTH_PASSWORD=p"])
    check_eq("K-27.5 ... the key set but the variable absent: a question", len(found), 1)
    found, _ = _gw_findings(ui, pipeline={"environment": ""})
    check_eq("K-27.5 two stands, none chosen: one finding", len(found), 1)
    check_eq("K-27.5 ... the factory's, never the person's", found[0]["class"], gate_preflight.FACTORY_DEFECT)


def test_gw1_27_k6_a_question_about_an_account_says_where_and_gives_three_answers() -> None:
    ghost = _gw_case("account", {"stand_account": "ghost"})
    found, _ = _gw_findings(ghost)
    check_eq("K-27.6 a role the stand does not hold: one question", len(found), 1)
    text = found[0]["message"] + " " + found[0]["fix"]
    check_in("K-27.6 it names the file the runner reads", "testproject1_test_harness/.env", found[0]["fix"])
    check_in("K-27.6 ... says it may be not needed", "not needed", found[0]["fix"])
    check_in("K-27.6 ... and the third answer", "`" + cmp2_case_id(1) + ": accept as blocked`", found[0]["fix"])
    for role in ("default_user", "project_scoped_user", "auditor"):
        check_in(f"K-27.6 the stand's accounts are named: {role}", f"`{role}`", found[0]["message"])
    check_not_in("K-27.6 no value", "not-printed-1", text)
    check_not_in("K-27.6 no value of the login", "admin@example.invalid", text)
    held = gate_preflight.Rehearsal._env_names

    def broken(self, files):
        raise OSError("the env file is a folder")
    gate_preflight.Rehearsal._env_names = broken
    try:
        found, _ = _gw_findings(ghost)
    finally:
        gate_preflight.Rehearsal._env_names = held
    check_eq("K-27.6 an env file that cannot be read is the factory's, not a question",
             [f["class"] for f in found], [gate_preflight.FACTORY_DEFECT])


def test_gw1_27_k7_one_paragraph_on_the_none_card_and_the_limit_is_as_before() -> None:
    paragraph = "an account named here: put its login and password in testproject1_test_harness/.env, never in the chat"

    def none_cases(count):
        root = cmp2_story("qa-gate-gw27-k7-", base=False, rewritten=False,
                          extra=[(n, f"TS-{n}", _gw_case("account", {"none": "the second user is not on this stand"}))
                                 for n in range(1, count + 1)])
        try:
            return [f for f in by_check(cmp2_run(root, steps=("case_preconditions",)), "case_preconditions")
                    if f["message"].startswith("preconditions no machine")]
        finally:
            cleanup(root)
    six = none_cases(6)
    check_eq("K-27.7 six `none` cases with an account: one card", len(six), 1)
    check_eq("K-27.7 ... the paragraph once", six[0]["fix"].count(paragraph), 1)
    check_in("K-27.7 ... naming the rewrite and the second rehearsal", "the case designer rewrites this precondition to that role, then I rehearse again", six[0]["fix"])
    check_not_in("K-27.7 six ids are named, none left over", " more of the same form", six[0]["fix"])
    seven = none_cases(7)
    check_in("K-27.7 at seven: `and 1 more` as before", "and 1 more of the same form", seven[0]["fix"])
    check_eq("K-27.7 ... still one paragraph", seven[0]["fix"].count(paragraph), 1)
    prose = _gw_findings(_gw_case("data", {"none": "needs the preview stand"}), rewritten=False)[0]
    check_not_in("K-27.7 a `none` of another kind carries no paragraph about an account", "an account named here", prose[0]["fix"])


def test_gw1_27_k8_the_three_doors_obey_the_human_text_rules() -> None:
    import human_text
    cases = {"stand_account": (_gw_case("account", {"stand_account": "ghost"}), None),
             "env account": (_gw_case("account", {"env": "NOT_SET_ANYWHERE"}), None),
             "stand_frontend": (_gw_case("service", {"stand_frontend": "the case opens the page"}),
                                lambda cfg: cfg["environments"][0].pop("frontend_url"))}
    for label, (items, config) in cases.items():
        found, _ = _gw_findings(items, config=config)
        check_eq(f"K-27.8 {label}: one question", len(found), 1)
        problems = human_text.problems(found[0]["message"] + "\n## How to answer\n" + found[0]["fix"], kind="question")
        check_eq(f"K-27.8 {label}: human_text (as a question) finds nothing", [(p["rule"], p["found"]) for p in problems], [])
        # F8: `problems` splits the block after the marker off and judges the shape rows on the BODY only, so the door text
        # (the `fix`) is checked here by the shape rows themselves: no script name, flag, form field, exit code or config key
        check_eq(f"K-27.8 {label}: the door text itself passes the shape rows", human_text.shape_problems(found[0]["fix"], kind="question"), [])
    card = _gw_findings(_gw_case("data", {"none": "base URL of UI"}), rewritten=False)[0]
    check_in("K-27.8 the prose `none` about the UI's address stays a card (code never reads prose)", "base URL of UI", card[0]["message"])


def test_gw1_27_k10_the_door_follows_the_check_and_a_recorded_account_closes_the_question() -> None:
    target = "testproject1_test_harness/.env"
    case = cmp2_case_id(1)
    tail = _GW_DOOR_TAIL.format(case=case)
    found, _ = _gw_findings(_gw_case("account", {"stand_account": "admin"}))
    check_eq("K-27.10 `stand_account: admin`, no such role: a question", len(found), 1)
    check_eq("K-27.10 ... its door, word for word",
             found[0]["fix"], f"this account (role admin): put its login and password in {target} as two variables of your choice, "
                              f"never in the chat, and tell me the two names — I record them under the role admin and rehearse again; {tail}")
    found, _ = _gw_findings(_gw_case("account", {"env": "NOT_SET_ANYWHERE"}))
    check_eq("K-27.10 an `env` account: its door, word for word", found[0]["fix"],
             f"this account: set NOT_SET_ANYWHERE and its password in {target}, never in the chat, and I rehearse again; {tail}")
    found, _ = _gw_findings(_gw_case("data", {"env": "NOT_SET_ANYWHERE"}))
    check_in("K-27.10 an `env` check of another kind keeps the general door", "prepare the stand", found[0]["fix"])
    found, _ = _gw_findings(_gw_case("account", {"stand_account": "default_user"}), env_lines=["AUTH_USERNAME=u"])
    check_in("K-27.10 the door is by the CHECK: the same kind with `stand_account` is not the `env` door", "put its login and password in",
             found[0]["fix"])
    check_eq("K-27.10 `env` with the name SET: no finding", _gw_findings(_gw_case("account", {"env": "AUTH_USERNAME"}))[0], [])
    found, _ = _gw_findings(_gw_case("account", {"none": "the second user"}), rewritten=False)
    check_in("K-27.10 a recorded role does not close a `none` card: the card is still there",
             "preconditions no machine can check", found[0]["message"])

    import project_decisions as PD
    root = cmp2_story("qa-gate-gw27-k10-", base=False, extra=[(1, "TS-1", _gw_case("account", {"stand_account": "admin"}))])
    try:
        use_project(root)
        check_eq("K-27.10 before the record: a question", len(by_check(cmp2_run(root, steps=("case_preconditions",)), "case_preconditions")), 1)
        PD.record_stand_account(root, stand="localhost", role="admin", user_key="AUTH_USERNAME", secret_key="AUTH_PASSWORD",
                                words="the second account is the admin on the local stand")
        check_eq("K-27.10 after `record_stand_account` for that role: the second rehearsal has no finding",
                 by_check(cmp2_run(root, steps=("case_preconditions",)), "case_preconditions"), [])
    finally:
        cleanup(root)


def test_gw1_27_r2_the_ui_door_offers_only_the_arm_the_tool_accepts() -> None:
    """Fix round 2, F1 (FR-2): `stand-frontend` takes `--key` at one stand (or none) and `--url --stand` at several, and refuses the
    other arm; the door asks for the variable at most one stand, for the address itself at several. F15: one door among several
    in a question is prefixed by the ids of the items it serves."""
    target = "testproject1_test_harness/.env"
    tail = _GW_DOOR_TAIL.format(case=cmp2_case_id(1))
    ui = _gw_case("service", {"stand_frontend": "the case opens the page"})
    several = lambda cfg: cfg["environments"][0].pop("frontend_url")                              # noqa: E731
    found, _ = _gw_findings(ui, config=several)
    check_eq("R2-F1 several stands: the door asks for the address itself, word for word", found[0]["fix"],
             f"the address of this stand's UI: tell me the address itself — I record it for this stand in the project and rehearse again; {tail}")

    def one_stand(cfg):
        cfg["environments"] = cfg["environments"][:1]
        cfg["environments"][0].pop("frontend_url")
    found, _ = _gw_findings(ui, config=one_stand)
    check_eq("R2-F1 one stand: the door asks for the variable (and says to put the address there first), word for word", found[0]["fix"],
             f"the address of this stand's UI: tell me which variable of {target} holds it (put the address there first if it is not in "
             f"the file) — I record it in the project and rehearse again; {tail}")

    def no_stand(cfg):
        cfg["environments"] = []
    found, _ = _gw_findings(ui, config=no_stand)
    check_in("R2-F1 no `environments[]` row: the block is the stand, so the variable arm", "which variable of", found[0]["fix"])
    check_not_in("R2-F1 ... and not the address arm", "the address itself", found[0]["fix"])
    import human_text
    for label, cfg in (("one stand", one_stand), ("several stands", several)):
        found, _ = _gw_findings(ui, config=cfg)
        check_eq(f"R2-F1 {label}: the door text passes the shape rows", human_text.shape_problems(found[0]["fix"], kind="question"), [])
    # a question that holds two doors: each is prefixed by the ids it serves (never one door for both)
    items = [{"id": "PC-1", "kind": "account", "what": "the second user", "partitions": [], "legacy": {"stand_account": "ghost"},
              "rewritten": {"stand_account": "ghost"}},
             {"id": "PC-2", "kind": "service", "what": "the page", "partitions": [], "legacy": {"stand_frontend": "the case opens the page"},
              "rewritten": {"stand_frontend": "the case opens the page"}}]
    found, _ = _gw_findings(items, config=several)
    check_eq("R2-F15 two items, two doors: one question", len(found), 1)
    check_in("R2-F15 the account door carries its id", "PC-1: this account (role ghost)", found[0]["fix"])
    check_in("R2-F15 the address door carries its id", "PC-2: the address of this stand's UI", found[0]["fix"])


def test_gw1_27_r2_s4_hands_the_conductor_commands_the_tools_accept() -> None:
    """Fix round 2, F3 / F4 / F1 (AR-8, FR-53): the text of `s4.md` carries the rework command without `--reason` (the controller
    refuses `--reason` together with `--words-file`) and with `--task-root`; both forms of `stand-frontend`; and the experiment
    clause. Keys quoted before the run; a negative control proves the helper can fail."""
    s4 = (Path(__file__).resolve().parents[2] / "skills" / "qa-story" / "phases" / "s4.md").read_text(encoding="utf-8")
    flat = " ".join(s4.split())

    def has(needle: str) -> bool:
        return needle in flat
    for needle in ("controller.py --task-root <r> --operation rework --stage S4 --role qa-case-designer --cases <ids> --brief --words-file <file>",
                   "project_decisions.py stand-frontend --key <NAME> --words-file <file>",
                   "project_decisions.py stand-frontend --stand <name> --url <address> --words-file <file>",
                   "In an experiment (`pipeline.no_trace`) write no fact into the config: the answer stays in the story's words"):
        check(f"R2 s4.md carries `{needle[:60]}...`", has(needle))
    check("R2-F3 the rework command has no `--reason` beside `--words-file`", not has('--cases <ids> --reason'))
    check("R2 negative control: the helper fails on a text that is absent", not has("stand-frontend --nowhere-in-the-text"))


def test_gw1_27_k11_a_flag_read_without_a_login_is_never_a_pass_on_the_unknown() -> None:
    flag = {"http": {"path": "/v1/flag", "status": 200, "json_path": "features.teams", "equals": True}}
    bare = {"http": {"path": "/v1/flag", "status": 200}}

    def run(kind, check_, body, status=200):
        root = cmp2_story("qa-gate-gw27-k11-", base=False, extra=[(1, "TS-1", _gw_case(kind, check_))])
        try:
            with stub_http((status, json.dumps(body))):
                return by_check(cmp2_run(root, steps=("case_preconditions",)), "case_preconditions")
        finally:
            cleanup(root)
    found = run("feature_flag", bare, {"any": 1})
    check_eq("K-27.11 a bare 200 for a flag: a question", len(found), 1)
    check_in("K-27.11 ... that it is not verifiable", "not verifiable", found[0]["message"])
    check_in("K-27.11 ... and why", "does not say whether a flag is on", found[0]["message"])
    found = run("feature_flag", flag, {"features": {}})
    check_in("K-27.11 the field absent: not verifiable, not `not enabled`", "without a login does not carry `features.teams`", found[0]["message"])
    check_in("K-27.11 ... counted as not verifiable", "1 not verifiable", found[0]["message"])
    check_eq("K-27.11 `equals` matched: no finding", run("feature_flag", flag, {"features": {"teams": True}}), [])
    found = run("feature_flag", flag, {"features": {"teams": False}})
    check_in("K-27.11 a found value that is not `equals`: unmet, says it was read without a login", "without a login", found[0]["message"])
    check_in("K-27.11 ... counted as not met", "1 not met", found[0]["message"])
    check_eq("K-27.11 a service with a bare 200 is met (the old pin)", run("service", bare, {"any": 1}), [])
    found = run("feature_flag", flag, {}, status=401)
    check_in("K-27.11 a 401 stays not verifiable with its reason", "wants a login", found[0]["message"])


def test_gw1_16_k16_10_the_one_classifier_serves_the_block_of_gate_b() -> None:
    """GW1-16, K16.10: `planning_contract._unmet_preconditions` reads the SAME classifier (`_check_one_precondition`), so the new
    `integration` check is met / unmet / uncheckable there exactly as at the gate: `met` leaves the block, the rest stays."""
    import planning_contract
    root = cmp2_story("qa-gate-gw16-k10-", base=False, config=lambda cfg: cfg["environment"]["integrations"].append(
        {"name": "set-svc", "keys": ["AUTH_USERNAME"], "required_by": ["api"]}))
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET

        def item(pid: str, name: str) -> dict:
            return {"id": pid, "kind": "service", "what": name, "check": {"integration": name}}
        items = [item("PC-1", "set-svc"), item("PC-2", "aws-parameter-store"), item("PC-3", "nowhere")]
        kept = [i["id"] for i in planning_contract._unmet_preconditions(task, items)]
        check_eq("K16.10: the integration whose key is set leaves; the unmet one and the unknown name stay", kept, ["PC-2", "PC-3"])
    finally:
        cleanup(root)


# --- RN1-10 (b): gate A proves each account a manual check signs in as (K-P1 .. K-P5 of the spec t-1700) ------------------
# Killing test of each mutant (named, not run - D-0056): M-P1 `ok` written without `signed_in is True` (a `not_landed` row `ok`) ->
# actor_sign_in_k_p2; M-P2 an actor with unset keys is probed anyway / stops the others -> actor_sign_in_k_p5; M-P3 the file
# written when no manual case names an account -> actor_sign_in_k_p4; M-P4 `before_submit`/`no_recipe` read as `ok` or as a person's
# question -> actor_sign_in_k_p3; M-P5 the row keyed by another text than the actor as given -> actor_sign_in_k_p1 (the reader's round
# trip); M-P6 the step left out of the gate-A list -> actor_sign_in_k_p1 (a whole run).
PROBE_USER, PROBE_ADMIN = "probe-user@example.invalid", "probe-admin@example.invalid"


class _ProbeWorld:
    """What the fake browsers of one test share: who the stand lets in, and what was opened and closed."""

    def __init__(self, lands=(PROBE_USER, PROBE_ADMIN), form_missing=False, no_browser=False):
        self.lands, self.form_missing, self.no_browser = set(lands), form_missing, no_browser
        self.opened, self.closed, self.logins, self.now = 0, 0, [], 0.0


class _ProbeBrowser:
    def __init__(self, world, MC):
        if world.no_browser:
            raise MC.BrowserUnavailable("playwright is not installed here")
        self.world, self.MC, self.url, self.cookies = world, MC, "about:blank", set()

    def open(self, timeout_s, allowed_hosts, local_storage=None, element_wait_s=None, profile_dir=None):
        self.world.opened += 1

    def login(self, recipe, credentials, frontend_url):
        if self.world.form_missing:
            raise self.MC.StepFailed("the sign-in field was not found")
        self.world.logins.append(credentials.username)
        if credentials.username in self.world.lands:
            self.url, self.cookies = "http://localhost:5173/home", {"testproject1_access_token"}
        else:
            self.url = "http://localhost:5173/auth/sign-in"

    def current_url(self):
        return self.url

    def cookie_names(self):
        return set(self.cookies)

    def field_visible(self, row):
        return not self.cookies

    def pause(self, seconds):
        self.world.now += max(seconds, 1e-6)

    def page_words(self, mode=None):
        return "Sign in to your account"

    def close(self):
        self.world.closed += 1


def _probe_story(items_by_case, config=None, env_lines=None):
    """The cmp2 story with `user` and `admin` roles of the stand, a file of their keys, and manual-agent cases that declare `items_by_case`."""
    def edit(cfg):
        roles = cfg["environments"][0]["credentials_by_role"]
        roles["user"] = ".env: USER_EMAIL / USER_PASSWORD - the user"
        roles["admin"] = ".env: ADMIN_EMAIL / ADMIN_PASSWORD - the admin"
        if config:
            config(cfg)
    lines = env_lines if env_lines is not None else (
        ["AUTH_USERNAME=admin@example.invalid", "AUTH_PASSWORD=not-printed-1"] + [f"{key}=x" for key in CMP2_EXTRA_KEYS]
        + [f"USER_EMAIL={PROBE_USER}", "USER_PASSWORD=pw-user-not-printed", f"ADMIN_EMAIL={PROBE_ADMIN}", "ADMIN_PASSWORD=pw-admin-not-printed"])
    extra = [(n, f"TS-{n}", _gw_case("account", {"stand_account": role})) for n, role in items_by_case]
    return cmp2_story("qa-gate-probe-", base=False, extra=extra, config=edit, env_lines=lines)


def _probe_run(root, world, whole=False):
    import manual_capture as MC
    before = (MC.BACKEND_FACTORY, MC.MONOTONIC)
    MC.BACKEND_FACTORY, MC.MONOTONIC = (lambda: _ProbeBrowser(world, MC)), (lambda: world.now)
    try:
        return cmp2_run(root, steps=None if whole else ("actor_sign_in",))
    finally:
        MC.BACKEND_FACTORY, MC.MONOTONIC = before


def _probe_rows(root) -> dict:
    path = root / "qa-factory" / "artifacts" / CMP2_TICKET / "state" / "sign-in-probe.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def test_actor_sign_in_k_p1_both_accounts_land_two_ok_rows_and_the_reader_accepts_them() -> None:
    import manual_capture as MC
    root = _probe_story([(1, "user"), (2, "admin")])
    try:
        world = _ProbeWorld()
        result = _probe_run(root, world, whole=True)        # the whole gate: the step is on the list of gate A
        check_eq("K-P1: no finding of the probe", by_check(result, "actor_sign_in"), [])
        rows = _probe_rows(root)
        check_eq("K-P1: one row per account, keyed by the text as a --session call is given it", sorted(rows), ["admin", "user"])
        check_eq("K-P1: both `ok`", [rows[a]["outcome"] for a in ("user", "admin")], ["ok", "ok"])
        check_eq("K-P1: each account signed in once, with its own keys", sorted(world.logins), sorted([PROBE_USER, PROBE_ADMIN]))
        check_eq("K-P1: every browser opened was closed", (world.opened, world.closed), (2, 2))
        recipe = MC.login_recipe(json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")), MC.spec(), "ui")
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        check_eq("K-P1: the reader of S6 (`sign_in_refusal`) accepts both rows for this recipe",
                 [MC.sign_in_refusal(task, a, recipe) for a in ("user", "admin")], ["", ""])
        check_not_in("K-P1: no password in the file", "pw-", json.dumps(rows))
    finally:
        cleanup(root)


def test_actor_sign_in_k_p2_an_account_the_stand_refuses_is_the_persons_question_and_never_ok() -> None:
    import human_text
    import manual_capture as MC
    root = _probe_story([(1, "user"), (2, "admin")])
    try:
        world = _ProbeWorld(lands=(PROBE_USER,))
        found = by_check(_probe_run(root, world), "actor_sign_in")
        rows = _probe_rows(root)
        check_eq("K-P2: one finding", len(found), 1)
        check_eq("K-P2: the person's, with three answers", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("K-P2: it names the account", "the account admin", found[0]["message"])
        check_in("K-P2: and the case that needs it", cmp2_case_id(2), found[0]["message"])
        for word in ("give access", "by hand", "not needed"):
            check_in(f"K-P2: the answer `{word}`", word, found[0]["fix"])
        check_eq("K-P2: the other account is `ok`", rows["user"]["outcome"], "ok")
        check_eq("K-P2: the refused one is `failed`, not `ok` (AR-28)", rows["admin"]["outcome"], "failed")
        task = root / "qa-factory" / "artifacts" / CMP2_TICKET
        check("K-P2: S6 refuses a session of the refused account", MC.sign_in_refusal(task, "admin", MC.login_recipe(
            json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")), MC.spec(), "ui")) != "")
        check_eq("K-P2: the texts obey the human-text rules", [(p["rule"], p["found"]) for p in human_text.problems(
            found[0]["message"] + "\n## How to answer\n" + found[0]["fix"], kind="question")], [])
        check_not_in("K-P2: no value of the account in the finding", "pw-admin", json.dumps(found))
    finally:
        cleanup(root)


def test_actor_sign_in_k_p3_a_recipe_that_does_not_fit_is_not_proved_and_the_factorys_to_fix() -> None:
    import manual_capture as MC
    for label, world, config in (
            ("the default form is not on the page", _ProbeWorld(form_missing=True), None),
            ("the project records no UI sign-in", _ProbeWorld(), lambda cfg: cfg.update(manual_capture={"login": {"ui": None}}))):
        root = _probe_story([(1, "user")], config=config)
        try:
            found = by_check(_probe_run(root, world), "actor_sign_in")
            check_eq(f"K-P3 {label}: one finding", len(found), 1)
            check_eq(f"K-P3 {label}: the factory's to fix, not the person's", found[0]["class"], gate_preflight.FACTORY_FIXABLE)
            check_eq(f"K-P3 {label}: `not_proved`, never `ok`", _probe_rows(root)["user"]["outcome"], "not_proved")
            task = root / "qa-factory" / "artifacts" / CMP2_TICKET
            cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            check(f"K-P3 {label}: S6 refuses the session", MC.sign_in_refusal(task, "user", MC.login_recipe(cfg, MC.spec(), "ui")) != "")
            check_eq(f"K-P3 {label}: no one is told to do anything (door to the person is only a word of theirs)",
                     gate_preflight.PERSON_DECIDES in [f["class"] for f in found], False)
        finally:
            cleanup(root)
    root = _probe_story([(1, "user")])
    try:
        found = by_check(_probe_run(root, _ProbeWorld(no_browser=True)), "actor_sign_in")
        check_eq("K-P3 no browser here: the factory's defect, the row `not_proved`",
                 ([f["class"] for f in found], _probe_rows(root)["user"]["outcome"]), ([gate_preflight.FACTORY_DEFECT], "not_proved"))
        # t-1747 F10: the door of the factory's own defect is ONE constant, whichever branch of the per-actor probe says it
        check("K-P3 F10: the no-browser finding carries the one factory door", gate_preflight.SIGN_IN_FACTORY_DOOR in json.dumps(found, ensure_ascii=False),
              json.dumps(found, ensure_ascii=False)[:300])
    finally:
        cleanup(root)


def test_actor_sign_in_k_p4_no_manual_case_with_an_account_writes_and_opens_nothing() -> None:
    root = cmp2_story("qa-gate-probe-none-")          # the cmp2 story: accounts only on `automate` rows
    try:
        world = _ProbeWorld()
        found = by_check(_probe_run(root, world), "actor_sign_in")
        check_eq("K-P4: no finding", found, [])
        check_eq("K-P4: no file", _probe_rows(root), {})
        check("K-P4: the file is not on disk at all", not (root / "qa-factory" / "artifacts" / CMP2_TICKET / "state" / "sign-in-probe.json").exists())
        check_eq("K-P4: no browser was opened", world.opened, 0)
    finally:
        cleanup(root)


def test_actor_sign_in_k_p5_keys_outside_the_files_the_runner_reads_are_that_accounts_finding_only() -> None:
    lines = (["AUTH_USERNAME=admin@example.invalid", "AUTH_PASSWORD=not-printed-1"] + [f"{key}=x" for key in CMP2_EXTRA_KEYS]
             + [f"ADMIN_EMAIL={PROBE_ADMIN}", "ADMIN_PASSWORD=pw-admin-not-printed"])
    root = _probe_story([(1, "user"), (2, "admin")], env_lines=lines)
    try:
        (root / "testproject1_test_harness" / ".env.local").write_text(f"USER_EMAIL={PROBE_USER}\nUSER_PASSWORD=pw-user-not-printed\n", encoding="utf-8")
        world = _ProbeWorld()
        found = by_check(_probe_run(root, world), "actor_sign_in")
        rows = _probe_rows(root)
        check_eq("K-P5: one finding, the user's", len(found), 1)
        check_eq("K-P5: the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("K-P5: it names the keys", "USER_EMAIL, USER_PASSWORD", found[0]["message"])
        check_in("K-P5: and says they are not set where the runner reads them", "not set where the runner reads it", found[0]["message"])
        check_in("K-P5: and the file it read (the existing text of `_looked_in`)", "testproject1_test_harness/.env", found[0]["message"])
        check_eq("K-P5: the user was never probed, the admin was", world.logins, [PROBE_ADMIN])
        check_eq("K-P5: the unreadable account is `not_proved`, the other `ok` (E8)",
                 (rows["user"]["outcome"], rows["admin"]["outcome"]), ("not_proved", "ok"))
    finally:
        cleanup(root)


if __name__ == "__main__":
    test_actor_sign_in_k_p1_both_accounts_land_two_ok_rows_and_the_reader_accepts_them()
    test_actor_sign_in_k_p2_an_account_the_stand_refuses_is_the_persons_question_and_never_ok()
    test_actor_sign_in_k_p3_a_recipe_that_does_not_fit_is_not_proved_and_the_factorys_to_fix()
    test_actor_sign_in_k_p4_no_manual_case_with_an_account_writes_and_opens_nothing()
    test_actor_sign_in_k_p5_keys_outside_the_files_the_runner_reads_are_that_accounts_finding_only()
    test_gw1_16_k16_10_the_one_classifier_serves_the_block_of_gate_b()
    test_gw1_27_k1_k3_the_role_in_another_spelling_is_the_role_the_stand_holds()
    test_gw1_27_k2_default_is_the_stands_default_account()
    test_gw1_27_k4_the_new_form_is_taught_and_validated()
    test_gw1_27_k5_the_address_of_the_ui_is_read_by_the_one_reader()
    test_gw1_27_k6_a_question_about_an_account_says_where_and_gives_three_answers()
    test_gw1_27_k7_one_paragraph_on_the_none_card_and_the_limit_is_as_before()
    test_gw1_27_k8_the_three_doors_obey_the_human_text_rules()
    test_gw1_27_k10_the_door_follows_the_check_and_a_recorded_account_closes_the_question()
    test_gw1_27_r2_the_ui_door_offers_only_the_arm_the_tool_accepts()
    test_gw1_27_r2_s4_hands_the_conductor_commands_the_tools_accept()
    test_gw1_27_k11_a_flag_read_without_a_login_is_never_a_pass_on_the_unknown()
    test_b_deps_first_test_file_recognises_a_test_through_the_one_leaf()
    test_b414_a_stand_gap_override_passes_only_the_finding_of_exactly_its_gap()
    test_b414_a_shared_precondition_id_is_qualified_in_the_rehearsal_and_its_door()
    test_b426_d4_the_findings_of_two_cases_keep_their_order_and_the_gap_ids()
    test_the_shape_of_a_rehearsal()
    test_the_critics_unapplied_fix_is_the_factorys_to_repair()
    test_a_fix_no_code_can_apply_is_carried_to_the_gate_not_repaired_forever()
    test_sc5_15_no_case_on_disk_under_a_planned_history_is_a_finding_not_a_pass()
    test_a_gap_the_plan_itself_declares_becomes_a_question()
    test_a_word_already_given_is_not_asked_for_twice()
    test_a_check_that_is_not_installed_is_a_finding_not_a_pass()
    test_a_refusal_waiting_on_the_other_side_is_named_before_the_gate()
    test_the_dirty_tree_and_the_branch_are_asked_inside_the_packet()
    test_gate_b_rehearses_the_write_it_is_about_to_authorise()
    test_the_write_right_the_project_already_denied_is_the_persons_question()
    test_an_experiment_rehearses_no_write_and_probes_no_tracker()
    test_the_toolchain_of_the_next_stage_is_collected_before_the_gate()
    test_ep1_9_a_collect_that_counts_tests_and_lists_none_is_unavailable_never_silent()
    test_rh1_3_a_broken_test_file_does_not_stop_the_gate_collect()
    test_rh1_4_a_difference_from_the_lock_is_a_note_and_one_phrase_of_the_collect_card()
    test_the_credentials_of_the_next_stage_name_the_file_that_reads_them()
    test_the_rehearsal_writes_nothing()
    test_the_brief_block_is_short_and_says_who_owns_what()
    test_s4_does_not_close_while_the_factory_owes_itself_a_repair()
    test_ep1_24_b3_a_refusal_with_a_typed_argv_names_the_command()
    test_ep1_24_f4_the_close_refusal_prints_the_command_and_the_waiver_ignores_it()
    test_a_persons_word_closes_the_stage_anyway()
    test_a_clean_story_closes_s4_without_a_word()
    test_what_a_case_needs_from_the_stand_is_one_question_per_case()
    test_a_stand_that_meets_every_precondition_raises_nothing()
    test_a_check_that_cannot_run_is_never_the_persons_problem()
    test_http_get_keeps_the_error_body_and_names_the_factory()
    test_a_case_without_preconditions_is_never_refused()
    test_an_unreadable_preconditions_line_is_the_factorys_to_repair()
    test_the_shape_has_one_owner()
    # t-218
    test_k1_the_seeded_and_the_stands_own_account_are_not_questions()
    test_k1_legacy_the_cmp2_lines_verbatim_make_two_findings()
    test_a_case_whose_items_are_all_seeded_asks_nothing_but_is_counted()
    test_seeded_items_never_make_an_unmet_one_met()
    test_a_stand_account_is_met_only_on_positive_evidence()
    test_a_stand_account_card_names_every_file_it_looked_in()
    test_no_selectable_stand_is_the_factorys_error_never_a_question()
    test_the_info_line_names_six_cases_and_counts_the_rest()
    test_k2_integration_keys_and_accounts_are_asked_only_when_the_story_names_them()
    test_the_integration_scope_follows_env_probes_order_and_errs_toward_a_card()
    test_an_integration_the_config_writes_badly_is_ignored_not_a_crash()
    test_a_case_that_cannot_be_read_keeps_every_integration_key_wanted()
    test_the_story_ids_integrations_are_scoped_by()
    test_f3a_an_e2e_row_is_keyed_to_the_profile_named_as_its_level()
    test_ep1_41f_a_device_level_is_keyed_by_the_fits_levels_of_its_surface()
    test_the_executor_question_now_reaches_the_e2e_profile()
    test_k5_a_page_that_loads_slower_than_the_page_objects_wait_is_one_card()
    test_k5_strict_greater_than_at_and_beyond_the_wait()
    test_k5_nothing_recorded_is_not_measured_and_never_a_card()
    test_k5_a_limit_that_cannot_be_read_is_one_defect_and_no_card()
    test_a_measurement_older_than_the_stand_is_not_a_measurement()
    test_the_other_stand_is_named_only_when_its_own_load_fits()
    test_a_card_a_person_has_answered_is_closed_in_all_the_ways_it_can_still_be()
    test_the_stand_limit_step_can_be_switched_off()
    test_the_reporter_proves_a_profile_with_one_of_its_own_tests()
    test_the_reporter_skips_a_profile_whose_e2e_limit_card_is_open()
    test_k3_a_stand_that_matches_is_derived_and_shown_with_its_argv()
    test_k3_the_rehearsal_with_a_derived_probe_writes_nothing()
    test_k3_two_candidate_checkouts_without_a_profile_id_are_one_card()
    test_k3_one_card_per_profile_when_the_container_is_ambiguous()
    test_k3_a_candidate_with_stale_content_is_one_mismatch_and_no_ambiguity_card()
    test_k3_what_the_probe_cannot_say_is_info_and_what_cannot_be_identified_is_a_fact()
    test_k3_docker_that_does_not_answer_is_one_card_with_the_refusal_verbatim()
    test_k3_a_probe_that_is_registered_is_left_alone()
    test_k3_the_step_stays_quiet_where_it_has_nothing_to_compare()
    test_k3_a_stand_the_story_did_not_choose_is_a_card_with_the_refusal()
    test_k3_the_container_is_chosen_by_what_it_holds()
    test_the_users_of_the_profile_keying_are_the_ones_the_report_lists()
    test_the_cmp2_rehearsal_is_the_one_a_person_can_read()
    # t-224 fix wave (t-218 section 0d)
    test_c1_the_none_card_opens_with_a_lead_that_survives_the_packets_cut()
    test_c2_the_stand_limit_card_offers_only_doors_that_have_an_executor()
    test_c3_the_new_checks_speak_in_the_storys_words()
    test_c4_a_story_that_changes_nothing_in_the_checkout_is_one_line_and_never_docker()
    test_fb8_gate_a_only_non_runtime_asks_no_container()
    test_fb8_gate_a_config_absence_mismatch_and_not_shipped_line()
    test_c5_an_integration_out_of_scope_is_not_asked_even_when_a_case_cannot_be_read()
    test_q1_a_profile_with_no_recorded_checkout_is_one_line_and_never_docker()
    test_q2_a_page_load_with_no_command_or_date_is_the_factorys_defect()
    test_d4_a_probe_that_prints_nothing_readable_is_the_factorys_defect_like_a_timeout()
    # t-256 (spec t-227 section 0d)
    test_t256_o6_the_none_card_prints_the_token_for_each_case_it_names()
    test_t256_o4_a_raise_that_is_still_there_at_gate_a_is_the_factorys_to_repair()
    # t-238 (t-218 section 0e): the second fix wave; the sweep goes LAST, it reads what the file did
    test_w3_a_verdict_outside_the_vocabulary_is_the_factorys_defect()
    test_w5_the_info_lines_carry_the_portable_argv_and_the_stored_one_is_read_with_this_machine()
    # t-300 N1a
    test_t300_k30_the_identity_reader_of_gate_a_is_a_rehearsal_and_takes_the_fifth_word()
    test_t300_k31_a_confirmed_build_is_an_info_line_at_gate_a_not_a_factory_defect()
    test_t345_r8_the_two_new_texts_of_the_probe_verdicts_obey_the_human_text_rules()
    test_t300_k32_stand_profiles_are_the_profiles_of_the_cases_a_stage_will_run()
    test_ep1_41f_the_probe_picks_the_stand_of_the_profile_it_probes()
    test_w2_the_older_cards_open_with_the_block_their_word_is_matched_against()
    test_w2_the_gate_b_cards_about_a_bug_draft_open_with_their_block()
    test_c3_a_code_reading_draft_is_judged_by_its_own_checker()
    test_t2187_n2_the_rehearsal_reads_the_manifestations_and_the_cause()
    test_g1_9_the_rehearsal_reads_the_drafts_through_the_one_reader()
    test_w2_every_card_that_offers_a_word_contains_its_block()
    test_t357_the_door_of_a_finding_is_a_line_in_words_never_a_command()
    test_b220_p2_the_reporter_card_carries_what_it_offers_and_whose_command_it_is()
    test_t357_the_stand_gap_cards_of_gate_a_are_pointed_at_in_words()
    test_t357_render_says_whose_it_is_in_words_and_keeps_the_id()
    test_t357_no_literal_of_any_add_or_note_in_the_source_names_a_script_or_a_flag()
    test_t683_d12_every_exit_and_every_verdict_of_the_derived_probe_says_what_it_said()
    test_d1b_k_b6_a_finding_made_for_a_subject_keeps_its_id_between_rehearsals()
    test_d1b_k_b7_the_norms_question_rule_runs_at_gate_a_and_the_marker_is_read()
    test_t357_every_text_of_every_run_of_this_file_obeys_the_owners_rule()
    finish("gate rehearsal")
