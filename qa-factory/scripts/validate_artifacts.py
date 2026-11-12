"""Detectors for the "artifact schemas" and "state machine" mechanisms (PostToolUse: Write|Edit).

1. Frontmatter of cases (test-cases/**/<case id>.md) and bugs (bugs/BUG-*.md) — required
   fields and allowed values.
2. State-machine gate: status: Automated is only legal together with red_probe and
   automated_by (the transition is made by the code critic after its probe —
   nobody else has a legal path).
3. Ledger of the P1 estimation loop (records/estimation-ledger.jsonl) — every line must be
   a valid JSON object with the full key set, and delta.direction must come from a
   closed list (anti-invented-status: the sdlc-emit lesson of the dev factory).
4. The P3 coverage line (qa-factory/artifacts/<task>/test-report.md) — a "## Check coverage"
   section is mandatory, and under it at least one table row with a status from the
   closed list of markers: a missing section reads as a silently skipped check,
   not as "everything passed".
5. "Empty is not clean", P2 (qa-factory/artifacts/<task>/run-report.json) — zero
   totals (passed+failed+skipped+passed_on_retry == 0) with env_preflight: pass and
   without env_blocked/manual_checks/manual_skipped — reject: an empty run must
   either explain the environment block or explicitly name where the cases went.
   Zero totals with env_preflight: blocked are legitimate — the block explains
   itself.
6. The pipeline.json checkpoint (state/<task>/) — the mandatory PIPELINE_KEYS keys,
   including parent_feature (FB-15, team calibration 2026-09-02: without it the
   dashboard loses the task-to-feature link; the backfill is done — both live
   checkpoints carry the field).
7. The "tester mindset" form (shared artifact contracts;
   closed lists — grammar.py; date-cutoff RULE_CUTOFF = 2026-09-07, older artifacts are
   validated by the previous schema): the requirements register (requirements-register.md)
   as the unit of coverage; a case — `covers: [R-n]` + defect_class + basis; the plan — a
   risk map (defect class, impact -> priority, independent observation, basis); a bug —
   violates per the oracle grammar, impact -> severity, the "User impact" and "Initial
   state" sections, and since BUG_CONFIRMATION_CUTOFF a `confirmation` from the closed
   list (a bug nobody reproduced is `unconfirmed`); a charter — hypotheses with bindings and statuses; the PTR — "Readiness
   within what was verified" for every R; the escape ledger.
Exit 2 -> the violation is returned to the model as same-turn feedback.

THE LAW OF EDITING THIS FILE (FB-12, team calibration decision 2026-09-02): any new
validator rule arrives ONLY paired with one of two things — (a) a backfill of the
existing artifacts with the missing field, or (b) a date-cutoff (the rule applies to
artifacts younger than the rule's date). Retro-fitting live old artifacts paints
innocent agents guilty of someone else's file — three break-glass incidents on
2026-09-01 (FB-1/FB-9/FB-12).
"""
import json
import re
import sys
from pathlib import Path

import hooklib
from hooklib import artifact_root, read_event, parse_frontmatter, block, norm, config_path, person_signal
import grammar as G
from record_schema import validate_record

CFG_PATH = config_path()

# covers_ac removed from the required fields (WP1): the unit of coverage is a register requirement (`covers`).
# Old cases (updated < RULE_CUTOFF) are accepted with covers_ac; new ones must carry covers.
CASE_REQUIRED = ["id", "title", "area", "priority", "status", "channel", "reuse_decision", "updated"]
CASE_FORM_REQUIRED = ["task", "covers", "defect_class", "basis"]  # since RULE_CUTOFF
# seams_touched / profile: parity dropped with the A4 decision (refactor-parity testing and the
# "before" snapshot are v1); the v0 register is the six-source model plus an observable column.
REGISTER_REQUIRED = ["task", "created", "ids", "by_source", "confidence"]
REGISTER_HEADING = "## Register"
# Duplicated here only because contract.py is imported further down the file (the C0 block);
# kept as a tuple so a drift between the two is a one-line fix, checked by test_validators.py.
OBSERVABLE_SOURCES_V0 = ("diff", "current-code", "expected-contract")
REGISTER_MATRIX_HEADING = "## Contradiction matrix"
PLAN_REQUIRED = ["task", "created", "scenarios_total", "smoke", "by_defect_class", "by_priority", "requirements_total"]
PLAN_SCENARIOS_HEADING = "## Scenarios"
PLAN_SEAMS_HEADING = "## Seam scenarios"
PTR_READINESS_HEADING = "## Readiness within what was verified"
BUG_FORM_REQUIRED = ["impact"]  # since RULE_CUTOFF
BUG_FORM_SECTIONS = ("## User impact", "## Initial state")
CHARTER_HYPOTHESES_HEADING = "## Hypotheses"
CHARTER_FINDINGS_HEADING = "## Findings"
ESCAPE_LEDGER_REQUIRED = ["ts", "bug", "stage_should_have_caught", "missing_element", "action", "witness"]
CASE_STATUS = {"Draft", "Review", "Approved", "Automated", "Blocked", "Archived"}
CASE_PRIORITY = {"P0", "P1", "P2", "P3"}
CASE_CHANNEL = {"auto", "manual-agent", "manual-human"}
# The designer's own closed list (agents/qa-case-designer.md, frontmatter block). It was the
# only closed-list case field nothing checked, and a closed list nothing checks is a suggestion.
CASE_REUSE_DECISION = {"new", "extend", "dedupe", "updated"}
BUG_REQUIRED = ["id", "title", "severity", "status", "area", "found_by", "violates", "created"]
# `confirmation` (contract.BUG_CONFIRMATIONS) gets its own cutoff rather than a seat in
# BUG_FORM_REQUIRED: RULE_CUTOFF is 2026-09-07, and adding the field to that list would make
# every bug filed since then stop validating — exactly what the law at the top of this file
# forbids. TP1-15045 is why the field exists: two of four bugs were red tests nobody had
# triaged or reproduced. A bug filed before this date carries no `confirmation` and reads as
# `confirmed_by_person` (contract.bug_confirmation) — nobody re-litigates a filed bug.
BUG_CONFIRMATION_CUTOFF = "2026-09-24"
# The filed-bug header (cases / requirements, HF8-21) has its own cutoff for the same reason: a bug written by 0.10.6 and before
# carries `source_draft` and no `cases` (run 12586's BUG-1.md), and nobody re-litigates a filed bug. The day after the release.
BUG_FILING_HEADER_CUTOFF = "2026-10-31"
# The red test with the bug (P28, X7-5): its cutoff day is `contract.BUG_RED_TEST_CUTOFF`, read only by `contract.red_test_owed`.
BUG_STATUS = {"Open", "Fixed", "Verified", "Reopened", "Rejected", "Intended", "Blocked", "Closed"}
BUG_SEVERITY = {"blocker", "critical", "major", "minor", "Blocker", "Critical", "Major", "Minor"}
# Required keys per JSON artifact of the v0 stage model. The SOURCE OF TRUTH for this table
# is the references/artifact-contract*.md family: audit A11 re-reads them and rejects any
# required key the contract does not document. Donor-era entries dropped with the v0 design
# (2026-09-11): classification.json (the complexity assessor is gone — size lives on the
# scope card), baseline-report.json (the "before" snapshot and parity testing are v1),
# actual-complexity.json (the estimation loop closes through records/estimation-ledger.jsonl).
PHASE_JSON_KEYS = {
    "context-manifest.json": ["ticket", "acceptance_criteria", "implementation"],
    "automation-manifest.json": ["tests", "run_witness"],
    "run-report.json": ["env_preflight", "totals", "results", "witness", "execution_status"],
    "triage.json": ["triage"],
}
# Writer role of each artifact — the owner of the schema above. Audit A11 checks the role
# exists in agents/; the KEYS themselves are checked against the contract document, not
# against the role's prose (a role is free to describe its output in its own words).
PHASE_JSON_WRITERS = {
    "context-manifest.json": "qa-scout.md",
    "automation-manifest.json": "qa-automator.md",
    "run-report.json": "qa-runner.md",
    "triage.json": "qa-failure-analyst.md",
}
PIPELINE_KEYS = ["task", "phase_done", "next_phase", "ts", "parent_feature"]  # parent_feature — FB-15 (2026-09-02), backfill done
REVIEW_REQUIRED = ["mode", "verdict", "blockers"]
REVIEW_MODES = {"audit", "decomposition", "audit+decomposition", "readiness", "freshness"}
REVIEW_VERDICTS = {"pass", "pass_with_questions", "blocked"}
REVIEW_DECOMPOSITION_REQUIRED = ["decomposition_defects", "subtasks", "feature"]
CHARTER_REQUIRED = ["id", "title", "status", "trigger", "timebox", "created"]
CHARTER_STATUS = {"Proposed", "Planned", "InProgress", "Done", "Blocked"}
CHARTER_TRIGGER = {"cadence", "app-changed", "bug-cluster", "pre-release", "refactor", "manual"}
ESTIMATION_LEDGER_REQUIRED = ["ts", "task", "forecast", "actual", "delta", "hit", "drivers"]
# Closed list of divergence directions. An invented value (e.g. "pending") is an
# invented status — the same disease as in the dev factory's sdlc-emit: reject, not a silent pass.
ESTIMATION_LEDGER_DIRECTIONS = {"in", "above", "below"}
# P3 "coverage line": closed list of status markers of the PTR coverage table.
PTR_COVERAGE_HEADING = "## Check coverage"
# A coverage row states an outcome either as a tick mark or as a ledger state — since the
# report absorbed the brief, its "## Check coverage" section IS the table ledger.py
# generated, whose vocabulary is `passed_green` / `failed:…` / `skipped:…` and so on.
PTR_STATUS_MARKERS = ("✓", "✗", "○", "—", "passed_green", "failed:", "skipped:", "impossible",
                      "not_executed", "env_blocked", "pending_implementation",
                      "deferred_by_decision", "not_verified_flaky", "subtask_in_progress")

# P6 "next: lines": a single dictionary of the orchestrator's next obligation, keyed by
# artifact filename. Printed ONLY after successful validation (see main()) —
# check_witness.py imports this dictionary from here, the hint text must not be
# duplicated. Origin of the principle — qafactory: "the instruction travels back
# with the result, where it is the freshest thing in context rather than the
# oldest". Rules from SKILL.md become the oldest thing in context by mid-pipeline;
# the next: line in a hook's output arrives freshest, right at the decision point.
NEXT_STEPS = {
    "context-manifest.json": "next: S2 qa-requirements-tester — requirements register, readiness and understanding.md; S1 + S2 questions reach gate A as one batch",
    "requirements-register.md": "next: requirements-readiness.json with the register block (total/by_source); then check_witness.py acceptance — a register built from AC alone while a parent feature exists must carry confidence: low",
    "requirements-readiness.json": "next: understanding.md, then S3 qa-test-strategist; verdict: blocked -> S3 is off-limits without answers or an explicit risk acceptance recorded at gate A",
    "understanding.md": "next: S3 qa-test-strategist — one plan row per register requirement; every R of the register must already appear under \"What we verify\" or \"What we do not verify\"",
    "test-plan.md": "next: GATE A (mandatory) — this table IS what the human reads, so every row needs its `what we verify` line; a disposition the human changes carries overridden: true and re-dispatches the strategist once",
    "automation-manifest.json": "next: check_witness.py acceptance (run_witness - or, when every test is pending its absent side, the `kind: collect` row in runs[]); then qa-code-critic — require independent_run and red_probe; stage_guard rule 3 blocks S6-S8 while an unresolved entry lacks a deferred_by_decision: reason",
    "run-report.json": "next: check_witness.py acceptance; env_preflight: blocked -> S6 halts on the environment (owner:factory) and execution_status must read env_blocked; otherwise S7 qa-failure-analyst triages every failure",
    "triage.json": "next: the ENV_ISSUE dismissal formula (our_signal/env_fix/unverified) and FLAKY proof (3 executions counted across every role via runs[], + mechanism + fix_result); then S8 — ledger.py, then check_delivery.py",
    "ledger.json": "next: check_delivery.py fills delivery_ready and reasons; then test-report.md, whose Check coverage section is work/ledger.md verbatim and whose delivery_ready line must equal this file",
    "test-report.md": "next: check_coverage.py acceptance (all six sections in order; Check coverage + Readiness within what was verified); then GATE B — the human decides delivery, a deliver_with_risks decision is journalled, never assumed; then S9 qa-retro-analyst",
    "estimation-ledger.jsonl": "next: the retro reads this precedent line back — forecast vs actual reaches retro.md and the dashboard's Estimates block",
}


def check_case(path: Path, errors: list) -> None:
    case_text = path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(case_text)
    if fm is None:
        errors.append(f"{path.name}: no YAML frontmatter")
        return
    for field in CASE_REQUIRED:
        if field not in fm or fm[field] == "":
            errors.append(f"{path.name}: required field '{field}' is missing")
    if fm.get("status") and fm["status"] not in CASE_STATUS:
        errors.append(f"{path.name}: status '{fm['status']}' outside {sorted(CASE_STATUS)}")
    if fm.get("priority") and fm["priority"] not in CASE_PRIORITY:
        errors.append(f"{path.name}: priority '{fm['priority']}' outside {sorted(CASE_PRIORITY)}")
    if fm.get("channel") and fm["channel"] not in CASE_CHANNEL:
        errors.append(f"{path.name}: channel '{fm['channel']}' outside {sorted(CASE_CHANNEL)}")
    # defect_class is checked for every case that declares one, not only after the form cutoff:
    # on TP1-15045 `regression` (the closed list has `regression:BUG-NNN`) travelled from a
    # plan row into case design and only the critic noticed, three dispatches later.
    dc = str(fm.get("defect_class", ""))
    classes = G.defect_classes(G.load_overrides(CFG_PATH))
    if dc and dc != G.SMOKE and dc not in classes and not re.match(r"^regression:BUG-\d+$", dc):
        # a PROPOSED list: a class of it, or the door `new: <word> -- <why>` (F-3 (b)); the stage critic judges the new word
        errors.extend(f"{path.name}: FORM — defect_class {problem}"
                      for problem in C.open_word_errors(dc, sorted(classes) + [G.SMOKE, "regression:BUG-NNN"], "defect_class"))
    reuse = str(fm.get("reuse_decision", "")).split(":", 1)[0]
    if reuse and reuse not in CASE_REUSE_DECISION:
        errors.append(f"{path.name}: reuse_decision '{fm['reuse_decision']}' outside "
                      f"{sorted(CASE_REUSE_DECISION)} (`extend:<case id>` / `dedupe:<case id>` name the target)")
    # State-machine gate (mechanism 2)
    if fm.get("status") == "Automated":
        if not fm.get("red_probe"):
            errors.append(
                f"{path.name}: STATE MACHINE — status: Automated without red_probe. "
                "Only the code critic moves cases to Automated, and only after its probe, which sets `red_probe`."
            )
        ab = fm.get("automated_by", "")
        if not ab or ab == "null":
            errors.append(f"{path.name}: STATE MACHINE — status: Automated without automated_by (file::test)")
    if fm.get("red_lock") and not re.match(r"^(AT-)?BUG-\d+", fm.get("red_lock", "")):
        errors.append(f"{path.name}: red_lock '{fm['red_lock']}' does not reference BUG-NNN")
    # `preconditions` is optional and new in 0.7.8, so the law of this file is kept by the
    # field itself: a case that does not declare it (every case written before) is not
    # touched. Shape only — whether the stand MEETS them is `gate_preflight`'s question, asked
    # once before gate A, never on a write. The shape has one owner, shared with the rehearsal.
    if "preconditions" in fm:
        try:
            from gate_preflight import parse_preconditions
        except Exception:
            parse_preconditions = None  # a half-installed build validates what it can
        if parse_preconditions:
            for problem in parse_preconditions(fm.get("preconditions") or "")[1][:4]:
                errors.append(f"{path.name}: FORM — {problem}")
    # WP1/WP3 — case form (only for cases with updated >= RULE_CUTOFF; older ones — covers_ac).
    if G.after_cutoff(fm.get("updated")):
        check_case_form(path, fm, errors)
    elif not fm.get("covers") and not fm.get("covers_ac"):
        errors.append(f"{path.name}: neither covers (register) nor covers_ac — a case without traceability")
    # t-227 (P20): where each Then's expected value comes from. Position: after the form checks, on
    # its own date (ORACLE_CUTOFF, by day). Invariant: a case written before the cutoff is never
    # refused (builder rule 9), and an expected value whose only source is the implementation
    # never reaches gate A looking settled.
    if _oracle_dated(fm, "updated", path.name, errors, required_already=True):
        check_then_oracles(path, fm, case_text, errors)


ORACLE_NOTES: list = []   # the lines `--check --verbose` prints: a file the dated oracle rules leave alone


def _oracle_dated(fm: dict, field: str, name: str, errors: list, required_already: bool = False) -> bool:
    """Do the dated oracle rules (ORACLE_CUTOFF) apply to a file whose `field` (`created` / `updated`) is in `fm`?

    True from the cutoff day on; False for a date before it (the file is legacy and is never refused for
    lacking the new fields, builder rule 9 - one line says so in ORACLE_NOTES for `--check --verbose`). A
    date that is MISSING, empty or no ISO date is neither: it is refused here, naming the field and the form
    expected (t-269 F1) - before this, `after_oracle_cutoff` read it as "legacy" and every dated check was
    off with no word. `required_already`: the field is in the file kind's required list, so an ABSENT key has
    its own refusal already and is not said twice."""
    value = fm.get(field)
    problem = C.oracle_date_problem(value, field)
    if problem:
        if not (required_already and field not in fm):
            errors.append(f"{name}: FORM — {problem}")
        return False
    note = C.oracle_date_note(value, field)
    if note:
        ORACLE_NOTES.append(f"{name}: {note}")
    return C.after_oracle_cutoff(value)


def check_cell_counts(path: Path, text: str, heading: str, what: str, errors: list) -> None:
    """G2-10 (AR-9, AR-28): a row of the table under `heading` with more cells than its header holds a bare `|` inside a
    cell, and every cell after it would be read from another column. Code does not guess where the cell ends: the row is
    refused, naming its id, the counts and the door (the role writes the bar as `\\|`). By the file's own `created`
    (`C.CELL_COUNT_CUTOFF`): a file saved before it keeps the reading it was written under and gets one `--verbose`
    line (FR-14), a file from the cutoff on - or with a `created` nobody can read - is refused. Invariant: no row of a
    new file is read from the wrong column silently. A row SHORTER than its header (an older, narrower table) is left alone."""
    excess = C.excess_cell_rows(text, heading)
    new_world = C.after_cell_count_cutoff(text)
    for first, width, found in excess:
        line = (f"{path.name}: {first}: the {what} row holds {found} cells under a header of {width} - a bare `|` inside a cell "
                "ends the cell, so what follows lands in another column. Way on: write | inside a cell as \\| (for example a \\| b)")
        if new_world:
            errors.append(line)
        else:
            ORACLE_NOTES.append(f"{line}; the file is dated before {C.CELL_COUNT_CUTOFF}, so it is read as it was written")


def _story_root(register: Path) -> Path:
    """The story folder a register lives in (`work/` is one level down)."""
    return register.parent.parent if register.parent.name == C.WORK_DIR else register.parent


def _question_rows(story_root: Path):
    """{question id: register row with its status} from the readiness file and the answers file
    (`question_register.load`); None when the readiness file is missing or unreadable. Never raises:
    a half-installed build validates what it can."""
    try:
        import question_register as QR
        view = QR.load(story_root)
    except Exception:
        return None
    if not view.get("register_present"):
        return None  # no readiness file at all: the door an `unknown` needs does not exist
    return {q["id"]: q for q in view.get("questions", [])}


def _register_facts(task) -> tuple:
    """(register ids, text of the register, question rows) of the task, each None when absent."""
    if not task:
        return None, None, None
    known = register_ids(str(task))
    if known is None:
        return None, None, None
    register = register_path_for(str(task))
    return known, C.read_text(register), _question_rows(_story_root(register))


def _snapshot_facts(task, register_text) -> tuple:
    """(snapshot item ids, parity R ids) for C7; each None when absent (no task/register, no snapshot, or a half-installed build keeps the
    refusal direction). The snapshot is read from the story root of the register path, so an archived story finds its own."""
    if not task:
        return None, None
    try:
        import reference_snapshot
        items = reference_snapshot.item_ids(_story_root(register_path_for(str(task))))
    except Exception:
        items = None
    return items, (None if register_text is None else C.parity_ids(register_text))


def check_then_oracles(path: Path, fm: dict, text: str, errors: list) -> None:
    """`then_oracles` and the case `basis` of a case written on or after ORACLE_CUTOFF.

    Code checks presence, shape and refs; what a requirement's text supports is the case critic's
    judgment (FR-12/FR-47). The error direction of the implementation-only test is toward refusing
    an `ac` ref to an R the register derives from the diff alone: that costs a question, the other
    direction costs a test that can only pass."""
    try:
        from s5_precheck import then_clauses
        thens = [number for number, _ in then_clauses(text)]
    except Exception:
        return  # a half-installed build validates what it can
    known, register_text, questions = _register_facts(fm.get("task"))
    impl_only = None
    if register_text is not None:
        impl_only = C.unconfirmed_requirements(register_text, questions)
    snapshot_items, parity = _snapshot_facts(fm.get("task"), register_text)
    errors.extend(C.then_oracle_errors(
        path.name, fm.get("then_oracles") if "then_oracles" in fm else None,
        fm.get("question_thens") if "question_thens" in fm else None,
        thens, impl_only=impl_only, known_r=known, questions=questions,
        raw_raise_questions=fm.get("raise_questions") if "raise_questions" in fm else None,
        snapshot_items=snapshot_items, parity=parity, basis=fm.get("basis", "")))
    # TQ1-25: the optional `alternatives` key (the readings B a Then must fail under). Inside the dated block: a case
    # written before ORACLE_CUTOFF carries no such key (it is new) and is not checked. Shape and refs only (FR-12).
    errors.extend(C.alternatives_errors(path.name, fm.get("alternatives") if "alternatives" in fm else None, thens,
                                        known_r=known, questions=questions))
    # C12: the basis a case inherits from its plan row may not name an implementation-only R either.
    basis = str(fm.get("basis", "")).strip()
    named = C.requirement_id(basis)
    if named and impl_only and named in impl_only:
        errors.append(
            f"{path.name}: FORM — basis '{basis}' names {named}, which is implementation-only (derived "
            "from the diff alone): a requirement read from the code is not an oracle. Name what the expectation "
            "rests on instead (`consistency:<where before and now differ>` or `external:<ref>`); each Then "
            "says where its value comes from in `then_oracles`")


def register_path_for(task: str) -> Path:
    """The task's register — live path first, then any archived copy.

    A closed feature's folder may have been moved under `artifacts/_archive/<task>/`, which
    relocates the register together with every case file that cites it. Probing only the
    live path made every one of those cases report "the requirements are invented" and
    blocked the next handoff, for a move neither the cases nor the register took part in
    (TP1-13958). The live path still wins, so an un-archived story is unaffected."""
    art = artifact_root()
    live = C.artifact(art / str(task), "requirements-register.md")
    if live.exists():
        return live
    for archive in ("_archive", "archive"):
        archived = C.artifact(art / archive / str(task), "requirements-register.md")
        if archived.exists():
            return archived
    return live  # the message names the live path: that is where it should have been


def register_ids(task: str) -> set | None:
    """The set of R-ids of the task's register; None — there is no register."""
    p = register_path_for(task)
    if not p.exists():
        return None
    fm = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace")) or {}
    return set(G.parse_inline_list(fm.get("ids")))


def check_case_form(path: Path, fm: dict, errors: list) -> None:
    """A case is the unit of coverage of a register requirement, not of an AC: covers resolves
    into the task's register, defect_class and basis are inherited from the plan row (not reassigned)."""
    for field in CASE_FORM_REQUIRED:
        if not fm.get(field):
            errors.append(
                f"{path.name}: FORM — '{field}' is missing (a case with updated >= {G.RULE_CUTOFF}: "
                "task, covers: [R-n], defect_class, basis — inherited from the plan row)"
            )
    covers = G.parse_inline_list(fm.get("covers"))
    r_ids = [c for c in covers if G.REQ_ID_RE.match(c)]
    bad = [c for c in covers if not G.REQ_ID_RE.match(c) and not c.startswith("legacy:")]
    if bad:
        errors.append(f"{path.name}: FORM — covers {bad}: only register R-n or legacy:<import reason> are allowed")
    if r_ids and fm.get("task"):
        known = register_ids(fm["task"])
        if known is None:
            errors.append(
                f"{path.name}: FORM — covers references {r_ids}, but the register "
                f"{register_path_for(fm['task']).as_posix()} does not exist: the requirements are invented or the task is mixed up"
            )
        else:
            missing = [r for r in r_ids if r not in known]
            if missing:
                errors.append(f"{path.name}: FORM — covers {missing} are not in the register of task {fm['task']}")
    basis = str(fm.get("basis", ""))
    if basis and not G.ORACLE_RE.match(basis):
        errors.append(
            f"{path.name}: FORM — basis '{basis}' is not per the oracle grammar "
            "(requirement:R-n | invariant:<id> | consistency:<where it differs> | history:<baseline> | impact:<harm> | external:<norm>)"
        )


def check_bug(path: Path, errors: list) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(text)
    if fm is None:
        errors.append(f"{path.name}: no YAML frontmatter")
        return
    for field in BUG_REQUIRED:
        if field not in fm or fm[field] == "":
            errors.append(f"{path.name}: required field '{field}' is missing")
    if fm.get("status") and fm["status"] not in BUG_STATUS:
        errors.append(f"{path.name}: status '{fm['status']}' outside {sorted(BUG_STATUS)}")
    if fm.get("severity") and fm["severity"] not in BUG_SEVERITY:
        errors.append(f"{path.name}: severity '{fm['severity']}' outside the allowed set")
    if G.after_cutoff(fm.get("created")):
        check_bug_form(path, fm, text, errors)


def check_bug_filing_header(path: Path, fm: dict, errors: list) -> None:
    """HF8-21: a bug filed from a draft of this run (it carries `source_draft`) names the case(s) and the requirement(s) it is about,
    or says why it names no case (`cases: []` with `no_case_reason`). A bug file with no `source_draft` is an older one and is not
    asked: the report reads such a file as it always did. The R-n is asked only when the oracle IS a requirement: a bug whose
    `violates` is `invariant:` / `consistency:` / `history:` / `impact:` / `external:` has no R-n to name, and `requirements: []`
    is its empty outcome (FR-2: the door a refusal names must exist)."""
    def listed(field: str) -> list:
        return [c for c in G.parse_inline_list(fm.get(field)) if c and c != "-"]
    cases = listed("cases") or listed("case")
    if not cases and not str(fm.get("no_case_reason", "")).strip().strip("-"):
        errors.append(f"{path.name}: FORM — 'cases' is missing or empty (the case ids the bug is about, from the draft's `case`/`cases`); "
                      "a bug about no case says `cases: []` and writes `no_case_reason` (why)")
    oracle_is_requirement = str(fm.get("violates", "")).strip().startswith("requirement:")
    if oracle_is_requirement and not listed("requirements"):
        errors.append(f"{path.name}: FORM — 'requirements' is missing or empty (the R-n the draft's `violates` names; the report counts a "
                      "bug against them)")


def check_bug_form(path: Path, fm: dict, text: str, errors: list, draft=None) -> None:
    """t-2187 N4 (one bug, many manifestations; AR-21, AR-27): `draft` is the RESOLVED source draft of the bug (a dict; `{}` is
    a draft that could not be read), handed in by `artifact_producer.validate`, the only caller that has the story folder. With
    `draft=None` the manifestation check below is NOT run and says nothing: the caller that cannot resolve a draft says so in
    its own not-checked line, never a pass (FR-59). With a draft of 2+ manifestations (one confirmed cause, several ways it
    shows) the bug file must list every case the draft speaks for in `cases`, carry `## Cause` and `## Manifestations`, and the
    `## Manifestations` text must hold each manifestation's case and its red test command (or the reason there is none): a
    PRESENCE check of data the draft already holds; whether the text is true or the cause is the cause stays the reporter's and
    the person's. A draft with fewer than 2 manifestations (an old draft, an ordinary bug) adds no check: the file is valid
    exactly as before.

    WP4 / X7-5: the oracle is a ROUTE word per the grammar (a finding without an oracle is an observation, not a bug; `code:`
    is refused - the code is never the oracle, P20), the impact is a class of the scale, the impact and initial-state sections
    are mandatory, the red test (or why there is none) is with the bug (P28). The severity is the reporter's call: the scale
    `impact -> severity` of config.json is a suggestion in the role's charter, and a severity that differs from it is NOT
    refused here (F-X7-8 (a)); the value itself stays a closed word (`BUG_SEVERITY`, checked in `check_bug`: the dashboard
    and the metrics read it)."""
    cfg = G.load_overrides(CFG_PATH)
    scale = G.impact_scale(cfg)
    for field in BUG_FORM_REQUIRED:
        if not fm.get(field):
            errors.append(f"{path.name}: FORM — '{field}' is missing (an impact class from the scale {sorted(scale)})")
    violates = str(fm.get("violates", ""))
    if violates and not G.ORACLE_RE.match(violates):
        if re.match(r"\s*code\s*:", violates, re.IGNORECASE):
            errors.append(
                f"{path.name}: FORM — violates '{violates}': the code is never the oracle (P20) - a test or a bug whose "
                "expectation is read from the implementation can only pass. Name what the product must do instead, one of "
                "requirement:R-n | invariant: | consistency: | history: | impact: | external:"
            )
        else:
            errors.append(
                f"{path.name}: FORM — violates '{violates}' is not one of the oracle kinds "
                "(requirement:R-n | invariant: | consistency: | history: | impact: | external:). "
                "No oracle from the list -> this is an observation, not a bug"
            )
    impact = str(fm.get("impact", ""))
    if impact and impact not in scale:
        errors.append(f"{path.name}: FORM — impact '{impact}' outside the scale {sorted(scale)}")
    if str(fm.get("source_draft", "")).strip() and C.red_test_owed(fm):
        for problem in C.red_test_problems(fm, flat=True):
            errors.append(f"{path.name}: FORM — {problem}")
    confirmation = str(fm.get("confirmation", "")).strip()
    if confirmation and confirmation not in C.BUG_CONFIRMATIONS:
        errors.append(
            f"{path.name}: FORM — confirmation '{confirmation}' outside "
            f"{sorted(C.BUG_CONFIRMATIONS)}"
        )
    elif not confirmation and str(G.date_prefix(fm.get("created")) or "") >= BUG_CONFIRMATION_CUTOFF:
        errors.append(
            f"{path.name}: FORM — 'confirmation' is missing (one of {sorted(C.BUG_CONFIRMATIONS)}). "
            "A bug nobody has reproduced is `unconfirmed`, and the report and the gate show it "
            "apart from the ones a person or a second run stood behind"
        )
    if str(fm.get("source_draft", "")).strip() and str(G.date_prefix(fm.get("created")) or "") >= BUG_FILING_HEADER_CUTOFF:
        check_bug_filing_header(path, fm, errors)
    lines = text.splitlines()
    for heading in BUG_FORM_SECTIONS:
        if not G.section_present(lines, heading):
            errors.append(f"{path.name}: FORM — no \"{heading}\" section (without it the defect record is irreproducible/unassessable)")
    if draft is None:
        return
    import bug_records as BR   # late: the ONE reader of a draft's cases and manifestations (AR-13); the module imports contract/hooklib only
    if not draft:
        errors.append(f"{path.name}: FORM — the source draft '{str(fm.get('source_draft', '')).strip()}' cannot be read, so its manifestations "
                      "cannot be checked; `source_draft` must name the draft file as it stands under work/bug-drafts/ "
                      "(`work/bug-drafts/<file>.json`)")
        return
    if len(BR.manifestation_summary(draft)) < 2:
        return
    stem = Path(str(fm.get("source_draft", ""))).stem or "<draft>"
    door = f"work/bug-text/{stem}.md holds the cause and one line per manifestation to copy from"

    def ids(cells) -> list:
        out: list = []
        for cell in cells:
            for one in C.case_ids(cell) or [str(cell).strip()]:
                if one and one not in out:
                    out.append(one)
        return out

    named = ids(G.parse_inline_list(fm.get("cases")) or G.parse_inline_list(fm.get("case")))
    owed = [one for one in ids(BR.draft_cases(draft)) if one not in named]
    if owed:
        errors.append(f"{path.name}: FORM — 'cases' lacks {owed}: the source draft is one bug with several manifestations and the bug "
                      f"lists every case they name (expected: {ids(BR.draft_cases(draft))}); add them to `cases`")
    for heading in ("## Cause", "## Manifestations"):
        if not G.section_present(lines, heading):
            errors.append(f"{path.name}: FORM — no \"{heading}\" section: the source draft has several manifestations of one cause, "
                          f"so the bug file states the cause and lists each manifestation ({door})")
    start = next((i for i, line in enumerate(lines) if line.strip().startswith("## Manifestations")), None)
    if start is None:
        return
    body = []
    for line in lines[start + 1:]:
        if line.strip().startswith("## "):
            break
        body.append(line)
    squashed = " ".join(" ".join(body).split())
    for entry in BR.manifestation_entries(draft):
        case = str(entry.get("case") or "").strip()
        if case and case not in squashed:
            errors.append(f"{path.name}: FORM — the \"## Manifestations\" section does not name the case {case}: one line per "
                          f"manifestation, each with its case ({door})")
        red = entry.get("red_test")
        wanted = str(red.get("command") or "").strip() if isinstance(red, dict) else str(red or "").strip()
        label = "its red test command"
        if not wanted:
            wanted, label = str(entry.get("red_test_none") or "").strip(), "the reason it has no red test"
        wanted = " ".join(wanted.split())
        if wanted and wanted not in squashed:
            errors.append(f"{path.name}: FORM — the \"## Manifestations\" line of {case or 'a manifestation'} lacks {label} "
                          f"('{wanted[:80]}'): each manifestation keeps its own red test, or says why there is none ({door})")


def check_register(path: Path, errors: list) -> None:
    """WP1/WP2: the requirements register — the unit of coverage. What is checked is the walk
    over the finite sets (source from the list, derived with a binding, matrix cells per the
    grammar), not the quality of the wording — a human judges that at the understanding gate."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(text)
    if fm is None:
        errors.append(f"{path.name}: no YAML frontmatter")
        return
    for field in REGISTER_REQUIRED:
        if field not in fm:
            errors.append(f"{path.name}: required field '{field}' is missing")
    ids = G.parse_inline_list(fm.get("ids"))
    if not ids:
        errors.append(f"{path.name}: ids is empty — a register without requirements; there is no story without a single requirement")
    bad_ids = [i for i in ids if not G.REQ_ID_RE.match(i)]
    if bad_ids:
        errors.append(f"{path.name}: ids {bad_ids} are not of the form R-n")
    by_source = G.parse_inline_dict_int(fm.get("by_source"))
    unknown = sorted(set(by_source) - G.REQ_SOURCES)
    if unknown:
        errors.append(f"{path.name}: by_source contains sources outside the list {sorted(G.REQ_SOURCES)}: {unknown}")
    if fm.get("confidence") and fm["confidence"] not in ("high", "low"):
        errors.append(f"{path.name}: confidence '{fm['confidence']}' outside high|low")
    lines = text.splitlines()
    rows = G.table_rows(lines, REGISTER_HEADING)
    if not rows:
        errors.append(f"{path.name}: the \"{REGISTER_HEADING}\" section has no table rows")
    check_cell_counts(path, text, REGISTER_HEADING, "register", errors)
    seen = set()
    for cells in rows:
        rid = cells[0]
        if not G.REQ_ID_RE.match(rid):
            continue
        seen.add(rid)
        if len(cells) < 4:
            errors.append(f"{path.name}: {rid}: the row is shorter than the form (R · requirement · source · derived_from · …)")
            continue
        source = cells[2]
        if source not in G.REQ_SOURCES:
            errors.append(f"{path.name}: {rid}: source '{source}' outside {sorted(G.REQ_SOURCES)}")
        if source == "derived" and not G.DERIVED_FROM_RE.match(cells[3]):
            errors.append(
                f"{path.name}: {rid}: derived without derived_from per the grammar "
                "(aspect:<name> | seam:<A×B> | invariant:<id> | test:<ref> | norm:<ref> | bug:BUG-NNN | bug:candidate-defect | "
                "case:<case id> | baseline:<surface>) — "
                "a derived requirement must name what it was derived from"
            )
        elif source == "derived" and not C.derived_from_legal(cells[3]):
            # G2-15 (N11): a misspelt `bug:` mark would lose the requirement's road to a test, so it is refused with its door
            errors.append(
                f"{path.name}: {rid}: `derived_from` says '{cells[3]}': `bug:` takes a bug id (`bug:BUG-12`) or "
                "`bug:candidate-defect` for a suspect place in the code; a misspelt mark would lose the requirement's road to a test."
            )
        # v0: every register row names where its observable was seen, or `none` — and `none`
        # is a gate-A question to the owner, never a silent skip (design section 7.2).
        if len(cells) >= 7:
            obs = cells[6].strip().strip("`")
            if obs and not (obs.startswith("none")
                            or any(obs == s or obs.startswith(s + ":") for s in OBSERVABLE_SOURCES_V0)):
                errors.append(
                    f"{path.name}: {rid}: observable '{obs}' names no source — prefix it with "
                    f"{list(OBSERVABLE_SOURCES_V0)} or write `none` (which becomes a gate-A question)"
                )
        # The impact column (0.7.7): "what breaks for the user if this requirement is
        # violated", from the project's own closed scale — it is what sizing.py weighs.
        if len(cells) >= 8 and cells[7].strip():
            impact = cells[7].strip().strip("`")
            scale = G.impact_scale(G.load_overrides(CFG_PATH))
            if scale and impact not in scale:
                errors.append(f"{path.name}: {rid}: impact '{impact}' outside the project's impact "
                              f"scale {sorted(scale)} (config.json impact_scale)")
    try:
        C.register_rows(text)
    except ValueError as exc:           # the role's header, not a defect of the factory (FR-46): refused with the header named
        errors.append(f"{path.name}: {exc}")
    else:
        check_delta_column(path, text, errors)
    check_manifest_reuse(path, text, rows, errors)
    missing_rows = [i for i in ids if i not in seen]
    if missing_rows:
        errors.append(f"{path.name}: ids {missing_rows} are declared in the frontmatter, but there are no rows in the register")
    # Contradiction matrix: only when the section exists (WP2); cells — per the grammar.
    for cells in G.table_rows(lines, REGISTER_MATRIX_HEADING):
        if not G.REQ_ID_RE.match(cells[0]):
            continue
        for cell in cells[1:]:
            if cell and not G.CONTRADICTION_CELL_RE.match(cell):
                errors.append(
                    f"{path.name}: matrix {cells[0]}: cell '{cell}' outside the grammar "
                    "(ok:<ref> | contradicts:<quote> | silent | n/a:<reason>) — ok without a reference is not accepted"
                )
    # t-227 (P20): a requirement that exists only in the diff is a behaviour claim, not a requirement.
    # Position: after the matrix walk, because the matrix is half of what makes an R implementation-only;
    # gated by the register's own `created` (ORACLE_CUTOFF, by day). Invariants: an implementation-only R
    # never reaches S3 without its before/now and its question; the `## Register` columns are untouched.
    if _oracle_dated(fm, "created", path.name, errors, required_already=True):
        check_behaviour_claims(path, text, errors)


def check_delta_column(path: Path, text: str, errors: list) -> None:
    """The register's `delta` column (written at S2, LAST after `impact`), when the register HAS one: every row
    carries exactly `new`, `changed` or `unchanged`, and an `unchanged` row does not cite the diff as its
    observable (a requirement seen only in the diff did not hold before the MR). A register with no `delta`
    column is not checked (every register written before the column; its rows count as expected to change -
    `contract.delta_state` says `absent`). Reads through `contract.register_rows`/`delta_state`, never by position."""
    for row in C.register_rows(text):
        state = C.delta_state(row)
        if state == "invalid":
            errors.append(
                f"{path.name}: {row['r']}: delta '{row['delta']}' is none of {' | '.join(C.DELTA_WORDS)} "
                "(exactly these lowercase words; an empty cell is not one) - write what the product did BEFORE this MR "
                "for the behaviour the requirement states: no such behaviour (new), a different one (changed), the same (unchanged)")
        elif state == "unchanged" and row["observable"].startswith("diff:"):
            errors.append(
                f"{path.name}: {row['r']}: delta unchanged with observable '{row['observable']}' contradicts itself: "
                "a requirement the code shows only in the diff did not hold before this MR. Write delta new or changed, "
                "or point the observable at code outside the MR (current-code:<path:line>); writing `current-code:` keeps "
                "the row in the coverage count - only the base slice code reads (G1-8) takes an unchanged row out of it")


def _snapshot_items(story_root):
    """The ids of the story's reference snapshot for a claim's `before_ref: reference:<item>` (PC-9c B1), read through
    `reference_snapshot.item_ids`; None when there is none, it cannot be read, or the build is half-installed (the claim form is then refused)."""
    try:
        import reference_snapshot
        return reference_snapshot.item_ids(story_root)
    except Exception:
        return None


def check_behaviour_claims(path: Path, text: str, errors: list) -> None:
    """`## Behaviour claims` for every implementation-only R (computed by code from the register,
    never declared: F10/FR-16). The readiness file may be written after the register, so its
    question ids are checked only when it is already there (the register's own shape always is).
    The `origin` of EVERY row of the table is judged here, whichever R it names (empty = written at S2)."""
    claims: dict = {}
    for row in C.behaviour_claims(text):
        origin = row.get("origin", "")
        if origin not in C.EMPTY_CELLS and origin != C.CLAIM_ORIGIN_S3:
            errors.append(f"{path.name}: {row['r']}: behaviour claim — `origin` '{origin}' is none of: "
                          f"empty (written at S2) | {C.CLAIM_ORIGIN_S3}")
        if row["r"] in claims:
            errors.append(f"{path.name}: {row['r']}: appears twice under \"{C.CLAIM_HEADING}\" — one claim per requirement")
            continue
        claims[row["r"]] = row
    questions = _question_rows(_story_root(path))
    link_index = C.claim_link_index(questions)
    snapshot_items = _snapshot_items(_story_root(path))
    for rid in C.claim_required_requirements(text):
        row = claims.get(rid)
        if row is None:
            errors.append(
                f"{path.name}: {rid} is implementation-only and has no behaviour claim — it is derived from the diff, the "
                "current code or another test alone (no ticket source speaks to it), so what it says is a claim about the code, not a requirement. "
                f"Add a row under \"{C.CLAIM_HEADING}\" ({' | '.join(['R'] + [c for c in C.CLAIM_COLUMNS[1:] if c != 'origin'])}): what the behaviour was "
                "before the change, what it is now, and the question that asks the person which one is expected")
            continue
        for problem in C.claim_row_errors(row, questions, link_index, snapshot_items=snapshot_items):
            errors.append(f"{path.name}: {rid}: behaviour claim — {problem}")


def _norm_path(value: str) -> str:
    return str(value or "").strip().strip("`").replace("\\", "/").lstrip("./").lower()


def _manifest_known_paths(path: Path) -> set | None:
    """Every file path S1 put on record: each observable's `path`, plus anything its `trail`
    names. None when there is no manifest to compare against (a fixture, a story that never
    ran S1) — in which case the reuse rule does not apply."""
    manifest = _sibling(path, "context-manifest.json")
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None
    known = set()
    for obs in data.get("observables") or []:
        if isinstance(obs, dict) and obs.get("path"):
            known.add(_norm_path(obs["path"]))
    trail = data.get("trail")
    for item in (trail if isinstance(trail, list) else [trail]):
        if isinstance(item, dict):
            for value in item.values():
                if isinstance(value, str):
                    known.add(_norm_path(value))
                elif isinstance(value, list):
                    known.update(_norm_path(v) for v in value if isinstance(v, str))
        elif isinstance(item, str):
            known.add(_norm_path(item))
    return {p for p in known if p}


def check_manifest_reuse(path: Path, text: str, rows: list, errors: list) -> None:
    """S1 gathers evidence; S2 turns it into requirements. A path S2 cites that S1 never
    recorded means the manifest had a hole — and that is a fact worth keeping.

    On QA-EXAMPLE the requirements tester went back into the application code
    (`entity.ts`, `canEdit`) although the manifest carried 24 grounded observables: the
    stage read code, produced requirements, and left no trace that the handover had been
    insufficient. So the next story repeated it. A code lookup at S2 stays legal; what it
    must not stay is invisible — name it in a `manifest_gap` line (what you looked for, why
    the manifest did not answer, what you found), and the retro can count them."""
    known = _manifest_known_paths(path)
    if known is None:
        return
    lowered = text.lower()
    for cells in rows:
        if len(cells) < 7 or not G.REQ_ID_RE.match(cells[0]):
            continue
        obs = cells[6].strip().strip("`")
        if ":" not in obs:
            continue
        source, _, where = obs.partition(":")
        if source.strip() not in ("diff", "current-code"):
            continue
        cited = _norm_path(where.rsplit(":", 1)[0] if ":" in where else where)
        if not cited or cited.startswith("<"):
            continue
        if any(cited == k or cited.endswith("/" + k) or k.endswith("/" + cited) for k in known):
            continue
        if "manifest_gap" in lowered and cited in lowered.replace("\\", "/"):
            continue
        errors.append(
            f"{path.name}: {cells[0]}: observable cites '{cited}', which context-manifest.json "
            "never recorded — S1's evidence is what S2 builds on. If the manifest really did "
            "not answer, keep the fact: add a `manifest_gap` line naming that path, what you "
            "looked for and why the manifest fell short. Silent re-reading of the "
            "implementation is how the same gap survives into the next story.")


def check_plan(path: Path, errors: list) -> None:
    """WP3: the plan is a risk map. Every row: defect class @ place (or smoke), impact from
    the scale, priority = the one derived from impact, a non-empty independent observation, a basis
    per the oracle grammar. Applies to plans with created >= RULE_CUTOFF."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(text)
    if fm is None or not G.after_cutoff(fm.get("created")):
        return
    cfg = G.load_overrides(CFG_PATH)
    classes = G.defect_classes(cfg)
    scale = G.impact_scale(cfg)
    for field in PLAN_REQUIRED:
        if field not in fm:
            errors.append(f"{path.name}: FORM — required field '{field}' is missing")
    lines = text.splitlines()
    rows = [r for r in G.table_rows(lines, PLAN_SCENARIOS_HEADING) if r and r[0].startswith("TS-")]
    if not rows:
        errors.append(f"{path.name}: FORM — the \"{PLAN_SCENARIOS_HEADING}\" section has no TS-* rows")
    smoke = 0
    by_class: dict = {}
    for cells in rows:
        tsid = cells[0]
        if len(cells) < 8:
            errors.append(
                f"{path.name}: {tsid}: the row is shorter than the risk-map form "
                "(TS · R · what can go wrong · impact · priority · experiment · observation · basis · …)"
            )
            continue
        r_cell, risk, impact, prio, experiment, observation, basis = cells[1:8]
        if not all(G.REQ_ID_RE.match(x) for x in G.parse_inline_list(r_cell)) or not r_cell:
            errors.append(f"{path.name}: {tsid}: the R column '{r_cell}' — register R-ids are required")
        if risk == G.SMOKE:
            smoke += 1
        else:
            m = G.DEFECT_CLASS_RE.match(risk)
            door = m.group("new") if m else None
            cls = (m.group("cls") or "") if m else ""
            if door is not None:
                # `new:<word> -- <why> @ <place>`: the form is code's, the word is the stage critic's (F-3 (b))
                bad = C.open_word_errors(door, sorted(classes), "defect_class")
                errors.extend(f"{path.name}: {tsid}: \"what can go wrong\" {problem}" for problem in bad)
                if not bad:
                    by_class[door.strip()] = by_class.get(door.strip(), 0) + 1
            elif not m or (cls not in classes and not cls.startswith("regression:")):
                errors.append(
                    f"{path.name}: {tsid}: \"what can go wrong\" '{risk}' — needs `<class> @ <place>` "
                    f"with a class from {sorted(classes)} | regression:BUG-NNN, or `smoke`, "
                    "or a new class as `new: <word> -- <why> @ <place>`"
                )
            else:
                by_class[cls] = by_class.get(cls, 0) + 1
        if impact not in scale:
            errors.append(f"{path.name}: {tsid}: impact '{impact}' outside the scale {sorted(scale)}")
        elif prio != scale[impact]["priority"]:
            errors.append(
                f"{path.name}: {tsid}: priority '{prio}' does not match the one derived from impact '{impact}' -> "
                f"'{scale[impact]['priority']}' (priority is derived, not assigned)"
            )
        if not observation or observation.lower() in ("-", "—"):
            errors.append(f"{path.name}: {tsid}: empty \"distinguishing observation\" — how do we tell a failure from the norm via an independent channel?")
        if not G.ORACLE_RE.match(basis):
            errors.append(f"{path.name}: {tsid}: basis '{basis}' is not per the oracle grammar (requirement:R-n | invariant: | consistency: | history: | impact: | external:)")
    plan_profile = str(fm.get("profile", "feature"))
    if plan_profile not in G.PLAN_PROFILES:
        errors.append(f"{path.name}: profile '{plan_profile}' outside {sorted(G.PLAN_PROFILES)}")
    if plan_profile == "parity":
        # V1, DORMANT IN v0: the v0 test-plan carries no `profile` key, so this branch never runs
        # (the default is "feature"); parity testing and the "before" snapshot are v1.
        # A parity plan: a row without a history:/invariant: basis does not compare "before" with "after" —
        # for a refactoring that is a check that it "works", not that it "did not change".
        weak = [c[0] for c in rows if len(c) >= 8 and c[2] != G.SMOKE
                and not re.match(r"^(history|invariant):", c[7])]
        if weak and len(weak) > len(rows) // 2:
            errors.append(
                f"{path.name}: FORM — profile parity, but {len(weak)} of {len(rows)} rows have a basis other than history:/invariant: "
                f"({', '.join(weak[:5])}…): a parity row compares the \"before\" snapshot with \"after\" via an independent channel"
            )
    reg_total = str(fm.get("requirements_total", "")).strip()
    if reg_total.isdigit() and smoke > int(reg_total):
        errors.append(
            f"{path.name}: FORM — {smoke} smoke rows exceed the number of requirements {reg_total}: "
            "at most one smoke per requirement, the rest must fail on a defect"
        )
    fm_smoke = str(fm.get("smoke", "")).strip()
    if fm_smoke.isdigit() and int(fm_smoke) != smoke:
        errors.append(f"{path.name}: frontmatter smoke={fm_smoke}, the table has {smoke} smoke rows — recount by fact")
    if reg_total.isdigit() and int(reg_total) >= 5 and rows and len(by_class) == 1 and smoke == 0:
        errors.append(
            f"{path.name}: FORM — all {len(rows)} rows are of one class {list(by_class)} against {reg_total} requirements: "
            "a monoclass is a sign of vacuum hypotheses; set confidence: low and name at the gate which classes are excluded and why"
        )
    if not G.section_present(lines, PLAN_SEAMS_HEADING):
        errors.append(
            f"{path.name}: FORM — no \"{PLAN_SEAMS_HEADING}\" section (for every seam in the register's seams_touched — a row or an explicit N/A; "
            "no seams — a section with a single line \"no seams found: <the register's seams_search>\")"
        )
    # Roll call against the register: every R — in a plan row or in the na_requirements list.
    task = str(fm.get("task", ""))
    known = register_ids(task) if task else None
    if known:
        covered = set()
        for cells in rows:
            if len(cells) > 1:
                covered |= set(G.parse_inline_list(cells[1]))
        na = set(G.parse_inline_list(fm.get("na_requirements")))
        orphan = sorted(known - covered - na, key=lambda s: int(s.split("-")[1]))
        if orphan:
            errors.append(
                f"{path.name}: FORM — requirements {orphan} without a plan row and without na_requirements — "
                "every R gets a scenario or an explicit N/A with a reason"
            )


def check_ptr_readiness(path: Path, lines: list, errors: list) -> None:
    """WP3: closing the story by requirements. If the task has a register — the PTR must carry
    "Readiness within what was verified": every R with a status from the three outcomes."""
    task = path.parent.name
    known = register_ids(task)
    if not known:
        return
    if not G.section_present(lines, PTR_READINESS_HEADING):
        errors.append(
            f"{path.name}: FORM — the task has a requirements register, but there is no \"{PTR_READINESS_HEADING}\" section "
            "(every R: verified / not verified / deferred by design / deferred by decision + evidence or a reason)"
        )
        return
    rows = G.table_rows(lines, PTR_READINESS_HEADING)
    seen = {}
    for cells in rows:
        if G.REQ_ID_RE.match(cells[0]) and len(cells) > 1:
            seen[cells[0]] = cells[1]
    missing = sorted(known - set(seen), key=lambda s: int(s.split("-")[1]))
    if missing:
        errors.append(f"{path.name}: FORM — requirements {missing} without a row in \"{PTR_READINESS_HEADING}\": an absent row reads as a verified one")
    for rid, status in seen.items():
        if status not in G.PTR_REQ_STATUSES:
            errors.append(f"{path.name}: FORM — {rid}: status '{status}' outside {sorted(G.PTR_REQ_STATUSES)}")


def check_escape_ledger(path: Path, errors: list) -> None:
    """WP6: the escape ledger (JSON Lines). Every escaped or rejected bug is a line
    naming the stage and the missed element of a finite set.

    V1, DORMANT IN v0: the v0 artifact contract (references/artifact-contract.md) has no
    such file, so this rule can never fire in v0 — it is kept, tested by form_selftest.py,
    and waits for the v1 stage that writes the artifact. Audit A11 ignores it: A11 only
    governs PHASE_JSON_KEYS, the unconditional v0 schema table.
    """
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as e:
            errors.append(f"{path.name}: line {i}: broken JSON ({e})")
            continue
        if not isinstance(row, dict):
            errors.append(f"{path.name}: line {i}: not a JSON object")
            continue
        for key in ESCAPE_LEDGER_REQUIRED:
            if key not in row:
                errors.append(f"{path.name}: line {i}: key '{key}' is missing")
        stage = row.get("stage_should_have_caught")
        if stage not in G.ESCAPE_STAGES:
            errors.append(
                f"{path.name}: line {i}: stage_should_have_caught '{stage}' outside {sorted(G.ESCAPE_STAGES)} "
                "(the layer vocabulary of mode E of qa-failure-analyst / qa-escape)"
            )
        missing = str(row.get("missing_element", ""))
        if stage in G.ESCAPE_STAGES_WITH_ELEMENT and not G.ESCAPE_MISSING_RE.match(missing):
            errors.append(
                f"{path.name}: line {i}: missing_element '{missing}' — for layer '{stage}' name the element of the set "
                "(aspect: | seam: | perturbation: | class: | oracle:) that was lacking"
            )
        if stage in G.ESCAPE_STAGES and stage not in G.ESCAPE_STAGES_WITH_ELEMENT and not str(row.get("reason", "")).strip():
            errors.append(f"{path.name}: line {i}: layer '{stage}' without reason — \"no set is to blame\" requires a justification")


def check_charter(path: Path, errors: list) -> None:
    """Charter state machine: Proposed -> (critic PASS) -> Planned -> InProgress -> Done.

    V1, DORMANT IN v0: the v0 artifact contract (references/artifact-contract.md) has no
    such file, so this rule can never fire in v0 — it is kept, tested by form_selftest.py,
    and waits for the v1 stage that writes the artifact. Audit A11 ignores it: A11 only
    governs PHASE_JSON_KEYS, the unconditional v0 schema table.
    """
    fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    if fm is None:
        errors.append(f"{path.name}: no YAML frontmatter")
        return
    for field in CHARTER_REQUIRED:
        if field not in fm or fm[field] == "":
            errors.append(f"{path.name}: required field '{field}' is missing")
    if fm.get("status") and fm["status"] not in CHARTER_STATUS:
        errors.append(f"{path.name}: status '{fm['status']}' outside {sorted(CHARTER_STATUS)}")
    if fm.get("trigger") and fm["trigger"] not in CHARTER_TRIGGER:
        errors.append(f"{path.name}: trigger '{fm['trigger']}' outside {sorted(CHARTER_TRIGGER)}")
    status = fm.get("status", "")
    if status in ("Planned", "InProgress", "Done") and not fm.get("plan_review"):
        errors.append(
            f"{path.name}: STATE MACHINE — status: {status} without plan_review. "
            "Proposed -> Planned only via a critic verdict (PASS:<ISO>) or an explicit lead-direct."
        )
    if status == "Done":
        for field in ("executed_at", "executed_by"):
            if not fm.get(field):
                errors.append(f"{path.name}: STATE MACHINE — Done without {field}")
        if "mission_leftover" not in fm:
            errors.append(
                f"{path.name}: STATE MACHINE — Done without the mission_leftover field "
                "(an empty list is valid, a missing field is not: charter-designer reads it)"
            )
    if G.after_cutoff(fm.get("created")):
        check_charter_form(path, fm, errors)


def check_charter_form(path: Path, fm: dict, errors: list) -> None:
    """WP5: a seed path is created for the sake of hypotheses. Every H — an oracle, a refuting
    observation, a binding to a finite set; Planned requires seams; Done — a status for every H,
    not-probed duplicated into mission_leftover."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    status = fm.get("status", "")
    hyp_ids = G.parse_inline_list(fm.get("hypotheses"))
    rows = G.table_rows(lines, CHARTER_HYPOTHESES_HEADING)
    table_ids = {c[0] for c in rows if G.HYPOTHESIS_ID_RE.match(c[0])}
    if status in ("Planned", "InProgress", "Done"):
        if not G.parse_inline_list(fm.get("seams")):
            errors.append(f"{path.name}: FORM — status {status} with empty seams: at least one seam hypothesis per charter")
        if not hyp_ids:
            errors.append(f"{path.name}: FORM — status {status} without hypotheses in the frontmatter")
    bindings = []
    for cells in rows:
        hid = cells[0]
        if not G.HYPOTHESIS_ID_RE.match(hid):
            continue
        if len(cells) < 5:
            errors.append(f"{path.name}: {hid}: the row is shorter than the form (H · claim · oracle · refuting observation · binding)")
            continue
        oracle, observation, binding = cells[2], cells[3], cells[4]
        if not G.ORACLE_RE.match(oracle):
            errors.append(f"{path.name}: {hid}: oracle '{oracle}' is not per the grammar (requirement:R-n | invariant: | consistency: | history: | impact: | external:)")
        if not observation or observation in ("-", "—"):
            errors.append(f"{path.name}: {hid}: no refuting observation named — the hypothesis is unfalsifiable")
        if not G.HYPOTHESIS_BINDING_RE.match(binding):
            errors.append(f"{path.name}: {hid}: binding '{binding}' outside (perturbation:<axis×zone> | seam:<A×B> | bug-class:BUG-NNN | reading:<Qn>)")
        bindings.append(binding)
    if hyp_ids and status in ("Planned", "InProgress", "Done"):
        declared_missing = [h for h in hyp_ids if h not in table_ids]
        if declared_missing:
            errors.append(f"{path.name}: FORM — hypotheses {declared_missing} are declared, but there are no rows in \"{CHARTER_HYPOTHESES_HEADING}\"")
        if bindings and not any(b.startswith("seam:") for b in bindings):
            errors.append(f"{path.name}: FORM — not a single hypothesis with a seam: binding — cross-feature checks have vanished from the charter")
    if status == "Done":
        findings = G.table_rows(lines, CHARTER_FINDINGS_HEADING)
        statuses = {}
        for cells in findings:
            if G.HYPOTHESIS_ID_RE.match(cells[0]) and len(cells) > 2:
                statuses[cells[0]] = cells[2]
        for h in hyp_ids:
            st = statuses.get(h)
            if st is None:
                errors.append(f"{path.name}: FORM — Done, but {h} has no row with a status in \"{CHARTER_FINDINGS_HEADING}\"")
            elif st not in G.HYPOTHESIS_STATUSES:
                errors.append(f"{path.name}: FORM — {h}: status '{st}' outside {sorted(G.HYPOTHESIS_STATUSES)} (the self-verdict \"ok\" is gone: refuted with a witness or not-probed)")
            elif st == "not-probed" and h not in str(fm.get("mission_leftover", "")):
                errors.append(f"{path.name}: FORM — {h} is not-probed, but not duplicated into mission_leftover")


def check_requirements_review(path: Path, errors: list) -> None:
    """Contract for requirements-review.md (epic workflow and mode U): the verdict and blocker
    count must be machine-readable; mode B must also carry the matrix fields."""
    fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    if fm is None:
        errors.append(f"{path.name}: no YAML frontmatter")
        return
    for field in REVIEW_REQUIRED:
        if field not in fm or fm[field] == "":
            errors.append(f"{path.name}: required field '{field}' is missing")
    mode = fm.get("mode", "")
    if mode and mode not in REVIEW_MODES:
        errors.append(f"{path.name}: mode '{mode}' outside {sorted(REVIEW_MODES)}")
    if fm.get("verdict") and fm["verdict"] not in REVIEW_VERDICTS:
        errors.append(f"{path.name}: verdict '{fm['verdict']}' outside {sorted(REVIEW_VERDICTS)}")
    if "decomposition" in mode:
        for field in REVIEW_DECOMPOSITION_REQUIRED:
            if field not in fm or fm[field] == "":
                errors.append(
                    f"{path.name}: mode B without '{field}' — the decomposition matrix is not "
                    "machine-readable without it (epic-workflow contract)"
                )


def check_report_coverage(path: Path, errors: list) -> None:
    """P3 "coverage line": the PTR must explicitly enumerate the check coverage —
    a missing section is read by a model/reviewer as "everything passed", which is
    the very problem this gate closes."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(PTR_COVERAGE_HEADING):
            start = i
            break
    if start is None:
        errors.append(
            f"{path.name}: PTR without a \"{PTR_COVERAGE_HEADING}\" section — a missing check "
            "reads as a passed one; enumerate ALL levels/channels with statuses "
            f"({'/'.join(PTR_STATUS_MARKERS)})"
        )
        return
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    section = lines[start + 1:end]
    has_status_row = any(
        line.strip().startswith("|") and any(marker in line for marker in PTR_STATUS_MARKERS)
        for line in section
    )
    if not has_status_row:
        errors.append(
            f"{path.name}: the \"{PTR_COVERAGE_HEADING}\" section is empty — not a single table "
            f"row with a status ({'/'.join(PTR_STATUS_MARKERS)}); enumerate ALL levels/channels"
        )
    check_ptr_readiness(path, lines, errors)


def check_test_report(path: Path, errors: list, notes: list | None = None) -> None:
    """Validate the public report against current machine-generated facts.

    `notes`, when given, collects the lines a caller prints beside a pass: a report that cannot be
    held to the code-owned blocks says so there ("legacy report: facts not checked") instead of
    passing in silence (FR-4)."""
    # The generated verification fragment left the report body for `work/delivery-summary.md`
    # (TP1-15045: it was inserted twice, and a counts table of rows-versus-instances is
    # not a decision a person makes). It is still validated byte for byte, where it lives.
    try:
        state_path = path.parent / 'state/controller.json'
        state = json.loads(state_path.read_text(encoding='utf-8-sig')) if state_path.exists() else {}
        if state.get('plan_contract_mode') == 'new':
            from delivery_summary import build, render
            summary = build(path.parent)
            fragment = path.parent / 'work' / 'delivery-summary.md'
            carrier = fragment.read_text(encoding='utf-8-sig') if fragment.exists() else ''
            if render(summary).strip() not in carrier:
                errors.append('STALE_REPORT_SUMMARY: regenerate work/delivery-summary.md '
                              '(delivery_summary.py --task-root <story>)')
    except (OSError, ValueError) as exc:
        errors.append('REPORT_SUMMARY_UNREADABLE: ' + str(exc))
    if is_legacy_report(path):
        check_report_coverage(path, errors)
        check_report_ledger_and_readiness(path, errors)
        check_legacy_report_sections(path, errors)
        if notes is not None:
            notes.append(G.LEGACY_FACTS_LINE)
        return
    check_report_ledger_and_readiness(path, errors)
    check_report_sections(path, errors)
    check_report_traceability(path, errors)
    check_report_left_with_you(path, errors)
    check_report_test_marks(path, errors)
    check_report_forbidden(path, errors)
    check_report_gate_b(path, errors)
    check_report_blocks(path, errors, notes)


LEGACY_REPORT_SECTIONS = ("## Verdict", "## Run this yourself", "## Product problems",
                          "## Check coverage", "## Readiness within what was verified",
                          "## Our tests and the factory")


def is_legacy_report(path: Path) -> bool:
    """A report written against the section list that stood before the rebuild.

    A story already in flight keeps its contract: it was written by a build that had no
    traceability appendix to paste, and refusing it now would make the factory's own version
    bump the person's problem."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "## Check coverage" in text and "## Appendix" not in text


def check_legacy_report_sections(path: Path, errors: list) -> None:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    seen = [ln for ln in lines if ln in LEGACY_REPORT_SECTIONS]
    for section in LEGACY_REPORT_SECTIONS:
        if section not in seen:
            errors.append(f"{path.name}: section '{section}' is missing - the gate-B message is "
                          "assembled from these sections in this order")
    ordered = [x for x in LEGACY_REPORT_SECTIONS if x in seen]
    if seen != ordered:
        errors.append(f"{path.name}: sections are out of order {seen} - expected {ordered}; "
                      "product problems come before anything about our own tests")


def _report_headings(text: str) -> list:
    """(prefix, whole line) for every `## ` heading this report carries, in file order."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        for section in G.REPORT_SECTIONS:
            if stripped.startswith(section):
                out.append((section, stripped))
                break
    return out


def _report_section_body(text: str, section: str) -> list:
    """The lines under one heading, up to the next `## `."""
    lines = text.splitlines()
    out, inside = [], False
    for line in lines:
        if line.strip().startswith("## "):
            inside = line.strip().startswith(section)
            continue
        if inside:
            out.append(line)
    return out


# The word of the report's `delivery_ready:` line (t-305 N8: three words, `after_checks` the third; `true`/`false` stay for
# a report that quotes an older ledger). A WHOLE word: `after_checksX`, `maybe` and `afterchecks` are not one.
READY_WORD_RE = re.compile(r"delivery_ready:\s*(yes|no|after_checks|true|false)\b", re.IGNORECASE)


def check_report_sections(path: Path, errors: list) -> None:
    """The order is the point: a reader who stops after the third section already has the
    verdict, what is proven and what is broken. What the factory owes itself sits below that
    line, and the traceability appendix closes the file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if is_legacy_report(path):
        # A caller that reaches this function directly (the S8/S9 tests do) gets the contract
        # the report in front of it was actually written against.
        check_legacy_report_sections(path, errors)
        return
    seen = [prefix for prefix, _ in _report_headings(text)]
    marked = G.has_markers(text)
    for section in G.REPORT_SECTIONS:
        if section in G.REPORT_SECTIONS_AFTER_GATE_B or section in seen:
            continue
        if section in G.REPORT_SECTIONS_WITH_BLOCKS and not marked:
            continue  # a report of the generation before the blocks is not owed the new sections
        errors.append(f"{path.name}: section '{section}' is missing - the report is assembled "
                      "from these sections in this order, and an absent one reads as nothing "
                      "to report")
    ordered = [x for x in G.REPORT_SECTIONS if x in seen]
    if seen != ordered:
        errors.append(f"{path.name}: sections are out of order {seen} - expected {ordered}; "
                      "what is proven and what is broken come before anything about ourselves")
    head = text.split("\n## ", 1)[0]
    if not READY_WORD_RE.search(head):
        errors.append(f"{path.name}: the verdict and its `delivery_ready:` line belong above "
                      "the first section - a person who reads one screen must have the answer")


def check_report_traceability(path: Path, errors: list) -> None:
    """Every register requirement and every case of the plan stands in the appendix.

    An absent row reads as a verified one. This is the same rule the old "Readiness within
    what was verified" table carried; what changed is that the table is generated, so the
    check is against a machine artifact instead of against prose."""
    text = path.read_text(encoding="utf-8", errors="replace")
    appendix = text.partition("## Appendix")[2]
    if not appendix.strip():
        return  # the missing-section error above already names it
    task = path.parent
    known = C.register_ids(C.artifact(task, "requirements-register.md"))
    missing = [r for r in known
               if not re.search(rf"(?<![\w-]){re.escape(r)}(?![\w-])", appendix)]
    if missing:
        errors.append(f"{path.name}: requirements {missing} are in the register and in no row "
                      "of the appendix - paste `traceability.py --render`, do not retype it")
    try:
        cases = C.case_index(task)
    except (OSError, ValueError):
        return
    absent = sorted(key for key in cases
                    if not re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", appendix))
    if absent:
        errors.append(f"{path.name}: cases {absent} are in the plan and in no row of the "
                      "appendix - run `traceability.py --check` before handing the report over")


def check_report_left_with_you(path: Path, errors: list) -> None:
    """Every item names its requirement and its case, says what a person would observe, and
    says how. On TP1-15045 "Run this yourself" mixed the regression commands with the
    tests that had been handed over, and no item said what answer was wanted."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # t-305 N8: the two code-owned blocks inside the section (what gate B's answers added, the plan's regression list) are
    # lines code renders from typed data and the S3 plan, not the scribe's items: the R-n / case / `To check:` rule is the
    # scribe's, and a scribe item without them is still refused below.
    items = _left_with_you_items(text)
    cfg = C.case_config(path)  # the report's own project decides what a case id looks like
    for index, item in enumerate(items, start=1):
        flat = " ".join(item.split())
        label = flat[:60]
        if not C.REQ_ID_RE.search(flat) or not C.case_ids(flat, cfg=cfg):
            errors.append(f"{path.name}: \"Left with you\" item {index} ({label}) names no "
                          "R-n and a case id - a person cannot look up an item that belongs to nothing")
        if not all(word in flat for word in G.REPORT_LEFT_WITH_YOU_REQUIRED):
            errors.append(f"{path.name}: \"Left with you\" item {index} ({label}) has no "
                          "\"To check:\" - say what would be observed, in words")
        if not any(word in flat for word in G.REPORT_LEFT_WITH_YOU_ONE_OF):
            errors.append(f"{path.name}: \"Left with you\" item {index} ({label}) has neither "
                          "\"Needed:\" nor \"How:\" - an item with no way to do it is a wish")


def _left_with_you_items(text: str) -> list:
    """The items of `## Left with you` the scribe wrote (a numbered or bulleted line and its continuation lines), the code-owned blocks
    inside the section taken out first."""
    # t-305 N8: the code-owned blocks inside the section (what gate B's answers added, the plan's regression list) are
    # lines code renders from typed data and the S3 plan, not the scribe's items: the R-n / case / `To check:` rule is the scribe's.
    found = G.blocks_found(text)
    cut = []
    for name in ("left-branches", "left-gate-b", "regression"):     # `left-branches`: step 3's lines name a branch, a part of the ticket or a picture, no case
        if name in found:
            begin = text.rfind(f"<!-- facts:{name} -->", 0, found[name][0])
            stop = text.find("\n", found[name][1])
            cut.append((begin, len(text) if stop < 0 else stop + 1))
    for begin, stop in sorted(cut, reverse=True):
        text = text[:begin] + text[stop:]
    body = _report_section_body(text, "## Left with you")
    items, current = [], ""
    for line in body:
        if re.match(r"^\s*(?:[-*]|\d+\.)\s+\S", line):
            if current:
                items.append(current)
            current = line
        elif current and line.strip():
            current += " " + line.strip()
    if current:
        items.append(current)
    return items


def _test_names(row: dict) -> set:
    """The spellings by which a report names the test of a ledger row: its ref (the instance id), the part after the last `::`, and each
    without a `[variant]` tail."""
    ref = str(row.get("ref") or "").strip()
    tail = ref.rsplit("::", 1)[-1]
    names = {ref, tail}
    names |= {re.sub(r"\[.*\]$", "", name) for name in list(names)}
    return {name for name in names if name}


def check_report_test_marks(path: Path, errors: list) -> None:
    """t-2277 W3 (owner 11.11.2026: "it must always be visible whether a result came from mocks or from real code"): the report held against
    the ledger's `real_or_mock` of each test. Two data joins, no wording judged (AR-29): (1) every test line under `## Proven` carries one of
    the marks `ledger.real_or_mock` writes (`ledger.REAL_OR_MOCK_MARKS`; a Proven line names a requirement and a case, not a test, so the join
    there is by presence); (2) every `## Left with you` item that names a test in backticks (`function[variant]`, the template's form) is
    joined to that test's ledger row by name and carries the row's words. A line without its mark is a report DEFECT named here with the test
    (FR-4: said, not silent); the door is the scribe's own edit of that line (FR-2: a regenerate cannot add a mark to a scribe's item). A ledger
    written before the field existed (no test row carries it) and a ledger that cannot be read are not checked (the legacy rule of the report's
    other generation checks)."""
    try:
        ledger_rows = json.loads(_sibling(path, "ledger.json").read_text(encoding="utf-8")).get("rows") or []
    except Exception:
        return
    tests = [r for r in ledger_rows if isinstance(r, dict) and r.get("kind") == "test" and not r.get("dead")]
    if not any("real_or_mock" in r for r in tests):
        return
    import ledger as L
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in _report_section_body(text, "## Proven"):
        if line.startswith("- ") and not any(mark in line for mark in L.REAL_OR_MOCK_MARKS):
            errors.append(f"{path.name}: a test line under \"Proven\" says neither `{L.REAL_CODE}` nor `{L.MOCK_LEAD}` ({line[:60].strip()}) - "
                          f"whether a result came from real code or from a mock must always be visible; "
                          f"`report_facts.py --task {path.parent.name} --write` renders the mark on that line")
    for index, item in enumerate(_left_with_you_items(text), start=1):
        flat = " ".join(item.split())
        for token in dict.fromkeys(re.findall(r"`([^`]+)`", flat)):
            for row in tests:
                words = " ".join(str(row.get("real_or_mock") or "").split())
                if words and token in _test_names(row) and words not in flat:
                    errors.append(f"{path.name}: \"Left with you\" item {index} names test `{token}` without its mark - the ledger says "
                                  f"`{words}`; copy `real_or_mock` of `{token}` from work/ledger.json into that item, word for word "
                                  "(your own edit of the line: a regenerate does not add it)")


def without_quoted_words(text: str) -> str:
    """The report text with the person's own quoted words taken out (t-305 N8 attempt 2, F7): the span of a line that starts
    with a `quoted_words` prefix of `references/human-text.json` `action_lines` is data, verbatim as recorded; the factory's
    writing around it is still judged. The same position rule `human_text` applies to its shape rows - one mechanism.
    A rules file that cannot be read exempts nothing: the whole text is judged, the stricter direction."""
    try:
        import human_text
        return human_text.without_quoted_words(text)
    except Exception:
        return text


# The SHAPES of the factory's own identifiers and markers (FR-6; X7-5): a content address `cv_<hex>`, a selector hash
# `ti_<hex>`, a path under `work/`, the generated fragment marker. A shape is data about an id, not a judgment of wording:
# `partial` or `utility_x` is not one. The phrase «look here first» is NOT here - whether a report leads with the verdict
# is the scribe's craft (charter: the task's terms first), judged by the tier above (AR-29). The whys are `G.REPORT_FORBIDDEN`'s.
REPORT_ID_SHAPES = (
    (re.compile(r"(?<![\w-])work/"), "work/"),
    (re.compile(r"(?<![\w-])cv_[0-9a-f]{4,}", re.IGNORECASE), "cv_"),
    (re.compile(r"(?<![\w-])ti_[0-9a-f]{4,}", re.IGNORECASE), "ti_"),
    (re.compile(r"<!-- factory-summary"), "<!-- factory-summary"),
)


def report_id_shape_hit(text: str) -> str:
    """The `G.REPORT_FORBIDDEN` key of the first factory identifier SHAPE found in `text`, "" when there is none. The one reader of
    `REPORT_ID_SHAPES` (AR-13): the validator below and `report_facts` (which keeps the report from refusing its own text) both ask it."""
    for shape, key in REPORT_ID_SHAPES:
        if shape.search(str(text or "")):
            return key
    return ""


def check_report_forbidden(path: Path, errors: list) -> None:
    """Identifiers and markers of ours that mean nothing to a person reading their own report: a shape, never a phrase."""
    text = path.read_text(encoding="utf-8", errors="replace")
    appendix_at = text.find("## Appendix")
    body = text[:appendix_at] if appendix_at >= 0 else text
    body = without_quoted_words(body)
    for shape, key in REPORT_ID_SHAPES:
        if shape.search(body):
            errors.append(f"{path.name}: the report carries {G.REPORT_FORBIDDEN[key]}")
    for match in G.REPORT_BARE_DECISION_RE.finditer(body):
        errors.append(f"{path.name}: `{match.group(0)}` stands with no decision text beside it "
                      "- quote the words the person said, the id alone says nothing")
        break


REPORT_HUMAN_HEADING = "## Factory defects"


def report_wording_rows() -> set:
    """The ids of the rows of `references/human-text.json` that judge a PHRASE about a tool run, not a factory id: a row with
    `report_refuses: false` is not refused in the report (X7-5, AR-29; AR-1: which row is data, not a tuple in code)."""
    import human_text
    return {str(row.get("id")) for row in human_text.rules().get("forbidden") or []
            if isinstance(row, dict) and row.get("report_refuses") is False}


def check_report_human_text(path: Path, errors: list) -> None:
    """The report's "Factory defects" section is text a person reads: it obeys
    `references/human-questions.md` (FR-6). TP1-13877 asked for factory-backlog ids and
    ledger states there, which the rules forbid; the template now asks for words.

    Called on write, beside `check_test_report` and never inside it: `traceability.py
    --close-gate-b` calls that one and exits 1 on its errors, and a report written before this
    check must not block a closure it has nothing to do with. Legacy reports are skipped; an
    empty or absent section has no human-text problem (the section list is the contract's)."""
    try:
        if is_legacy_report(path):
            return
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return  # an unreadable report is the other checks' finding, not this one's
    import human_text  # a missing rules file gives no rows: nothing to enforce, never a crash
    wording = report_wording_rows()
    for item in human_text.section_problems(text, REPORT_HUMAN_HEADING):
        if item.get("rule") in wording:
            continue   # a phrase about a tool run: the scribe's wording, not a factory id (X7-5, AR-29)
        errors.append(f"{path.name}, Factory defects: `{str(item['found']).strip('`')[:80]}` — {item['why']}. "
                      "Say what went wrong in words; the id or state stays in the ledger")


def check_report_gate_b(path: Path, errors: list) -> None:
    """The gate-B section is the person's own words, not a paraphrase of them.

    The 15045 report was written before the gate and still said the bugs "await your word"
    after the person had already said where they go."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if "## Decided at gate B" not in text:
        return
    pipeline = C.load_json(path.parent / "pipeline.json")
    section = " ".join(text.partition("## Decided at gate B")[2].split("\n## ")[0].split())
    words = " ".join(str((((pipeline.get("gates") or {}).get("B") or {})
                          .get("authorization_source") or "")).split())
    if words and words not in section:
        errors.append(f"{path.name}: \"Decided at gate B\" does not quote "
                      "gates.B.authorization_source verbatim - paste "
                      "`traceability.decided_at_gate_b(pipeline)`, do not restate it")
    for entry in C.live_stage_overrides(pipeline, ("S8", "S9")):      # the same live list the section is written from (GW1-1)
        decision = " ".join(str(entry.get("decision") or "").split())
        if decision and decision not in section:
            errors.append(f"{path.name}: the {entry.get('stage')} decision \"{decision[:50]}\" "
                          "is not in \"Decided at gate B\" - every word the person said at or "
                          "after the gate is in the report they get")


def report_is_unmarked(path: Path) -> bool:
    """True for a report with no code-owned block marker at all - written before the blocks existed.
    (Not `is_legacy_report`, which is the older contract of the section list: a report of the
    generation between the two, like TP1-13797's, has today's sections and no markers.)"""
    return not G.has_markers(path.read_text(encoding="utf-8", errors="replace"))


def gate_b_has_words(pipeline) -> bool:
    """Gate B recorded words of the person: `gates.B.authorization_source`, or a S8/S9 stage
    override's decision - the same sources `traceability.decided_at_gate_b` writes the section from."""
    if not isinstance(pipeline, dict):
        return False
    gate = (pipeline.get("gates") or {}).get("B") if isinstance(pipeline.get("gates"), dict) else None
    if isinstance(gate, dict) and " ".join(str(gate.get("authorization_source") or "").split()):
        return True
    return bool(C.live_stage_overrides(pipeline, ("S8", "S9")))      # a revoked word is not a decision (GW1-1)


def check_report_blocks(path: Path, errors: list, notes: list | None = None) -> None:
    """The code-owned blocks of the report (`grammar.REPORT_BLOCKS`): markers well formed, every block
    there, each opening with its own heading, and gate B's section holding only gate B's words.

    A report with no marker at all is read as before and says so (`notes`): nothing new is owed by
    a story written before the blocks, and the first `report_facts.py --write` converts it. A
    marker inside a code fence is not a marker, so a block whose closing marker sits in one is
    unterminated and named. Reads only (FR-45)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if is_legacy_report(path) or not G.has_markers(text):
        if notes is not None:
            notes.append(G.LEGACY_FACTS_LINE)
        return
    name = path.name
    door = G.REPORT_BLOCKS_DOOR.replace("<T>", path.parent.name)
    for problem in G.marker_problems(text):
        errors.append(f"{name}: {problem}")
    seen = G.blocks_seen(text)
    # the loop variable is `block_name`, not `block`: `block` is the hook's refusal function imported above
    for block_name in G.REPORT_BLOCKS:
        if block_name in seen or block_name in G.REPORT_BLOCKS_AFTER_GATE_B or block_name in G.REPORT_BLOCKS_WHEN_PRESENT:
            continue
        what = G.REPORT_BLOCK_HEADINGS.get(block_name) or "the verdict"
        errors.append(f"{name}: the code-owned block `{block_name}` ({what}) is missing - expected "
                      f"`<!-- facts:{block_name} -->` ... `<!-- /facts:{block_name} -->`; run `{door}` to render it")
    for block_name, (_start, _end, body) in G.blocks_found(text).items():
        expected = G.REPORT_BLOCK_HEADINGS.get(block_name, "")
        headings = G.heading_lines(body)
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        if not expected:
            if headings:
                errors.append(f"{name}: block `{block_name}` holds the section heading `{headings[0]}` - the verdict "
                              "stands above the first section; move the heading out of the block")
        elif expected.startswith("### "):
            # a block INSIDE a section (`left-gate-b`, `regression`, t-305 N8): it opens with its own `### ` line and holds
            # no `## ` section of its own - the section's heading is the scribe's, outside every block
            if not first.startswith(expected) or headings:
                errors.append(f"{name}: block `{block_name}` must open with its own heading line `{expected}` and hold "
                              f"no section heading (found {headings or 'none'}); run `{door}` to render it again")
        elif not first.startswith(expected) or len(headings) != 1:
            errors.append(f"{name}: block `{block_name}` must open with its own heading line `{expected}` and hold "
                          f"no other section (found {headings or 'no heading'}) - the heading carries the count "
                          f"code owns; run `{door}` to render it again")
    pipeline = C.load_json(path.parent / "pipeline.json")
    gates = pipeline.get("gates") if isinstance(pipeline, dict) else None
    gates = gates if isinstance(gates, dict) else {}

    def words(gate: str) -> str:
        record = gates.get(gate)
        return " ".join(str(record.get("authorization_source") or "").split()) if isinstance(record, dict) else ""

    if any(h.startswith("## Decided at gate B") for h in G.heading_lines(text)):
        section = " ".join("\n".join(_report_section_body(text, "## Decided at gate B")).split())
        if not gate_b_has_words(pipeline):
            errors.append(f"{name}: \"Decided at gate B\" stands in a report whose gate B has no recorded words - "
                          "the section exists only after the gate, and never holds another gate's content; "
                          f"leave it out until gate B is decided (`{door}` renders it only then)")
        elif words("A") and words("A") in section and words("A") not in words("B"):
            errors.append(f"{name}: \"Decided at gate B\" quotes gate A's words - under a gate's heading "
                          "stand only that gate's own recorded words; gate A's belong under \"Decided at gate A\"")


def check_pipeline(path: Path, errors: list) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"{path.name}: broken JSON ({e})")
        return
    for key in PIPELINE_KEYS:
        if key not in data:
            errors.append(f"{path.name}: required key '{key}' is missing (resume contract)")


def check_estimation_ledger(path: Path, errors: list) -> None:
    """Ledger of the P1 estimation loop (JSON Lines): every line is a separate
    forecast/actual measurement. The format is line-based (not one JSON array) — the writer
    appends a new line without re-reading and rewriting the whole file."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as e:
            errors.append(f"{path.name}: line {i}: broken JSON ({e})")
            continue
        if not isinstance(row, dict):
            errors.append(f"{path.name}: line {i}: the line is not a JSON object")
            continue
        for key in ESTIMATION_LEDGER_REQUIRED:
            if key not in row:
                errors.append(f"{path.name}: line {i}: required key '{key}' is missing")
        if "forecast" in row and not isinstance(row["forecast"], dict):
            errors.append(f"{path.name}: line {i}: 'forecast' must be an object")
        if "actual" in row and not isinstance(row["actual"], dict):
            errors.append(f"{path.name}: line {i}: 'actual' must be an object")
        if "drivers" in row and not isinstance(row["drivers"], list):
            errors.append(f"{path.name}: line {i}: 'drivers' must be a list")
        if "hit" in row and not isinstance(row["hit"], bool):
            errors.append(f"{path.name}: line {i}: 'hit' must be a bool")
        delta = row.get("delta")
        if isinstance(delta, dict):
            direction = delta.get("direction")
            if direction not in ESTIMATION_LEDGER_DIRECTIONS:
                errors.append(
                    f"{path.name}: line {i}: delta.direction '{direction}' outside "
                    f"{sorted(ESTIMATION_LEDGER_DIRECTIONS)} — an invented status is not accepted"
                )
        elif "delta" in row:
            errors.append(f"{path.name}: line {i}: 'delta' must be an object")


def check_run_report_empty(path: Path, data: dict, errors: list) -> None:
    """P2 "empty is not clean": a zero run with env_preflight: pass and without
    env_blocked/manual_checks/manual_skipped is indistinguishable from "we forgot to
    run it" — reject. A zero run with env_preflight: blocked is legitimate: the block
    itself explains where the emptiness came from."""
    totals = data.get("totals")
    if not isinstance(totals, dict):
        return
    def _n(key: str) -> float:
        v = totals.get(key, 0)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    total_sum = _n("passed") + _n("failed") + _n("skipped") + _n("passed_on_retry")
    if total_sum != 0:
        return
    if data.get("env_preflight") != "pass":
        return
    if data.get("env_blocked") or data.get("manual_checks") or data.get("manual_skipped"):
        return
    errors.append(
        f"{path.name}: an empty run with env_preflight=pass and without blocked/manual — "
        "\"we ran nothing\" does not mean \"clean\": return blocked with a reason or "
        "explain where the cases went"
    )


def check_run_report_head(path: Path, data: dict, errors: list) -> None:
    """P9 "evidence is bound to head": without a head a run-report cannot be tied to a
    concrete sha — runs are only comparable on one head, and without it the result goes
    stale instantly. head must be non-empty (a commit-info object or a string)."""
    head = data.get("head")
    valid = (isinstance(head, str) and head.strip() != "") or (isinstance(head, dict) and len(head) > 0)
    if not valid:
        errors.append(
            f"{path.name}: run-report without head: the evidence is not bound to a sha — "
            "runs are only comparable on one head; without it the result goes stale instantly"
        )


def check_nfr_report(path: Path, data: dict, errors: list) -> None:
    """Phase 8n: an NFR specialist report. What is checked is the walk over the finite list of norm
    items and the evidence, not the quality of judgment: the matrix is non-empty, statuses from the
    list, applicable items carry a result and evidence, a positive control exists (not-detected ->
    confidence low), not-measured without limitations is not accepted, findings carry a norm item and evidence.

    V1, DORMANT IN v0: the v0 artifact contract (references/artifact-contract.md) has no
    such file, so this rule can never fire in v0 — it is kept, tested by form_selftest.py,
    and waits for the v1 stage that writes the artifact. Audit A11 ignores it: A11 only
    governs PHASE_JSON_KEYS, the unconditional v0 schema table.
    """
    for key in G.NFR_REQUIRED:
        if key not in data:
            errors.append(f"{path.name}: required key '{key}' is missing (the Phase 8n contract)")
    ntype = data.get("type")
    if ntype not in G.NFR_TYPES:
        errors.append(f"{path.name}: type '{ntype}' outside {sorted(G.NFR_TYPES)}")
    if data.get("mode") not in G.NFR_MODES:
        errors.append(f"{path.name}: mode '{data.get('mode')}' outside {sorted(G.NFR_MODES)}")
    matrix = data.get("matrix")
    not_measured = 0
    if not isinstance(matrix, list) or not matrix:
        errors.append(f"{path.name}: matrix is empty — a report without a walk over the norm items is an opinion, not a check")
    else:
        for i, row in enumerate(matrix):
            if not isinstance(row, dict):
                errors.append(f"{path.name}: matrix[{i}] is not an object")
                continue
            if not str(row.get("clause", "")).strip():
                errors.append(f"{path.name}: matrix[{i}] without clause")
            status = row.get("status")
            if status not in G.NFR_MATRIX_STATUS:
                errors.append(f"{path.name}: matrix[{i}] status '{status}' outside {sorted(G.NFR_MATRIX_STATUS)}")
            if status == "n/a" and not str(row.get("n_a_reason", "")).strip():
                errors.append(f"{path.name}: matrix[{i}] n/a without n_a_reason — non-applicability is justified")
            if status == "applicable":
                result = row.get("result")
                if result not in G.NFR_RESULTS:
                    errors.append(f"{path.name}: matrix[{i}] result '{result}' outside {sorted(G.NFR_RESULTS)}")
                elif result == "not-measured":
                    not_measured += 1
                elif not str(row.get("evidence", "")).strip():
                    errors.append(f"{path.name}: matrix[{i}] '{result}' without evidence — there is no \"meets\" without proof")
    pc = data.get("positive_control")
    if not isinstance(pc, dict) or pc.get("result") not in G.NFR_CONTROL_RESULTS or not str(pc.get("what", "")).strip():
        errors.append(f"{path.name}: positive_control must carry what and result in {sorted(G.NFR_CONTROL_RESULTS)} — a tool not checked against a known violation proves nothing")
    elif pc.get("result") == "not-detected" and data.get("confidence") != "low":
        errors.append(f"{path.name}: positive_control not-detected with confidence '{data.get('confidence')}' — low is required")
    for i, f in enumerate(data.get("findings") or []):
        if not isinstance(f, dict) or not str(f.get("clause", "")).strip() or not str(f.get("evidence", "")).strip():
            errors.append(f"{path.name}: findings[{i}] without clause or evidence")
        elif f.get("impact") and f["impact"] not in G.impact_scale(G.load_overrides(CFG_PATH)):
            errors.append(f"{path.name}: findings[{i}] impact '{f['impact']}' outside the scale")
    for i, v in enumerate(data.get("verdict") or []):
        if not isinstance(v, dict) or v.get("result") not in G.NFR_RESULTS:
            errors.append(f"{path.name}: verdict[{i}] result outside {sorted(G.NFR_RESULTS)}")
    lim = data.get("limitations")
    if not_measured and not (isinstance(lim, list) and any(str(x).strip() for x in lim)):
        errors.append(f"{path.name}: {not_measured} not-measured items without limitations — \"we did not measure\" is explained, not left silent")
    if data.get("confidence") not in ("high", "low"):
        errors.append(f"{path.name}: confidence outside high|low")
    if not str(data.get("witness", "")).strip():
        errors.append(f"{path.name}: empty witness")


def check_phase_json(path: Path, errors: list, notes: list | None = None) -> None:
    required = PHASE_JSON_KEYS.get(path.name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"{path.name}: broken JSON ({e})")
        return
    if re.match(r"^nfr-[a-z]+\.json$", path.name) and isinstance(data, dict):
        check_nfr_report(path, data, errors)
        return
    if required:
        if path.name == "automation-manifest.json" and isinstance(data, dict):
            # a manifest with no run to witness (every test handed, or every test pending its absent side) owes no `run_witness` -
            # `acceptance.run_witness_excused`, the ONE reader the other two witness readers ask as well (t-2181 PC-4, B3)
            import acceptance
            if acceptance.run_witness_excused(data):
                required = [k for k in required if k != "run_witness"]
        for key in required:
            if key not in data:
                errors.append(f"{path.name}: required key '{key}' is missing")
    if path.name == "run-report.json" and isinstance(data, dict):
        check_run_report_empty(path, data, errors)
        check_run_report_head(path, data, errors)
        check_run_report_coverage(path, data, errors, notes)
        check_remedy_rows(path, data.get("env_blocked") or [], "env_blocked[]", errors)


# =============================================================================================
# C0 — the v0 artifact contract (references/artifact-contract.md). Everything below reads the
# closed vocabularies from contract.py and the regex lists from references/detectors.json; no
# vocabulary is spelled out twice. Each message is at most two lines and names the file, the
# rule it broke and the fix — a reject the role cannot act on is noise.
# =============================================================================================

import assertion_detectors as AD  # noqa: E402  (the ONE reader of detectors.json's assert lines, B-407 C)
import contract as C  # noqa: E402
import test_files as TF  # noqa: E402  (the ONE "is this a test file" leaf, B-407 A)
from hooklib import REQUIRED_SCHEMA_VERSION, load_config, load_ref_json, project_root  # noqa: E402

UNDERSTANDING_MAX_LINES = 40
TEST_REPORT_MAX_BYTES = 6144

UNDERSTANDING_SECTIONS = ("## Why this change", "## What we verify", "## What we do not verify",
                       "## What else the change may touch", "## Questions without which")
# A stage id as a whole token, in any wording or language (FR-12: the trigger is the presence of the id, never a
# phrase about being finished). `S10` and `AS8` are not stage ids.
STAGE_ID_RE = re.compile(r"(?<![A-Za-z0-9_])S[0-9](?![A-Za-z0-9_])")
# Stage statuses `stage_notes` names: a stage that has not started (or stopped) cannot have been finished. A
# `running` stage is where the report is being written (S8), and a `done` one is nobody's lie.
STAGE_NOTED_STATUSES = ("pending", "halted")
RED_LOCK_TOKEN = "red_lock"
# Built-in copies of the shipped rows of `detectors.json`, the way `AD.ASSERT_LINE_FLOOR` is for `assert_lines`: a key that
# is dropped, unreadable or malformed means THESE rows and one ORACLE_NOTES line naming the key - never "no check"
# (FR-4, FR-41, FR-59). `test_broad_status.py` K-floor holds each tuple equal to the shipped data. After X7-2 only the plan
# check reads a row: the test-code rows (retry, broad status, skip) were read by `check_test_code`, which is cut.
DETECTOR_FLOORS = {
    "plan_antipatterns": (r"(?i)\bis\s+visible\b", r"(?i)\bvisibility\s+of\b", r"(?i)\belement\s+(is\s+)?displayed\b",
                          r"(?i)\bpage\s+title\b", r"(?i)\btitle\s+is\s+correct\b", r"(?i)\burl\s+after\s+navigat",
                          r"(?i)\bredirects?\s+to\s+url\b", r"(?i)\bfirst\s+(available\s+)?record\b",
                          r"(?i)\bfirst\s+(available\s+)?(entity|item|row)\s+exists\b"),
}


def detector_rows(path: Path, key: str) -> list:
    """The compiled regexes of one `detectors.json` key, through `assertion_detectors.shape_patterns` (the one reader).

    These checks may only OVER-refuse: a key that is absent, not a list, empty or holding a pattern that does not
    compile leaves `DETECTOR_FLOORS[key]` and ONE ORACLE_NOTES line naming the key - never "no check" (the data's gap
    is the factory's, not the role's: the write is not blocked for it)."""
    try:
        patterns = AD.shape_patterns(key)
    except AD.DetectorsError as exc:
        patterns = list(DETECTOR_FLOORS[key])
        note = f"{path.name}: {str(exc)[:200]} - the check used its built-in floor for `{key}`"
        if note not in ORACLE_NOTES:
            ORACLE_NOTES.append(note)
    return [re.compile(p) for p in patterns]


def _sibling(path: Path, name: str) -> Path:
    """Another artifact of the same story. `path` may itself be inside `work/`, so resolve
    against the story folder, and let `C.artifact` find the name in either place."""
    return C.artifact(_story_root(path), name)


def _pipeline_stages(path: Path) -> dict:
    source = _sibling(path, "pipeline.json")
    try:
        data = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
    except (OSError, ValueError):
        return {}   # an unreadable pipeline.json is its own file's refusal; a note about a report waits for it
    stages = data.get("stages") if isinstance(data, dict) else {}
    return stages if isinstance(stages, dict) else {}


def stage_notes(path: Path, text: str) -> list:
    """One line per stage id the report names while pipeline.json has that stage `pending` or `halted`.

    A report that calls a stage finished while it has not started is a lie a person cannot catch by reading, and
    what a sentence MEANS is the author's to judge, not a phrase list's (FR-12, F-8): this reads only the presence
    of the id, in any wording or language, and says so. It is a note, never an error - the verdict a person reads
    (`delivery_ready:`) stays refused on contradiction (check_report_ledger_and_readiness). INVARIANT: a `running`
    or `done` stage is never named, so the normal report written during S8 gets no note; a stage that pipeline.json
    does not hold is not named either."""
    stages = _pipeline_stages(path)
    notes = []
    for stage in dict.fromkeys(STAGE_ID_RE.findall(text)):
        row = stages.get(stage)
        status = row.get("status") if isinstance(row, dict) else None
        if status in STAGE_NOTED_STATUSES:
            notes.append(f"{path.name} names {stage} while pipeline.json has it '{status}': if a sentence calls "
                         "it finished, correct it; whether it does is yours to judge.")
    return notes


def collect_notes(path: Path) -> list:
    """What a valid write of the report is told beside its pass: printed by `--check --verbose` and by the
    valid-write hint block, never an error (FR-4: said, not silent). Fail-open: a note is no reason to refuse."""
    target = norm(str(path))
    if "/qa-factory/artifacts/" not in target or not target.endswith("test-report.md"):
        return []
    try:
        return stage_notes(path, without_quoted_words(_authored_text(path.read_text(encoding="utf-8", errors="replace"))))
    except Exception:
        return []


# --- test-plan.md (v0 contract) ----------------------------------------------------------------

def check_plan_v0(path: Path, errors: list) -> None:
    rows = C.parse_plan(path)
    if not rows:
        errors.append(f"{path.name}: the '## Plan' table has no TS-n rows — a plan with no rows is "
                      "not a plan; add one row per check")
        return
    antipatterns = detector_rows(path, "plan_antipatterns")
    classes = G.defect_classes(G.load_overrides(CFG_PATH))
    # t-227 C12 (P20): an `oracle` may not name a requirement the register derives from the diff
    # alone. Dated by the plan's own `created` (ORACLE_CUTOFF): an older plan is never refused.
    impl_only: set = set()
    plan_fm = parse_frontmatter(C.read_text(path)) or {}
    check_cell_counts(path, C.read_text(path), C.PLAN_HEADING, "plan", errors)
    register = _sibling(path, "requirements-register.md")
    if register.exists() and _oracle_dated(plan_fm, "created", path.name, errors):
        impl_only = C.unconfirmed_requirements(C.read_text(register), _question_rows(_story_root(register)))
    seen = set()
    for row in rows:
        ts = row["ts"]
        if ts in seen:
            errors.append(f"{path.name}: {ts} appears twice — one row, one TS id")
        seen.add(ts)
        if not row.get("requirements"):
            errors.append(f"{path.name}: {ts}: the R column names no register requirement — "
                          "every row traces to at least one R-n")
        # The v0 plan carried no check on its own defect class, so `regression @ <place>` — a
        # class the closed list only has as `regression:BUG-NNN` — passed S3 untouched and the
        # case designer inherited it (TP1-15045). Every case inherits this cell verbatim,
        # which makes it the earliest place the vocabulary can be held.
        hypothesis = str(row.get("hypothesis") or "").strip()
        if hypothesis and hypothesis != G.SMOKE:
            m = G.DEFECT_CLASS_RE.match(hypothesis)
            door = m.group("new") if m else None
            cls = (m.group("cls") or "") if m else ""
            if door is not None:
                # `new:<word> -- <why> @ <place>`: the form is code's, the word is the stage critic's (F-3 (b))
                errors.extend(f"{path.name}: {ts}: defect hypothesis {problem}"
                              for problem in C.open_word_errors(door, sorted(classes), "defect_class"))
            elif not m or (cls not in classes and not cls.startswith("regression:")):
                errors.append(
                    f"{path.name}: {ts}: defect hypothesis '{hypothesis}' — needs `<class> @ <place>` "
                    f"with a class from {sorted(classes)} | regression:BUG-NNN, or `smoke`, or a new class as "
                    "`new: <word> -- <why> @ <place>`. Every "
                    "case of this row inherits the class verbatim.")
        disposition = row.get("disposition", "")
        if disposition not in C.DISPOSITIONS:
            errors.append(f"{path.name}: {ts}: disposition '{disposition}' outside "
                          f"{list(C.DISPOSITIONS)} — use one of them")
        elif not row.get("reason"):
            errors.append(f"{path.name}: {ts}: disposition `{disposition}` with no reason — "
                          "write it as `disposition` - <one clause saying why>")
        if not row.get("observable_source"):
            errors.append(f"{path.name}: {ts}: the observable '{row.get('observable', '')}' names no "
                          f"source — prefix it with one of {list(C.OBSERVABLE_SOURCES)}")
        oracle = row.get("oracle", "")
        if oracle and not any(oracle.startswith(p) for p in C.ORACLE_PREFIXES):
            errors.append(f"{path.name}: {ts}: oracle '{oracle}' is not from "
                          f"{list(C.ORACLE_PREFIXES)} — name what makes the expected value expected")
        named = C.requirement_id(oracle)
        if named and named in impl_only:
            errors.append(f"{path.name}: {ts}: oracle '{oracle}' names {named}, which is implementation-only "
                          "(derived from the diff alone): a requirement read from the code is not an oracle. Leave "
                          "`oracle` empty for this row, or name `external:<ref>`; its Thens carry their own oracle "
                          "(`unknown` until the person answers the claim's question)")
        level =str(row.get("level") or "").strip().lower()
        if level and level not in C.PLAN_LEVELS:
            errors.append(f"{path.name}: {ts}: level '{level}' outside {list(C.PLAN_LEVELS)} — "
                          "the board groups the pyramid by this word, so an invented one is a "
                          "check that lands in no level at all")
        elif not level and disposition == "automate":
            errors.append(f"{path.name}: {ts}: `automate` with no level — name one of "
                          f"{list(C.PLAN_LEVELS)}. Without it the test reaches the board with no "
                          "place in the pyramid, and the board cannot invent one.")
        if disposition == "automate":
            for pattern in antipatterns:
                hit = pattern.search(row["line"])
                if hit:
                    errors.append(f"{path.name}: {ts}: `automate` on a low-value row "
                                  f"(matched '{hit.group(0)}') — visibility/title/URL/first-record is "
                                  "smoke at most; check the behaviour through an independent channel")
                    break
        new_behaviour = row.get("fit") == "new" or "pending_implementation" in row["line"]
        if new_behaviour:
            if oracle.startswith("history:"):
                errors.append(f"{path.name}: {ts}: new behaviour with oracle `history:` — the expected "
                              "value comes from the requirement or an external spec, never from the past")
            if row.get("observable_source") == "current-code":
                errors.append(f"{path.name}: {ts}: new behaviour observed on `current-code` — current "
                              "code is not the oracle for new behaviour; use expected-contract or the diff")


# --- understanding.md / test-report.md ---------------------------------------------------

def check_understanding(path: Path, errors: list) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > UNDERSTANDING_MAX_LINES:
        errors.append(f"{path.name}: {len(lines)} lines > {UNDERSTANDING_MAX_LINES} — the scope card is "
                      "one screen; move detail into requirements-register.md")
    for section in UNDERSTANDING_SECTIONS:
        if not any(ln.strip().startswith(section) for ln in lines):
            errors.append(f"{path.name}: section '{section}' is missing — the gate-A message is "
                          "assembled from these sections in order")
    known = C.register_ids(_sibling(path, "requirements-register.md"))
    if not known:
        return
    body = text
    for heading in ("## What else the change may touch", "## Questions without which"):
        idx = body.find(heading)
        if idx >= 0:
            body = body[:idx]
    covered = set(C.REQ_ID_RE.findall(body))
    orphan = [r for r in known if r not in covered]
    if orphan:
        errors.append(f"{path.name}: {orphan} appear in no 'What we verify' / 'What we do not verify' "
                      "line — an unlisted requirement reads as covered; list it or say why not")


def _authored_text(text: str) -> str:
    """The report minus its code-owned parts: what the scribe wrote.

    Text inside `facts` blocks is code-owned (t-189 fork 3): it scales with the story and is
    checked against a fresh render, so it is not the scribe's prose. Cut from the end so the
    offsets stay true; a report with no marker has no block and loses nothing. The traceability
    appendix is machine text like the ledger table was: it grows with the plan and it is
    validated elsewhere, so it is not part of the author's prose budget."""
    counted = text
    for start, end, _body in sorted(G.blocks_found(text).values(), reverse=True):
        counted = counted[:start] + counted[end:]
    authored = re.sub(r"<!-- factory-summary:start -->.*?<!-- factory-summary:end -->", "",
                      counted, flags=re.DOTALL)
    appendix_at = authored.find("## Appendix")
    return authored[:appendix_at] if appendix_at >= 0 else authored


def check_report_ledger_and_readiness(path: Path, errors: list) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    # The cap is on the hand-written part: the checks ledger table is generated by
    # ledger.py and grows with the plan, so its table lines are not counted. The old
    # 2 KB was written for a separate two-page brief; this file is the whole report now.
    # The pilot overran that number twofold with nothing noticing — a limit that everyone
    # quietly steps over is worse than no limit, so this one is real and enforced.
    # Deterministic machine sections scale with evidence and are validated byte-for-byte;
    # they are not part of the author's prose budget.
    authored = _authored_text(text)
    hand = "\n".join(ln for ln in authored.splitlines() if not ln.startswith("|")).encode("utf-8")
    if len(hand) > TEST_REPORT_MAX_BYTES:
        errors.append(f"{path.name}: {len(hand)} bytes outside the generated tables > {TEST_REPORT_MAX_BYTES} — "
                      "the report is what a person reads to decide; detail that does not fit belongs "
                      "in the artifact it came from, cited by path")
    ledger_md = _sibling(path, "ledger.md")
    if ledger_md.exists() and is_legacy_report(path):
        # The ledger stopped being shown to the person at all (it is a machine input under
        # `work/`); a report written before that still owes its verbatim copy.
        table = [ln for ln in ledger_md.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.startswith("|")]
        if table and "\n".join(table) not in text:
            errors.append(f"{path.name}: section 1 is not the table ledger.py generated — paste "
                          "ledger.md's table verbatim; a hand-written ledger is not a ledger")
    ledger_json = _sibling(path, "ledger.json")
    if ledger_json.exists():
        import delivery_verdict as DV
        try:
            word = DV.word_of(json.loads(ledger_json.read_text(encoding="utf-8")))
        except Exception:
            word = None
        if word not in (None, DV.UNKNOWN):
            claimed = READY_WORD_RE.search(text)
            if not claimed:
                errors.append(f"{path.name}: no 'delivery_ready: yes|after_checks|no' line — it is not optional: "
                              "`report_facts.py --task <TICKET> --write` renders it in the verdict block "
                              "(a report with no code-owned blocks quotes check_delivery.py verbatim)")
            else:
                said = claimed.group(1).lower()
                # `true`/`false` are the spelling of a ledger that had a bool and no word: they mean yes / no
                said = {"true": "yes", "false": "no"}.get(said, said)
                # t-305 N8 (Q-N8-7): a MARKED report is held to the ledger's word too. It used to be exempt ("the
                # ledger is only one of the verdict block's inputs"), because the block could say `no` over a ready
                # ledger from its own facts; now the head IS the ledger's word (`report_facts._verdict`, D9) and
                # `rebuild_report` re-renders it at S8 and S9 before any validate, so a head that differs is stale.
                if said != word:
                    errors.append(f"{path.name}: says delivery_ready {claimed.group(1)} while ledger.json says "
                                  f"{word} — quote check_delivery.py, do not restate it "
                                  "(`report_facts.py --task <TICKET> --write` renders the head from the ledger)")


# --- automation-manifest.json / run-report.json / triage.json ---------------------------------------

def check_marker_in_file(path: Path, file_rel: str, marker: str, case: str, errors: list) -> None:
    """The traceability marker is checked where it has to exist — in the test file.

    The manifest field was checked; the file was not, so a `marker: "TC-001"` beside a test
    carrying no such comment passed every gate until a human read the code. On
    TP2-2386 the code critic found five of them AFTER the tests had been written and
    run, and the fix went round the automation loop again for a change that touched no
    executable line. This is the cheapest possible moment to catch it: the automator is
    still in its own dispatch, the run has cost nothing yet, and the repair is a comment.
    A file that cannot be read is not a finding here — the existence check above owns that."""
    for candidate in (project_root() / file_rel, Path(file_rel)):
        try:
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        if marker in text:
            return
        errors.append(
            f"{path.name}: {case or file_rel} declares marker `{marker}`, but {file_rel} does "
            "not contain it — the traceability marker belongs in the test code, not only in "
            "this manifest. Add it to the test (a comment or the framework's case decorator) "
            "and rewrite the entry; a marker only the manifest knows traces nothing.")
        return


def _s6_runner_half(path: Path) -> tuple:
    """(`execution_kind`, `manual_case_ids`) of the ONE running S6 qa-runner dispatch, from the
    controller's own record (`state/controller.json`, the file `exit_gate.dispatch_scope` reads);
    ("", []) when it cannot be said. ERROR DIRECTION (a doubt never skips a refusal): no state file,
    an unreadable one, no running S6 runner dispatch, two of them, or a dispatch that carries no
    `execution_kind` (a story that predates the field) all answer ("", []) - and that means the check
    refuses exactly as it always did."""
    art_dir = _story_root(path)
    try:
        state = json.loads((art_dir / "state" / "controller.json").read_text(encoding="utf-8"))
    except Exception:
        return "", []
    raw = state.get("dispatches") if isinstance(state, dict) else None
    # AR-13: the one reader. A session that works for a named dispatch gets ITS record even beside another running lane
    # (parallel S6 lanes, TR3-9 C2); no name is the count rule (one running runner), two running and no name is None.
    import dispatch_identity
    live = dispatch_identity.own(raw, role="qa-runner", stage="S6", name=dispatch_identity.named())
    if live is None:
        return "", []
    block = live.get("manual_case_ids")
    return (str(live.get("execution_kind") or ""),
            [str(c) for c in block if str(c).strip()] if isinstance(block, list) else [])


def check_run_report_coverage(path: Path, data: dict, errors: list, notes: list | None = None) -> None:
    """Every case S5 automated, and every manual-agent row of the plan, is accounted for.

    The report's KEYS were checked and its emptiness was checked; its completeness was not,
    so a report missing half its cases was a valid artifact and the hole surfaced two stages
    later in check_traceability — by which time the runner's dispatch was closed and the fix
    cost a corrective re-dispatch (TP2-2386). Accounted for means named somewhere: a
    result, a manual check, `skipped`, `impossible`, `env_blocked`, `manual_skipped` or
    `manual_human`. Where the case went is the runner's call; saying nothing is not.

    S6 runs in two halves (t-290): the automation runner first, the manual block(s) after it, and
    `manual_checks` is empty until the second half runs - a refusal for every manual-agent row at
    the end of the FIRST half cannot be satisfied by anyone. So while the dispatch being accepted is
    the S6 runner's `execution_kind: automation`, a `manual-agent` row with no lane is one NOTE line
    (`notes`, else ORACLE_NOTES), not an error (FR-4: said, not silent). INVARIANT the skip keeps
    unreachable: an AUTOMATED case with no lane still refuses in that half, and every row refuses
    at any close (no running dispatch, no kind: today's behaviour).

    The manual half goes block by block, and the refused cases' code-only record is written only after
    the LAST block (`manual_close`), so a block's handoff cannot be asked for the rows of the others.
    For the running `execution_kind: manual` dispatch the rows whose case is NOT in its
    `manual_case_ids` and has no lane are the same kind of note ("wait for a later block or the
    close"); a case IN `manual_case_ids` keeps the refusal - the block delivers its own. A manual
    dispatch that names no cases cannot be scoped, so it refuses everything (error direction)."""
    manifest = C.load_json(_sibling(path, "automation-manifest.json"))
    plan_rows = C.parse_plan(_sibling(path, "test-plan.md"))
    cases = C.case_index(path.parent)

    required = {}
    manual_row = {}     # case id -> the plan row (TS-n) that makes it a manual-agent case
    for test in C.manifest_tests(manifest):
        for cid in C.case_ids(test.get("case")) or [str(test.get("case") or "")]:
            if cid:
                required[cid] = "automated at S5"
    for row in plan_rows:
        if row.get("disposition") != "manual-agent":
            continue
        for cid, meta in cases.items():
            if meta.get("plan_row") == row["ts"]:
                if cid not in required:
                    manual_row[cid] = row["ts"]
                required.setdefault(cid, f"`manual-agent` in the plan ({row['ts']})")
    if not required:
        return
    half, block = _s6_runner_half(path)
    waiting_half = half == "automation"
    manual_block = half == "manual" and bool(block)
    waiting = set()

    accounted = set(C.run_results(data)) | set(C.run_impossible(data)) | set(C.manual_human_evidence(data))
    for key in ("skipped", "manual_skipped", "env_blocked"):
        for row in data.get(key) or []:
            if isinstance(row, dict):
                accounted |= {cid for cid in C.case_ids(row.get("case")) or [str(row.get("case") or "")] if cid}
            elif isinstance(row, str):
                accounted |= set(C.case_ids(row))

    for cid, why in sorted(required.items()):
        # D2-B3: by the identity lookup, an area-keyed result (`api/TC-4`) accounts for the bare required id
        if not C.names_case(accounted, cid):
            if cid in manual_row and (waiting_half or (manual_block and cid not in block)):
                waiting.add(manual_row[cid])
                continue
            errors.append(
                f"{path.name}: {cid} is {why} but appears in no lane of this report — not in "
                "results[], manual_checks[], skipped[], impossible[], env_blocked[] or "
                "manual_skipped[]. A case left out reads as untested; say where it went. An unprepared case is closed by "
                "`manual_evidence.py unprepared` (walked or not).")
    if waiting:
        rows = sorted(waiting, key=lambda ts: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", ts)])
        (ORACLE_NOTES if notes is None else notes).append(
            f"{path.name}: {len(rows)} manual-agent rows wait for "
            f"{'the manual half' if waiting_half else 'a later block or the close'}: {', '.join(rows)}")


def check_manifest_v0(path: Path, data: dict, errors: list) -> None:
    plan_rows = C.parse_plan(_sibling(path, "test-plan.md"))
    cases = C.case_index(path.parent)
    tested = {str(t.get("case")) for t in C.manifest_tests(data)}
    unresolved = {str(u.get("case")): str(u.get("reason") or "") for u in C.manifest_unresolved(data)}

    for case, reason in unresolved.items():
        if not C.unresolved_reason_ok(reason):
            errors.append(f"{path.name}: {case} unresolved with reason '{reason}' — use one of "
                          f"{list(C.UNRESOLVED_REASONS)} or deferred_by_decision:<gate>")
    for test in C.manifest_tests(data):
        who = str(test.get("case") or test.get("file") or "test")
        file_rel = str(test.get("file") or "")
        if file_rel and not (project_root() / file_rel).exists() and not Path(file_rel).exists():
            errors.append(f"{path.name}: tests[] names {file_rel}, which does not exist — the manifest "
                          "points at code that was written, not code that was planned")
        marker = str(test.get("marker") or "")
        binding = test.get("trace_binding")
        if binding is not None:
            candidates = [project_root() / file_rel, Path(file_rel)]
            actual = next((p for p in candidates if p.is_file()), None)
            if (not isinstance(binding, dict) or not binding.get("selector") or not binding.get("assertion_refs")
                    or not test.get("case_version_links") or actual is None
                    or __import__("hashlib").sha256(actual.read_bytes()).hexdigest() != binding.get("test_content_sha")):
                errors.append(f"{path.name}: invalid content-bound test trace; selector, assertions, pins and actual file hash required")
        elif not marker:
            errors.append(f"{path.name}: {test.get('case') or file_rel} has no `marker` (its case id) or content-bound trace_binding")
        else:
            check_marker_in_file(path, file_rel, marker, str(test.get("case") or ""), errors)
        verdict = str(test.get("critic_verdict") or "")
        if verdict and verdict not in C.CRITIC_VERDICTS:
            errors.append(f"{path.name}: {who}: critic_verdict '{verdict}' outside "
                          f"{list(C.CRITIC_VERDICTS)}")
        notes = [str(n).strip() for n in (test.get("fix_notes") or []) if str(n).strip()]
        if verdict == "approved_with_fixes" and not notes:
            errors.append(f"{path.name}: {who}: approved_with_fixes with no fix_notes[] — the "
                          "verdict exists to carry the findings that do not need a second "
                          "review round; without them it is just `approved`")
        if notes and verdict not in ("approved_with_fixes", ""):
            errors.append(f"{path.name}: {who}: fix_notes[] beside verdict '{verdict}' — notes "
                          "belong to approved_with_fixes; a rejected test's findings go in the "
                          "critic's report, and an approved one has none")
    for row in plan_rows:
        if row.get("disposition") != "automate":
            continue
        for cid, meta in cases.items():
            if meta.get("plan_row") != row["ts"]:
                continue
            # A keyed index (`<area>/TC-NNN`) against bare manifest rows: either spelling
            # names the case, so neither may read as "disappeared".
            matches = getattr(C, "case_matches", None)
            covered = (any(matches(key, cid) for key in (*tested, *unresolved)) if matches
                       else (cid in tested or cid in unresolved))
            if not covered:
                errors.append(f"{path.name}: `automate` case {cid} ({row['ts']}) is in neither tests[] "
                              "nor unresolved[] — a case that just disappeared reads as covered")
    check_self_fixes(path, data, errors)
    check_manifest_invariants(path, data, errors)


def check_manifest_invariants(path: Path, data: dict, errors: list) -> None:
    """What `manifest_put.py` guarantees, re-checked on the file as it lies on disk.

    TP1-15045: the automator edited `automation-manifest.json` by hand — because
    identity was a hash of the mutable selector string, splitting one parametrized test
    into per-partition instances ADDED rows instead of replacing them. A hand edit can
    break an invariant the merge cannot: a case in both lists, two rows with one instance
    id, the same repair recorded twice. Naming the command is the whole point of the
    message: the repair is to re-send the fragment, not to edit the file again."""
    seen: dict = {}
    for entry in C.manifest_tests(data):
        iid = C.test_instance_id(entry)
        if iid and iid in seen:
            errors.append(f"{path.name}: two tests[] entries carry the instance id {iid!r} — "
                          "one row per test. Rewrite the fragment with one entry per test "
                          "function/parameter and re-run `manifest_put.py --task <TICKET> "
                          "--fragment <file>`; this file is not edited by hand")
        seen[iid] = entry
    tested = {str(t.get("case") or "") for t in C.manifest_tests(data)
              if str(t.get("status") or "") == "green"}
    for row in C.manifest_unresolved(data):
        case = str(row.get("case") or "")
        scoped = row.get("partition") or row.get("partitions") or row.get("instance_id")
        if case and case in tested and not scoped:
            errors.append(f"{path.name}: {case} is green in tests[] and present in unresolved[] "
                          "— the two lists disagree about whether it ran. `manifest_put.py` "
                          "drops the stale copy when the decision arrives as a fragment; if the "
                          "remainder is a partition, name it in `partitions: [...]`")
    keys = set()
    for i, fix in enumerate(data.get("self_fixes") or []):
        token = json.dumps(fix, ensure_ascii=False, sort_keys=True, default=str)
        if token in keys:
            errors.append(f"{path.name}: self_fixes[{i}] is byte-identical to an earlier entry — "
                          "one repair, recorded twice, reads as two. Re-send the fragment through "
                          "`manifest_put.py`, which drops an identical repeat")
        keys.add(token)
    check_remedy_rows(path, C.manifest_unresolved(data), "unresolved[]", errors)


def check_remedy_rows(path: Path, rows, label: str, errors: list) -> None:
    """A row that says the environment blocks a case says what would unblock it — `remedy`.

    TP1-15045: the automator had found the exact cause (`customer-config.yaml:304-311`,
    `enabled: false`) and the manifest carried only prose, so the person was handed a state,
    not a fix. The rule keeps THE LAW OF EDITING THIS FILE the way `preconditions` does: the
    field itself is the cutoff. A file in which no row carries a `remedy` was written before
    the field existed and is validated exactly as it always was; the moment one row carries
    one, the file is this version's and every blocking row in it owes the same.

    Whatever the age of the file: a `remedy` that IS there must be one, and neither it nor the
    prose beside it may print the value of a credential. Names only."""
    rows = [row for row in rows if isinstance(row, dict)]
    this_version = any(row.get("remedy") is not None for row in rows)
    for row in rows:
        who = str(row.get("case") or row.get("instance_id") or row.get("area") or "a row")
        reason = str(row.get("reason") or "")
        # An `env_blocked[]` row of a run report carries no reason: being in that list is the
        # reason. In the manifest only `blocked_by_env` owes a fix — `handed_to_person` keeps
        # the remedy it was given at a gate, and the other reasons are not about the stand.
        blocking = reason == "blocked_by_env" or (not reason and label != "unresolved[]")
        remedy = row.get("remedy")
        if remedy is not None:
            for problem in C.remedy_errors(remedy):
                errors.append(f"{path.name}: {label} {who}: {problem}. The remedy is the fix "
                              "this row found: {kind, where, change, restart?}, names only")
        elif this_version and blocking:
            errors.append(f"{path.name}: {label} {who} blocks on the environment with no "
                          "`remedy` — the row names a state and not the change that ends it. "
                          "Add {kind: flag|credential|data|service, where: <file:lines or the "
                          "variable NAME>, change: <what to set>, restart: <what to restart>}")
        prose = str(row.get("detail") or row.get("needs") or "")
        if isinstance(remedy, dict):
            prose += " " + " ".join(str(remedy.get(f) or "") for f in (*C.REMEDY_FIELDS, "restart"))
        for key in _secret_value_leaks(prose):
            errors.append(f"{path.name}: {label} {who} carries a value for `{key}` — name the "
                          "variable, never its value. An artifact is read by everyone this "
                          "story is shown to")


def _secret_value_leaks(text: str) -> list:
    """`KEY=value` in prose where KEY names a credential. One spelling of "this name holds a
    credential" in the factory: `env_probe.SECRET_NAME`, with `s5_precheck` asking the same
    question of the same rows before the artifact is ever written."""
    try:
        from s5_precheck import secret_value_leaks
    except Exception:
        return []
    return secret_value_leaks(text)


def assert_line_regexes(path: Path) -> list:
    """The compiled patterns that make a line of a self-fix an assertion line: `detectors.json` `assert_lines`
    (through `assertion_detectors.assert_line_patterns`, the one reader) united with the head of every assertion
    form of `assertion_probes`.

    This check may only OVER-refuse (B-407 C, E-C4): a line counted as an assertion in `before` and absent from
    `after` is a refusal, so a pattern added can add refusals and never remove one. A key that is dropped,
    unreadable or malformed therefore leaves `AD.ASSERT_LINE_FLOOR` (the same six patterns) and one
    ORACLE_NOTES line naming the problem - never "no check". A table of heads that cannot be read adds nothing."""
    try:
        patterns = AD.assert_line_patterns()
    except Exception as exc:
        patterns = list(AD.ASSERT_LINE_FLOOR)
        ORACLE_NOTES.append(f"{path.name}: {str(exc)[:200]} - dropped Then lines were checked against the "
                            "built-in floor of six assertion patterns")
    try:
        patterns += AD.assertion_heads()
    except Exception:
        pass
    return [re.compile(p) for p in dict.fromkeys(patterns)]


def assertion_lines(blob, asserts: list) -> set:
    return {ln.strip() for ln in str(blob or "").splitlines() if any(rx.search(ln) for rx in asserts)}


def check_self_fixes(path: Path, data: dict, errors: list) -> None:
    """A repair may fix a selector, an import or the test's own data — never a Then. If an
    assert present in `before` is gone from `after`, the test was quieted, not fixed."""
    fixes = data.get("self_fixes") or []
    asserts = assert_line_regexes(path) if fixes else []   # no fix, no table read and no note
    for i, fix in enumerate(fixes):
        if not isinstance(fix, dict):
            continue
        for key in ("test", "what", "why_test_defect", "evidence"):
            if not str(fix.get(key) or "").strip():
                errors.append(f"{path.name}: self_fixes[{i}] has no '{key}' — a repair without its "
                              "proof that the product behaves to spec is an adjusted expectation")
                break
        dropped = sorted(assertion_lines(fix.get("before"), asserts) - assertion_lines(fix.get("after"), asserts))
        if dropped:
            errors.append(f"{path.name}: self_fixes[{i}] ({fix.get('test')}) dropped the Then line "
                          f"`{dropped[0][:80]}` — restore it; a weakened assert is not a fix")


def check_context_manifest_v0(path: Path, data: dict, errors: list) -> None:
    """`related[]` is what the ticket NAMES, never the parent's other children.

    The pilot's successor (TP2-2290, 16.09) showed a role handed "sibling stories
    with status" and no data to satisfy it: it built a range of ticket keys by incrementing
    a number and queried each one, across teams that share the epic. The scout's charter now
    forbids that; this is the check that the artifact agrees. A `source` says WHERE in this
    ticket the key was read — an entry without one is a ticket somebody went looking for."""
    for i, rel in enumerate(data.get("related") or []):
        if not isinstance(rel, dict):
            errors.append(f"{path.name}: related[{i}] is not an object — "
                          "each entry is {key, kind, source}")
            continue
        who = str(rel.get("key") or f"related[{i}]")
        kind = str(rel.get("kind") or "")
        if kind not in C.RELATED_KINDS:
            errors.append(f"{path.name}: {who}: kind '{kind}' outside "
                          f"{list(C.RELATED_KINDS)} — an invented kind is not a kind")
        if not str(rel.get("source") or "").strip():
            errors.append(f"{path.name}: {who} has no 'source' — say where in this ticket "
                          "the key was read (description, AC, a comment, the links field, an "
                          "MR thread). A key with no source was gone looking for, not named.")

    # One entry per repository the cascade ran in. A story can be split across repositories
    # — QA-EXAMPLE had a backend MR and a frontend MR — and a single `implementation`
    # object can hold only one of them, so the other half of the change was invisible to
    # every later stage.
    rows = data.get("implementations")
    if isinstance(rows, list) and rows:
        seen = set()
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{path.name}: implementations[{i}] is not an object — each "
                              "entry is {repo, source, mr, branch, commit, diff_path}")
                continue
            repo = str(row.get("repo") or "").strip()
            if not repo:
                errors.append(f"{path.name}: implementations[{i}] has no 'repo' — name the "
                              "repository this entry came from (a config.code_repos[].name, "
                              "or 'tests' for this one)")
            elif repo in seen:
                errors.append(f"{path.name}: implementations names '{repo}' twice — one "
                              "entry per repository; the cascade stops at the first hit "
                              "inside each")
            seen.add(repo)
            src = str(row.get("source") or "")
            if src not in C.IMPLEMENTATION_SOURCES:
                errors.append(f"{path.name}: implementations[{i}].source '{src}' outside "
                              f"{list(C.IMPLEMENTATION_SOURCES)}")
        first = rows[0] if isinstance(rows[0], dict) else {}
        top = data.get("implementation") if isinstance(data.get("implementation"), dict) else {}
        if top and first and str(top.get("source") or "") != str(first.get("source") or ""):
            errors.append(f"{path.name}: implementation.source "
                          f"'{top.get('source')}' disagrees with implementations[0].source "
                          f"'{first.get('source')}' — the first entry IS the primary one, "
                          "and every reader that predates the list reads the summary")

    # The v2 discovery records the build would refuse, said in the turn that wrote them (t-1347). `requirement_sources` is
    # not judged here: the build replaces it from work/source-inventory.json. An absent or empty-valued section is the
    # build's `or []` (no problem); a v1 manifest with none of the keys meets no v2 rule.
    from context_bundle import v2_discovery_problems
    judged = ("coverage_search", "existing_test_candidates")
    present = tuple(key for key in judged if data.get(key) and isinstance(data[key], list))
    for key in judged:
        if data.get(key) and not isinstance(data[key], list):
            errors.append(f"{path.name}: {key} must be an array or absent")
    errors += [f"{path.name}: {problem}" for problem in v2_discovery_problems(data, sections=present)]


def check_run_report_v0(path: Path, data: dict, errors: list) -> None:
    status = data.get("execution_status")
    if status is None:
        errors.append(f"{path.name}: no execution_status — it is computed from the run's own evidence "
                      f"and must be one of {list(C.EXECUTION_STATUS)}")
    elif status not in C.EXECUTION_STATUS:
        errors.append(f"{path.name}: execution_status '{status}' outside {list(C.EXECUTION_STATUS)} — "
                      "an invented status is not a status")
    elif data.get("env_preflight") == "blocked" and status != "env_blocked":
        errors.append(f"{path.name}: env_preflight is blocked but execution_status is '{status}' — one "
                      "field, one source: a blocked preflight means env_blocked")
    check_result_rows(path, data, errors)


def check_result_rows(path: Path, data: dict, errors: list) -> None:
    """Every `results[]` row carries an identity, a status, and — for a skip — a reason.

    Until 0.3.0 this file checked `execution_status` and nothing else, so nine rows of `{}`
    passed the validator and the exit gate and reached the dashboard as "?" with no name and
    an invented `regression` origin (TP2-2290, a story written ahead of its
    implementation, where every row is a skip and the reason IS the report). A row nobody can
    name is not a result; a skip whose reason was never written cannot be shown, whatever the
    dashboard does."""
    rows = data.get("results")
    if not isinstance(rows, list):
        return
    non_passed = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{path.name}: results[{i}] is not an object")
            continue
        who = C.result_id(row) or str(row.get("case") or "")
        status = C.result_status(row)
        named = C.case_ids(row.get("case"))
        if len(named) > 1:
            errors.append(f"{path.name}: results[{i}].case names {len(named)} cases "
                          f"({', '.join(named)}) — one row per case, even when one test "
                          "covers several: ledger.py matches a case id exactly, so a "
                          "compound cell matches nothing and every one of those cases "
                          "reaches the ledger as `not_executed`")
        if not who:
            errors.append(f"{path.name}: results[{i}] has neither test_id nor case — a row "
                          "nobody can name is not a result, and the board prints it as a "
                          "nameless regression test")
        if not status:
            errors.append(f"{path.name}: {who or f'results[{i}]'} has no status — one of "
                          f"{list(C.RESULT_STATUS)} (the board prints a missing one as '?')")
        elif status not in C.RESULT_STATUS:
            errors.append(f"{path.name}: {who or f'results[{i}]'}: status '{status}' outside "
                          f"{list(C.RESULT_STATUS)}")
        elif status == "skipped" and not str(row.get("reason") or "").strip():
            errors.append(f"{path.name}: {who} is skipped with no reason — the one thing a "
                          "reader needs from a skipped test is why, and run_suite.py takes it "
                          "from the junitxml <skipped message>")
        if status in ("failed", "error", "skipped"):
            non_passed += 1
    totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
    if rows and totals:
        expected = sum(int(totals.get(k) or 0) for k in ("failures", "errors", "skipped"))
        if expected and non_passed != expected:
            errors.append(f"{path.name}: totals count {expected} test(s) not passed but "
                          f"results[] lists {non_passed} — every non-passed test is listed by "
                          "name (only passed rows are ever capped)")


def check_triage_v0(path: Path, data: dict, errors: list, task_root=None) -> None:
    """`task_root` comes from the CALLER (HF2-18, N1): `artifact_producer.validate` is handed `Path('triage.json')` with
    no folder, so a root derived from `path` would judge `control.evidence` against the process's cwd. `None` = the caller
    has no task root: the evidence file's existence is not judged (the caller says so), never refused for it."""
    all_rows = C.triage_rows(data)
    # the run report, when the caller has a task root and the file is there: the live-blocker check of `blocked_thens`
    # (R6) needs the current failures; no report = that one fact is not judged here (the delivery check judges it)
    report = (C.load_json(C.artifact(Path(task_root), "run-report.json")) or None) if task_root is not None else None
    # P26 (RN1-10): ONE row answers an observation of a manual check (`<case>#obs<n>`); a second row for it is refused,
    # whatever its verdict, with the row to keep as the door (the delivery reader binds one row per target)
    # The rule is `contract.observation_duplicates`, the binder's own and attempt-aware (t-1747 F5): a stale row of an earlier
    # attempt is not a competitor
    for name, rows_ in C.observation_duplicates(all_rows, report).items():
        errors.append(f"{path.name}: {name}: {len(rows_)} triage rows both answer the observation {name} (attempt "
                      f"{str(rows_[0].get('attempt_id') or '-')[:30]}) - keep one row for it")
    for i, row in enumerate(all_rows):
        test = row.get("test") or f"triage[{i}]"
        verdict = str(row.get("verdict") or "")
        if verdict not in C.TRIAGE_VERDICTS:
            errors.append(f"{path.name}: {test}: verdict '{verdict}' outside {list(C.TRIAGE_VERDICTS)}")
            continue
        # the observation-only word NO_DEFECT (P26): the SAME reader as the delivery check (AR-13)
        errors += [f"{path.name}: {test}: {p}" for p in C.triage_no_defect_problems(row, report, task_root)]
        # the fields of the red-then chain (R4, R6): ONE reader each, shared with the delivery check (AR-13)
        errors += [f"{path.name}: {test}: {p}" for p in C.triage_diagnostic_problems(row, task_root)]
        errors += [f"{path.name}: {test}: {p}" for p in C.triage_blocked_problems(row, task_root, all_rows, report)]
        errors += [f"{path.name}: {test}: {p}" for p in C.triage_reorder_problems(row)]
        # the `control` experiment block (E17): after the closed list has refused an unknown word, before the FLAKY-only gate
        # below - a branch that comes after it never sees the word that needs the block
        errors += [f"{path.name}: {test}: {p}" for p in C.triage_control_problems(row, task_root)]
        # the `contradiction` block of the misread-evidence word (HF8-19): the SAME reader as the delivery check and the S7 re-judge
        errors += [f"{path.name}: {test}: {p}" for p in C.triage_contradiction_problems(row, task_root)]
        if verdict != "FLAKY":
            continue
        reruns = row.get("reruns")
        if not isinstance(reruns, int) or reruns < C.FLAKY_MIN_RERUNS:
            errors.append(f"{path.name}: {test}: FLAKY with reruns={reruns} — a flake verdict needs "
                          f">= {C.FLAKY_MIN_RERUNS} isolated executions as its witness, counted "
                          "across every role through the manifest's runs[]")
        if row.get("mechanism") not in C.FLAKY_MECHANISMS:
            errors.append(f"{path.name}: {test}: FLAKY without a mechanism from "
                          f"{list(C.FLAKY_MECHANISMS)} — an unnamed mechanism cannot be repaired")
        if not str(row.get("fix_result") or "").strip():
            errors.append(f"{path.name}: {test}: FLAKY with no fix_result — record 'fixed' or "
                          "'not_fixed'; an unfixed flake is not verified, and quarantine is the "
                          "human's call at gate B")


# --- test code under config.tests_root ------------------------------------------------------------

def tests_root_path(cfg: dict) -> Path | None:
    raw = str(cfg.get("tests_root") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    try:
        return (p if p.is_absolute() else project_root() / p).resolve()
    except Exception:
        return None


def is_test_code(path: Path, cfg: dict) -> bool:
    """Under `tests_root`, and a test by the ONE recognizer (`test_files`, consumer `test_code`): a code file whose
    name or folder is a usual test name, or that the project's own word names (a `test_locations` entry or a
    `run.levels` pattern - but not `tests_root` / `roots.test` alone, which name a folder that may hold helpers).

    The unsafe error here is a test that is NOT recognised (its detectors never run), yet a helper that is not a
    test (`qa/helpers/latest.py`, "test" inside "latest") is no longer one (F-3). A bare `conftest.py` is not test
    code either: it holds fixtures, and a `pytest.skip(` inside a fixture is an environment gate, not a hidden test
    (the Lead's decision on the t-557 F6; `qa/tests/conftest.py` IS test code by its folder). When the usual names
    or code extensions cannot be read the recognizer answers None, and the FR-59 safe default applies (K-C8): a file
    under `tests_root` whose extension is in `test_files.CODE_EXTENSION_FLOOR` IS test code, and one ORACLE_NOTES
    line names the unreadable markers and the floor; any other file is not."""
    root = tests_root_path(cfg)
    if root is None:
        return False
    try:
        path.resolve().relative_to(root)
    except Exception:
        return False
    # The path is asked RELATIVE to the project (or, for a tests_root outside it, to the folder above that root):
    # the recognizer reads every folder segment as written, so an absolute path would let a checkout that happens
    # to live under `.../test/...` make every file a test.
    try:
        asked = path.resolve().relative_to(project_root().resolve())
    except ValueError:
        asked = path.resolve().relative_to(root.parent)
    answer = TF.is_test_for("test_code", asked, cfg, root=project_root())
    if answer is None:
        note = ("references/test-path-markers.json could not be read (the usual test names or code extensions), so "
                f"files with the extensions {', '.join(TF.CODE_EXTENSION_FLOOR)} were treated as code")
        if note not in ORACLE_NOTES:
            ORACLE_NOTES.append(note)
        return path.suffix.lower() in TF.CODE_EXTENSION_FLOOR
    return answer is True


# --- pipeline.json (the story's own state machine) -------------------------------------------------

PIPELINE_STAGE_STATUS = ("pending", "running", "done", "halted")


def check_pipeline_v0(path: Path, data: dict, errors: list) -> None:
    """stage_guard reads this file on every dispatch: a stage status outside the four, or a
    missing gates block, turns the guard into a coin toss."""
    for key in ("ticket", "stages", "gates"):
        if key not in data:
            errors.append(f"{path.name}: required key '{key}' is missing — stage_guard reads it on "
                          "every dispatch; without it the order rules cannot be applied")
    stages = data.get("stages")
    if not isinstance(stages, dict):
        return
    known = {s.get("id") for s in (load_ref_json("stages.json").get("stages") or [])}
    for name, entry in stages.items():
        if known and name not in known:
            errors.append(f"{path.name}: stage '{name}' is not in references/stages.json "
                          f"({sorted(known)}) — the pipeline and the stage model must agree")
            continue
        status = entry.get("status") if isinstance(entry, dict) else None
        if status not in PIPELINE_STAGE_STATUS:
            errors.append(f"{path.name}: {name}: status '{status}' outside "
                          f"{list(PIPELINE_STAGE_STATUS)} — an invented status is not a status")


# --- config.json -------------------------------------------------------------------------------

def check_config(path: Path, errors: list) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"{path.name}: broken JSON ({e}) — every hook reads this file; a broken config "
                      "silently disables the factory's own laws")
        return
    version = data.get("schema_version")
    if version != REQUIRED_SCHEMA_VERSION:
        errors.append(f"{path.name}: schema_version is {version!r}, this plugin requires "
                      f"{REQUIRED_SCHEMA_VERSION} — run `readiness.py --json` for the migration hint")


# --- dispatch --------------------------------------------------------------------------------------

def collect_errors(path: Path, cfg: dict | None = None) -> list:
    """Every rule that applies to this file. Importable so scripts/tests can assert on the
    exact message instead of on an exit code."""
    cfg = load_config() if cfg is None else cfg
    target = norm(str(path))
    errors: list = []
    in_artifacts = "/qa-factory/artifacts/" in target

    # The case branch stays BEFORE the critic-findings branch below: a name is recognised as a
    # case first, and only what is not a case document is read as the findings file. The name is
    # judged by the project's id form (`config.case_id_form`, then `TC-NNN`) - the pattern here
    # used to be `tc-<n>.md`, so a project-form case was never validated on write (B-013, FR-17).
    if "/test-cases/" in target and C.is_case_file_name(target.rsplit("/", 1)[-1], cfg=cfg):
        check_case(path, errors)
    elif "/test-cases/" in target and target.endswith("critic-findings.md"):
        # The roll-call decides the verdict, and it is read on write so the critic learns it
        # in the turn that wrote the file — not at the exit gate, and not never.
        from critic_rollcall import findings_errors
        errors.extend(findings_errors(path))
    elif "/bugs/" in target and re.search(r"(at-)?bug-\d+\.md$", target):
        check_bug(path, errors)
    elif "/exploratory-charters/" in target and re.search(r"ch-\d+\.md$", target):
        check_charter(path, errors)
    elif target.endswith("/qa-factory/config.json"):
        check_config(path, errors)
    elif "/qa-factory/state/" in target and target.endswith("pipeline.json"):
        check_pipeline(path, errors)
    elif ("/qa-factory/records/" in target or "/qa-factory/state/" in target) and target.endswith("estimation-ledger.jsonl"):
        check_estimation_ledger(path, errors)         # records/ is its place; state/ is where an older factory kept it
    elif "/qa-factory/state/" in target and target.endswith("escape-ledger.jsonl"):
        check_escape_ledger(path, errors)
    elif in_artifacts and target.endswith("requirements-register.md"):
        check_register(path, errors)
    elif in_artifacts and target.endswith("test-plan.md"):
        if C.plan_is_v0(path):
            check_plan_v0(path, errors)
        else:
            check_plan(path, errors)
    elif in_artifacts and target.endswith("understanding.md"):
        check_understanding(path, errors)
    elif in_artifacts and target.endswith("requirements-review.md"):
        check_requirements_review(path, errors)
    elif in_artifacts and target.endswith("test-report.md"):
        check_test_report(path, errors)
        check_report_human_text(path, errors)
    elif in_artifacts and target.endswith(".json"):
        check_phase_json(path, errors)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if path.name == "test-plan.json":
            from planning_contract import validate_plan
            rows = data.get("rows") if isinstance(data, dict) else data
            errors.extend(validate_plan(rows))
            if isinstance(data, dict):
                from case_lifecycle import validate_actions
                errors.extend(validate_actions(data.get("lifecycle_actions", [])))
        if isinstance(data, dict):
            if path.name == "automation-manifest.json":
                check_manifest_v0(path, data, errors)
            elif path.name == "run-report.json":
                check_run_report_v0(path, data, errors)
            elif path.name == "triage.json":
                check_triage_v0(path, data, errors, _story_root(path))
            elif path.name == "pipeline.json":
                check_pipeline_v0(path, data, errors)
            elif path.name == "context-manifest.json":
                check_context_manifest_v0(path, data, errors)
            elif path.name == "context-bundle.json":
                try:
                    validate_record("ContextBundle", data)
                    from context_bundle import validate_bundle
                    validate_bundle(data)
                except ValueError as exc:
                    errors.append(f"context-bundle.json: {exc}")
    # Test code is not judged on write (X7-2): a retry, a broad status set or a skip in it is the code critic's to read.
    return errors


def collect_findings(path: Path) -> list:
    """Defects of the factory's OWN bookkeeping found on a write: named, never refused.

    An `errors` line is something the writer must repair inside the same turn. A stage that
    finished before it started is not the writer's to repair — the clock that stamped it is
    the factory's (TP2-2553's "Run Timeline", where S0 finished 1h38m before it began
    and every reader downstream showed a clamped zero). So it travels on this second channel:
    the write goes through, the finding names the stage and both stamps, and the person is
    never asked to fix a defect that was never theirs.
    """
    if path.name != "pipeline.json":
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []  # broken JSON is already an error on the other channel
    from stage_done import clock_anomalies
    return [f"{path.name}: {stage} finished before it started "
            f"({stamps['started_at']} -> {stamps['finished_at']}) — owner: factory. The stage "
            "record stands; its duration is excluded from the retro's sums rather than counted "
            "as zero."
            for stage, stamps in clock_anomalies(data)]


def main() -> None:
    if "--check" in sys.argv:
        i = sys.argv.index("--check")
        target = Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 else None
        if target is None or not target.exists():
            print("usage: validate_artifacts.py --check <existing file>", file=sys.stderr)
            sys.exit(1)
        del ORACLE_NOTES[:]
        found = collect_errors(target)
        if found:
            print("ARTIFACT VALIDATION FAILED:\n- " + "\n- ".join(found), file=sys.stderr)
            sys.exit(2)
        for finding in collect_findings(target):
            print("factory finding: " + finding)
        if "--verbose" in sys.argv:
            for note in ORACLE_NOTES + collect_notes(target):
                print("note: " + note)
        print(f"valid: {target.name}")
        sys.exit(0)

    event = read_event()
    if event is None:
        # H18 (RH1-5): exit 1 here reached nobody. PostToolUse exit 2 is feedback to the model - the call already ran
        # and is not undone - so the role is told, with the door that does the check by hand (F-16).
        block("ARTIFACT VALIDATION: the file just written was not validated (the hook event could not be parsed: "
              "broken stdin) - the factory's own defect; validate it with `validate_artifacts.py --check <file>`")
    if event.get("tool_name") not in ("Write", "Edit", "apply_patch"):
        sys.exit(0)
    from host_adapter import mutation_events
    try:
        operations = mutation_events(event)
    except ValueError as exc:
        block(f"ARTIFACT VALIDATION FAILED: {exc}; validation not performed")
    paths = []
    for operation in operations:
        fp = (operation.get("tool_input") or {}).get("file_path")
        if fp:
            path = Path(fp)
            if not path.is_absolute():
                path = Path(event.get("cwd") or Path.cwd()) / path
            if path.is_file() and path not in paths:
                paths.append(path)
    try:
        errors = [error for path in paths for error in collect_errors(path, load_config(event))]
    except Exception as exc:
        # H19: a validator that crashed used to exit 1 (nobody reads it) - the file stood unvalidated, said to no one.
        names = ", ".join(path.name for path in paths) or "the file just written"
        block(f"ARTIFACT VALIDATION: {names} was written but not validated ({type(exc).__name__}: {exc}) - the "
              "factory's own defect; validate it with `validate_artifacts.py --check <file>`")
    if errors:
        block("ARTIFACT VALIDATION FAILED:\n- " + "\n- ".join(errors) + "\nFix it within this same turn.")
    # P6: the next-step hint is printed only for a valid artifact (errors is empty —
    # a reject would already have exited via block() above). Fail-open: a lookup/print
    # error must not fail a hook that already passed validation.
    try:
        hints = list(dict.fromkeys(NEXT_STEPS[path.name] for path in paths if path.name in NEXT_STEPS))
        hints.extend("note: " + n for path in paths for n in collect_notes(path))
        # No metric-signal notice here (SC1-4b, F-3 (a)): this hook is SYNCHRONOUS on every Write/Edit and the
        # notice re-told the same open signals after each one. They stay in `metric-signals.json`, on the
        # dashboard, in the role prompt at dispatch and after a compact; the Stop capture prints them as before.
        # RH1-5 (H16): the role reads NEXT_STEPS and notes through the host adapter's notice channel (a bare stdout
        # on PostToolUse reaches nobody on Claude); a "factory finding" is the factory's, so it goes to the person.
        for path in paths:
            for finding in collect_findings(path):
                person_signal(event, "validate", f"{path.name}: {finding}")
        hooklib.notice(event, "\n".join(hints), reader="role")
        hooklib.take_notices(event, 0, default_event="PostToolUse")
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
