#!/usr/bin/env python3
"""The validator class guard (t-1355 N3): a role learns what a validator accepts BEFORE the work, and a refusal lists every
problem at once, each with its record position.

The class (docs/tasks/specs/reviews/t-1349-validator-class-sweep.md): a role-facing validator that (A) tells the role its
fields only in `--help` or in the refusal, or (B) raises the first problem of two and names no record position. This file holds
the class three ways:

  * BATTERY  - every role-facing validator in `ROLE_VALIDATORS` is given ONE input carrying exactly two defects and must name
    both in ONE answer, each with its locator (`section[i]`, `section[i].field`); a validator that raises the first and stops,
    that lists both without a position, that accepts the bad input, or that crashes instead of refusing, fails.
    A returned list (`check_context_manifest_v0`, `planning_contract.validate_plan`, `artifact_producer.validate`,
    `manual_evidence.validate`) is read as a whole; a raised text must be a `detector_verdict.compound` of exactly two items.
  * FIELD PINS - the fields and closed lists the validators read live in ONE carrier constant each (`V2_REQUIRED`,
    `SPEC_REQUIRED`, `FACTS_KEYS`, `TRIAGE_ROW_IDS`); the text the role reads before the work (an ahead card or a charter)
    must hold every value of it, so a field added to the code breaks this test until the role is told (FR-38, AR-10, AR-22).
  * CENSUS   - every role command (`role-commands.json`) and every role-written artifact (`artifact-writers.json`, writer
    ending `(the role)`) names where the role learns its fields: a vocabulary pinned here or in `test_ahead_cards.py`, a skeleton
    the code prints, a file, a reason the command takes no role-written record, or a known gap that is PRINTED as OPEN and not
    failed (FR-4: an informed pass, never a silent one). A new command or artifact with no entry fails and is named (AR-10).

It is written against the constants and message shapes of the t-1355 spec; on a tree that lacks them (N1/N2 not merged) it
fails at import - the guard is never green against code that lacks what it guards.
"""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import artifact_producer  # noqa: E402
import context_bundle  # noqa: E402
import estimate_record  # noqa: E402
import execution_fingerprint  # noqa: E402
import friction  # noqa: E402
import manifest_put  # noqa: E402
import manual_evidence  # noqa: E402
import planning_contract  # noqa: E402
import record_schema  # noqa: E402
import validate_artifacts  # noqa: E402
from detector_verdict import split_items  # noqa: E402
import test_ahead_cards  # noqa: E402  (its VOCABULARIES table and card reader are imported, never edited)

PLUGIN = harness.PLUGIN_ROOT

# --- the inputs ------------------------------------------------------------------------------------------------------------

SEARCH = {"repo": "app", "revision": "abc", "changed_area": "src", "searched_paths": ["tests"],
          "status": "complete", "reason": "searched"}
CANDIDATE = {"candidate_id": "C-1", "repo": "app", "revision": "abc", "path": "tests/test_a.py", "selector": "test_a",
             "parameter_ids": [], "level": "unit", "assertion_refs": ["tests/test_a.py:4"],
             "candidate_requirement_refs": ["R-1"], "origin": "existing", "result_candidate_refs": []}
SOURCE = {"source_id": "SRC-1", "relation": "subject", "ref": "STORY-1", "revision": "7", "status": "read",
          "evidence_ref": "snapshot.json"}
MANIFEST = {"ticket": "QA-1", "implementations": [{"repo_id": "app", "source_sha": "abc", "diff_path": "change.diff"}],
            "changed_areas": ["src"], "facts": [{"id": "R-1", "value": "plain"}], "known_paths": ["src/a.py"],
            "requirement_sources": [SOURCE], "coverage_search": [], "existing_test_candidates": [CANDIDATE]}
PROVENANCE = {"result": "not_applicable", "profile_id": "unit", "environment_id": "local",
              "expected_source_revision": "abc", "timestamp": "2026-10-23T00:00:00Z", "evidence_refs": []}


def plan_row(i: int, **more) -> dict:
    """A row that passes `planning_contract.validate_plan` (the same shape `test_plan_row.valid` writes)."""
    row = {"id": f"TS-{i}", "impact": "medium", "likelihood": "medium", "confidence": "medium", "risk_rationale": "why",
           "risk_source_refs": ["R-1"], "risk_policy_revision": "r1", "coverage_refs": ["R-1"], "unknowns": [],
           "verification_depth": "normal", "required_scenarios": ["s"], "test_level_rationale": "lvl",
           "design_review_required": False}
    row.update(more)
    return row


def v2_bundle(root: Path) -> dict:
    """A valid v2 bundle built by the code that builds it, to be damaged by the battery rows."""
    (root / "change.diff").write_text("diff --git a/x b/x\n+x\n", encoding="utf-8")
    return context_bundle.build(copy.deepcopy(MANIFEST), root)


# --- the helper the battery stands on ------------------------------------------------------------------------------------

def answer(call) -> tuple:
    """`(kind, text)`: kind is `list` (returned problems), `raised` (a ValueError - a refusal), `accepted` (returned
    nothing/[]) or `crash:<TypeName>` (a non-ValueError escaped: a crash is not a refusal, E-N3-6)."""
    try:
        got = call()
    except ValueError as exc:
        return "raised", str(exc)
    except Exception as exc:  # noqa: BLE001 - the point is to name what escaped
        return "crash:" + type(exc).__name__, str(exc)
    if isinstance(got, list) and got:
        return "list", "\n".join(str(item) for item in got)
    return "accepted", ""


def lists_both(call, needles) -> tuple:
    """`(ok, text, kind)`: true only when BOTH needles are in the one answer; a raised text must also be a
    `compound` of exactly two items (the head count equals the items, AR-18). An empty answer, an accepted input and a crash
    are false and print what they were."""
    kind, text = answer(call)
    if kind not in ("list", "raised"):
        return False, text, kind
    if not all(needle in text for needle in needles):
        return False, text, kind
    if kind == "raised":
        items = split_items(text)
        if items is None or len(items) != 2:
            return False, text, kind
    return True, text, kind


# --- the battery ---------------------------------------------------------------------------------------------------------

def battery(root: Path) -> list:
    """`(id, script, callable, (needle1, needle2), part)`: ONE input with exactly two defects per row (the returned-list rows
    marked below carry unrelated further problems where a fully valid base record would cost more than the row proves; their
    needles are still the two named defects)."""
    base = v2_bundle(root)

    def bundle(**sections):
        out = copy.deepcopy(base)
        out.update(sections)
        return out

    spec = {"source_revision": "abc", "test_files": [], "config_files": [], "dependency_files": [],
            "runtime_provenance": dict(PROVENANCE), "profile_id": "unit"}
    test_file = root / "test_one.py"
    test_file.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    config_file = root / "config.json"
    config_file.write_text("{}", encoding="utf-8")
    two_missing = {k: v for k, v in spec.items() if k not in ("source_revision", "dependency_files")}
    two_missing.update(test_files=[str(test_file)], config_files=[str(config_file)])
    two_bad_files = dict(spec, test_files=[{"path": str(test_file), "sha256": "xyz"}],
                         config_files=[str(root / "no-such-config.json")], dependency_files=[])
    manifest_bad = copy.deepcopy(MANIFEST)
    manifest_bad["implementations"] = [{"repo": "app", "source": "diff", "diff_path": "change.diff"}]   # the hook's own shape
    manifest_bad["coverage_search"] = [dict(SEARCH, status="not_found")]
    manifest_bad["existing_test_candidates"] = [{k: v for k, v in CANDIDATE.items() if k != "selector"}]

    def hook(data):
        errors: list = []
        validate_artifacts.check_context_manifest_v0(Path("context-manifest.json"), data, errors)
        return errors

    enum_schema = {"type": "object", "properties": {"s": {"enum": ["x", "y"]}, "t": {"enum": ["p"]}}}
    bug = artifact_producer.prepare("bug")
    bug["frontmatter"].update(status="Wontfix", severity="huge")
    bug["body"] = "body"
    expectation_good = {"function": "t.test_a", "red_attempt": "S5-r-1", "green_attempt": "S5-r-2",
                        "then_refs": [{"case": "TC-1", "then": 1}], "what_changed": "a -> b", "reason": "why"}
    return [
        ("B1", "context_bundle.py", lambda: context_bundle.validate_bundle(bundle(
            coverage_search=[dict(SEARCH, status="not_found")],
            existing_test_candidates=[dict(CANDIDATE, origin="guessed")])),
         ("coverage_search[0].status must be one of", "existing_test_candidates[0].origin must be one of"), "N1"),
        ("B2", "context_bundle.py", lambda: context_bundle.validate_bundle(bundle(
            coverage_search=[{k: v for k, v in SEARCH.items() if k != "reason"}] * 2)),
         ("coverage_search[0]: missing required fields: reason", "coverage_search[1]: missing required fields: reason"), "N1"),
        ("B3", "validate_artifacts.py", lambda: hook(manifest_bad),
         ("context-manifest.json: coverage_search[0].status",
          "context-manifest.json: existing_test_candidates[0]: missing required fields: selector"), "N1"),
        ("B4", "execution_fingerprint.py", lambda: execution_fingerprint.build(two_missing),
         ("missing source_revision", "missing dependency_files"), "N2"),
        ("B5", "execution_fingerprint.py", lambda: execution_fingerprint.build(two_bad_files),
         ("test_files[0]: sha256 of", "(config_files[0])"), "N2"),
        ("B6", "estimate_record.py", lambda: estimate_record.append_record(root, "QA-1", {"forecast": [], "actual": "x"}),
         ("forecast must be an object", "actual must be an object"), "N2"),
        ("B7", "manual_evidence.py", lambda: manual_evidence.write_block(root, ["a", "b"]),
         ("records[0]:", "records[1]:"), "N2"),
        ("B8", "record_schema.py", lambda: record_schema.validate({"type": "object", "required": ["a", "b"]}, {}),
         ("$: missing a", "$: missing b"), "regression guard"),
        ("B9", "record_schema.py", lambda: record_schema.validate(enum_schema, {"s": "z", "t": "q"}),
         ("$.s: unsupported value (one of x, y)", "$.t: unsupported value (one of p)"), "N2"),
        ("B10", "planning_contract.py", lambda: planning_contract.validate_plan(
            [plan_row(1, verification_depth="deep"), plan_row(2, verification_depth="deep")]),
         ("TS-1: invalid verification depth (one of low, normal, critical)", "TS-2: invalid verification depth"), "N2"),
        ("B11", "artifact_producer.py", lambda: artifact_producer.validate("bug", bug),
         ("frontmatter.status must be one of", "frontmatter.severity must be one of"), "N2"),
        ("B12", "artifact_producer.py", lambda: artifact_producer.validate(
            "triage", {"triage": [{"attempt_id": "a-1"}, {"instance_id": "i-1"}]}),
         ("triage[0]", "triage[1]"), "OK today + N2 text"),
        ("B13", "manual_evidence.py", lambda: manual_evidence.validate(
            {"schema_version": 2, "result": "maybe", "evidence_policy": "video"}, root),
         ("invalid result (one of", "invalid evidence_policy (one of"), "N2"),
        ("B14", "manifest_put.py", lambda: manifest_put.expectation_change_problems(
            [dict(expectation_good, function=""), dict(expectation_good, red_attempt="")], []),
         ("expectation_changes[0].`function`", "expectation_changes[1].`red_attempt`"), "regression guard"),
    ]


# --- the field pins ------------------------------------------------------------------------------------------------------

def field_vocabularies() -> list:
    """`(label, values, where)`: the carrier constant each validator reads, and the text the role reads before the work."""
    scout = ("card", "qa-scout")
    return [
        ("scout coverage_search fields", context_bundle.V2_REQUIRED["coverage_search"], scout),
        ("scout existing_test_candidates fields", context_bundle.V2_REQUIRED["existing_test_candidates"], scout),
        ("scout search statuses", sorted(context_bundle.SEARCH_STATUSES), scout),
        ("scout test origins", sorted(context_bundle.TEST_ORIGINS), scout),
        ("scout not_found place", ("coverage_status: not_found",), scout),
        ("scout not_found place (charter)", ("coverage_status: not_found",), ("file", "agents/qa-scout.md")),
        # X7-3 / X8-4: the runner charter no longer lists the fingerprint spec keys (the Commands card and the lifecycle reference tell them);
        # the TOLD row points at the one carrier that does (the old runner row and this lifecycle row were the same vocabulary twice).
        ("fingerprint spec keys", execution_fingerprint.SPEC_REQUIRED, ("file", "references/execution-lifecycle.md")),
        ("triage row identity", artifact_producer.TRIAGE_ROW_IDS, ("card", "qa-failure-analyst")),
        ("estimate facts keys", estimate_record.FACTS_KEYS, ("card", "qa-retro-analyst")),
    ]


# A named exclusion, printed and not checked: the card byte budget and the code that writes the section.
EXCLUDED = ("scout requirement_sources fields",
            "excluded: written by code from work/source-inventory.json; the card budget (t-1355 N1)")


def told_text(where: tuple) -> str:
    kind, ref = where
    if kind == "card":
        return str((test_ahead_cards.cards().get(ref) or {}).get("text") or "")
    return (PLUGIN / ref).read_text(encoding="utf-8")


# A pin of a section's fields is read over THAT section's sentence only (t-1398 fix 2): a whole-card substring check is blind
# per section (`repo` sits in both rows, `path` inside `searched_paths`).
SECTION_MARKERS = {
    "scout coverage_search fields": "`coverage_search[]` rows:",
    "scout search statuses": "`coverage_search[]` rows:",
    "scout existing_test_candidates fields": "`existing_test_candidates[]` rows:",
    "scout test origins": "`existing_test_candidates[]` rows:",
}


def section_sentence(text: str, marker: str) -> str:
    """The text after `marker` up to the next ". " (or the end); empty when the marker is not there."""
    start = text.find(marker)
    if start < 0:
        return ""
    rest = text[start + len(marker):]
    end = rest.find(". ")
    return rest if end < 0 else rest[:end]


def words_absent(values, text: str) -> list:
    """The values that are not in `text` as whole words (a name inside a longer identifier does not count)."""
    return [str(v) for v in values if not re.search(r"(?<![\w])" + re.escape(str(v)) + r"(?![\w])", text)]


def where_text(where: tuple) -> str:
    return f"{where[0]} {where[1]}"


# --- the census ----------------------------------------------------------------------------------------------------------

READ = "the sweep t-1349 §3 A column"
TOLD = {
    # role-commands.json `commands`
    "manual_evidence.py prepare": ("open", "sweep row 23: the record fields are printed by `prepare`, not pinned"),
    "manual_evidence.py write-block": ("open", "sweep row 23: the record fields are printed by `prepare`, not pinned"),
    "manual_evidence.py export": ("open", "sweep row 23: the record fields are printed by `prepare`, not pinned"),
    "manual_evidence.py build": ("flags", "the record is built by code from the files manual_capture.py saved; the role passes flags"),
    "manual_evidence.py rejudge": ("flags", "the record is a copy of a written attempt's, changed by code; the role passes flags"),
    "manual_capture.py ui": ("file", "references/manual-capture-steps.json"),
    "manual_capture.py http": ("file", "references/manual-capture-steps.json"),
    "manual_capture.py app": ("file", "references/manual-capture-steps.json"),
    "artifact_producer.py publish": ("skeleton", "artifact_producer.py prepare <kind>"),
    "artifact_producer.py validate-batch": ("skeleton", "artifact_producer.py prepare <kind>"),
    "manifest_put.py --fragment": ("vocab", "dispute values"),
    "critic_rollcall.py --store": ("flags", "a path to the immutable case-version store; no role-written record"),
    "external_writes.py --record": ("open", "not established by t-1349 (sweep row 30 covers the bug side only)"),
    "case_versions.py --pin": ("flags", "two values, a case id and an existing version; no role-written record"),
    "plan_row.py": ("file", "references/risk-policy.md"),
    "execution_fingerprint.py": ("vocab", "fingerprint spec keys"),
    "context_bundle.py": ("vocab", "scout coverage_search fields"),
    "red_sandbox.py --diagnostic": ("file", "references/role-commands.json"),     # `input` spells the five request keys
    # artifact-writers.json `artifacts` whose writer ends `(the role)`
    "work/context-manifest.json": ("vocab", "related kinds"),
    "work/impl-diff.txt": ("flags", "a raw diff; no record fields"),
    "work/requirements-register.md": ("vocab", "requirement sources"),
    "work/requirements-readiness.json": ("skeleton", "artifact_producer.py prepare readiness"),
    "understanding.md": ("file", "references/templates/understanding.md"),
    "test-plan.md": ("file", "references/risk-policy.md"),
    "work/test-plan.json": ("file", "references/risk-policy.md"),
    "work/s5-plan.json": ("file", "agents/qa-automator.md"),     # the charter sends the author to the skeleton and the brief
    "work/grounding.yaml": ("open", "sweep row 11: the skeleton is built by code; the fields are not pinned"),
    "work/probe-models/": ("flags", "qa-code-critic.md sends the critic to the `--alternatives` rows, whose line prints `--alternative <token> [--model work/probe-models/<any name>.json]` and the model file's entry skeleton; a refusal (_models_refusal) prints the whole model form"),
    "work/test-cases/critic-findings.md": ("vocab", "critic verdicts"),
    "work/test-code/critic-findings.md": ("vocab", "expectation change verdicts"),
    "work/test-code/critic-findings-*.md": ("vocab", "expectation change verdicts"),
    "work/s5-notes/S5-qa-code-critic-*.md": ("flags", "free notes for the next window; no record fields"),
    "work/s5-notes/S5-qa-automator-*.md": ("flags", "free notes for the next window; no record fields"),
    "work/s5-notes/": ("flags", "the folder of those notes, one file per dispatch; no record fields"),
    "work/test-cases/": ("vocab", "case frontmatter"),
    "work/triage.json": ("vocab", "triage row identity"),
    "work/evidence/manual/<case>/tried.md": ("file", "references/explore-charter.md"),     # X7-3: the runner writes it; the form of its rows is there
    "work/bug-drafts/": ("open", "sweep row 27: no validator on write for a draft's shape was found"),
    "project:bugs/": ("vocab", "bug sections"),
    "test-report.md": ("vocab", "report sections"),
    "retro.md": ("vocab", "estimate facts keys"),
    "project:obligations.md": ("open", "sweep row 32: project_decisions.py add_finding; the card and --help carry the fields"),
    "project:factory-backlog.md": ("open", "sweep row 32: project_decisions.py add_finding; the card and --help carry the fields"),    "place_answers.py write": ("file", "references/place-answers.json"),     # the answer's keys and closed lists; the command's `input` spells the form
    "first_look.py put": ("file", "references/role-commands.json"),     # `input` spells the row keys and the closed words; the refusal lists every problem with its door
    "reference_snapshot.py put": ("file", "references/role-commands.json"),     # `input` spells the items-file form (id, area, user_path, observed, evidence/old_test, locators_portable, gaps); the refusal lists every problem
    "first_look.py show": ("flags", "a task root and --json; read-only, no role-written record"),
    "walk_session.py open": ("flags", "a walk id, a place and an actor; reopens the dispatch's own session, no role-written record"),
    "walk_session.py item": ("flags", "a case id and an actor; no role-written record"),
    "walk_session.py step": ("file", "references/manual-capture-steps.json"),
    "walk_session.py look": ("flags", "a case id, an actor and a selector; no role-written record"),
    "walk_session.py final": ("flags", "a case id and an actor; no role-written record"),
    "walk_session.py verdict": ("file", "references/role-commands.json"),     # `input` spells the verdict's keys; the rules are asked while the session lives
    "walk_session.py claim": ("file", "references/walk-charter.md"),     # the charter tells the walker to claim a shared record: --kind, --instance, --all
    "walk_session.py done": ("flags", "a walk id; no role-written record"),
    "walk_session.py status": ("flags", "a walk id; read-only, no role-written record"),
    "work/place-answers/": ("file", "references/place-answers.json"),
}
ENTRY_KINDS = ("vocab", "skeleton", "file", "flags", "open")

# The second census column (part B of the class, t-1398 fix 1): for every census key, where the validator that reads what the
# role wrote is held by the battery - a battery row id - or why there is no such row. Seeded from the sweep t-1349 §3: the OK
# rows are `none` with the row quoted; a gap not yet in the battery is `open` and PRINTED. A key with neither fails and is
# named, so a NEW role command or artifact cannot ship a first-error validator unseen (AR-18, FR-4).
GUARDED = {
    "manual_evidence.py prepare": ("none", "prints a skeleton; takes no role-written record"),
    "manual_evidence.py write-block": ("battery", "B7"),
    "manual_evidence.py export": ("open", "not established by t-1349 (sweep row 23 covers write_block and validate only)"),
    "manual_evidence.py build": ("none", "the record is built by code from saved files; the role passes flags"),
    "manual_evidence.py rejudge": ("none", "the record is copied by code from a written attempt; the role passes flags"),
    "manual_capture.py ui": ("none", "sweep row 24 OK: parse_steps lists every bad line, each with `line N`"),
    "manual_capture.py http": ("none", "sweep row 24 OK: parse_steps lists every bad line, each with `line N`"),
    "manual_capture.py app": ("none", "EP1-41d: the same parse_steps (words=app_steps) lists every bad line, each with `line N`"),
    "artifact_producer.py publish": ("battery", "B11"),
    "artifact_producer.py validate-batch": ("battery", "B11"),
    "manifest_put.py --fragment": ("battery", "B14"),
    "critic_rollcall.py --store": ("none", "a path to the case-version store; no role-written record"),
    "external_writes.py --record": ("open", "not established by t-1349 (sweep row 30 covers the bug side only)"),
    "case_versions.py --pin": ("none", "two values, a case id and a version; no role-written record"),
    "plan_row.py": ("battery", "B10"),
    "execution_fingerprint.py": ("battery", "B4"),
    "context_bundle.py": ("battery", "B1"),
    "red_sandbox.py --diagnostic": ("open", "run_diagnostic refuses the request key by key (first error) and prints the whole form "
                                            "(DIAGNOSTIC_FORM) with every refusal; not a two-defect compound, so no battery row"),
    "work/context-manifest.json": ("battery", "B3"),
    "work/impl-diff.txt": ("none", "a raw diff; no record fields"),
    "work/requirements-register.md": ("none", "sweep row 6 OK: check_register is an accumulator"),
    "work/requirements-readiness.json": ("open", "sweep row 7: readiness_check is a B-gap queued by F-8, not in the battery"),
    "understanding.md": ("none", "sweep row 8 OK: check_understanding is an accumulator"),
    "test-plan.md": ("battery", "B10"),
    "work/test-plan.json": ("battery", "B10"),
    "work/s5-plan.json": ("none", "s5_plan.check_report is an accumulator: every gap of the plan at once, one line each (SC1-14)"),
    "work/grounding.yaml": ("none", "sweep row 11 OK: the check lists every finding, form 1"),
    "work/probe-models/": ("none", "TQ1-25, t-2064 P3/P5: load_models refuses one field at a time but every refusal prints the whole models form (_models_shape_refusal, _models_refusal); a list of small entries, not a compound input"),
    "work/test-cases/critic-findings.md": ("none", "sweep row 14 OK: findings_errors is an accumulator"),
    "work/test-code/critic-findings.md": ("battery", "B14"),
    "work/test-code/critic-findings-*.md": ("battery", "B14"),
    "work/s5-notes/S5-qa-code-critic-*.md": ("none", "free text for the next window; there is nothing to validate"),
    "work/s5-notes/S5-qa-automator-*.md": ("none", "free text for the next window; there is nothing to validate"),
    "work/s5-notes/": ("none", "the folder of those free-text notes; there is nothing to validate"),
    "work/test-cases/": ("none", "sweep row 13 OK: check_case is an accumulator"),
    "work/triage.json": ("battery", "B12"),
    "work/evidence/manual/<case>/tried.md": ("open", "X7-8: no validator on write was found (the recorder's `build` reads it for citations only); the runner is its writer since X7-3"),
    "work/bug-drafts/": ("open", "sweep row 27: no validator on write for a draft's shape was found"),
    "project:bugs/": ("battery", "B11"),
    "test-report.md": ("none", "sweep row 28 OK: check_test_report is an accumulator"),
    "retro.md": ("battery", "B6"),
    "project:obligations.md": ("none", "sweep row 32 OK: add_finding names its three required fields in one sentence"),
    "project:factory-backlog.md": ("none", "sweep row 32 OK: add_finding names its three required fields in one sentence"),    "place_answers.py write": ("none", "answer_problems returns every problem of the answer at once, each with its door (_p), raised through _refuse before anything is written"),
    "first_look.py put": ("none", "first_look.put_problems is an accumulator: every problem of the record at once, each with its door (J-C3); nothing is written while the list is not empty"),
    "reference_snapshot.py put": ("none", "reference_snapshot.put collects every problem of the items file (`problems`) and refuses once with the whole list and each door; nothing is written while it is not empty (PC-9)"),
    "first_look.py show": ("none", "a task root and --json; read-only, no role-written record"),
    "walk_session.py open": ("none", "a walk id, a place and an actor; reopens the dispatch's own session, no role-written record"),
    "walk_session.py item": ("none", "a case id and an actor; no role-written record"),
    "walk_session.py step": ("none", "the same MC.parse_steps as manual_capture: every bad line listed, each with `line N`; a longer batch is refused whole"),
    "walk_session.py look": ("none", "a case id, an actor and a selector; no role-written record"),
    "walk_session.py final": ("none", "a case id and an actor; no role-written record"),
    "walk_session.py verdict": ("none", "verdict_problems and ME.walk_rule_errors return lists: every problem of the verdict at once, while the session lives (t-2016 F2)"),
    "walk_session.py claim": ("open", "thinking-roles TR4-16"),
    "walk_session.py done": ("none", "a walk id; no role-written record"),
    "walk_session.py status": ("none", "a walk id; read-only, no role-written record"),
    "work/place-answers/": ("none", "answer_problems is an accumulator (see place_answers.py write); the scratch file is the same record"),
}
GUARD_KINDS = ("battery", "none", "open")


def guard_problems(keys: list, guard: dict, row_ids: list) -> list:
    """Every census key that has no battery row and no stated reason, and every entry that is malformed, names a missing row
    or names a key that no longer exists. An EMPTY column is a problem of its own: a guard column that holds nothing is not a
    pass."""
    problems = []
    if not guard:
        problems.append("the guard column is empty")
    for key in keys:
        entry = guard.get(key)
        if entry is None:
            problems.append(f"{key}: no battery row and no reason (battery, <row id>) / (none, <reason>) / (open, <pointer>)")
        elif not (isinstance(entry, tuple) and len(entry) == 2 and entry[0] in GUARD_KINDS and entry[1]):
            problems.append(f"{key}: an entry is (kind, value) with kind one of {', '.join(GUARD_KINDS)}")
        elif entry[0] == "battery" and entry[1] not in row_ids:
            problems.append(f"{key}: battery row {entry[1]!r} does not exist")
    problems += [f"{key}: names a command or artifact that no longer exists" for key in guard if key not in keys]
    return problems


def census_keys() -> list:
    commands = json.loads((PLUGIN / "references" / "role-commands.json").read_text(encoding="utf-8"))["commands"]
    artifacts = json.loads((PLUGIN / "references" / "artifact-writers.json").read_text(encoding="utf-8"))["artifacts"]
    role_written = [name for name, entry in artifacts.items() if str(entry.get("writer", "")).endswith("(the role)")]
    return list(commands) + role_written


def entry_problem(key: str, entry, labels: set) -> str:
    """Why a census entry points at nothing (empty string when it points at something real)."""
    if not (isinstance(entry, tuple) and len(entry) == 2 and entry[0] in ENTRY_KINDS and entry[1]):
        return f"{key}: an entry is (kind, pointer) with kind one of {', '.join(ENTRY_KINDS)}"
    kind, pointer = entry
    if kind == "vocab":
        return "" if pointer in labels else f"{key}: vocabulary {pointer!r} is in neither VOCABULARIES nor FIELD_VOCABULARIES"
    if kind == "skeleton":
        word = pointer.split()[-1]
        kinds = artifact_producer.KINDS if word == "<kind>" else (word,)
        if not pointer.startswith("artifact_producer.py prepare "):
            return f"{key}: a skeleton is printed by `artifact_producer.py prepare <kind>`, got {pointer!r}"
        for one in kinds:
            if one not in artifact_producer.KINDS:
                return f"{key}: {one!r} is not an artifact_producer kind ({', '.join(artifact_producer.KINDS)})"
            try:
                artifact_producer.prepare(one)
            except ValueError as exc:
                return f"{key}: prepare {one} refuses: {exc}"
        return ""
    if kind == "file":
        return "" if (PLUGIN / pointer).is_file() else f"{key}: file {pointer} does not exist in the package"
    return ""


def census_checks(row_ids: list) -> None:
    keys = census_keys()
    missing = [k for k in keys if k not in TOLD]
    check("census: every role command and role-written artifact names where the role is told", not missing,
          "no entry for: " + ", ".join(missing))
    labels = {label for _, label, _ in test_ahead_cards.VOCABULARIES} | {label for label, _, _ in field_vocabularies()}
    bad = [p for p in (entry_problem(k, TOLD[k], labels) for k in keys if k in TOLD) if p]
    check("census: every entry points at something that exists", not bad, "; ".join(bad))
    stale = [k for k in TOLD if k not in keys]
    check("census: no entry names a command or artifact that no longer exists", not stale, ", ".join(stale))
    for key in keys:
        if key in TOLD and TOLD[key][0] == "open":
            print(f"OPEN {key} -- {TOLD[key][1]}")
    # the checker itself can fail: a census with a key removed and one with a dangling pointer are both caught
    some = next(k for k in keys if k in TOLD)
    check("census negative control: a key with no entry is named", [k for k in keys if k not in
          {x: TOLD[x] for x in TOLD if x != some}] == [some])
    check("census negative control: a dangling vocabulary pointer is named",
          bool(entry_problem("x", ("vocab", "no such vocabulary"), labels)))
    check("census negative control: a missing file is named", bool(entry_problem("x", ("file", "references/no-such.md"), labels)))
    # part B: every key has a battery row or a stated reason (t-1398 fix 1)
    gaps = guard_problems(keys, GUARDED, row_ids)
    check("census guard: every role command and role-written artifact has a battery row or a reason it has none", not gaps,
          "; ".join(gaps))
    check("census guard: the column is seeded (battery rows and sweep reasons are both present)",
          sum(1 for v in GUARDED.values() if v[0] == "battery") >= 5 and sum(1 for v in GUARDED.values() if v[0] == "none") >= 5)
    for key in keys:
        if key in GUARDED and GUARDED[key][0] == "open":
            print(f"OPEN (battery) {key} -- {GUARDED[key][1]}")
    check("census guard negative control: a key with neither a row nor a reason fails and is named",
          guard_problems(keys + ["new_command.py --x"], GUARDED, row_ids) ==
          ["new_command.py --x: no battery row and no reason (battery, <row id>) / (none, <reason>) / (open, <pointer>)"])
    check("census guard negative control: an empty column fails", bool(guard_problems(keys, {}, row_ids)))
    check("census guard negative control: a battery row that does not exist is named",
          bool(guard_problems(["k"], {"k": ("battery", "B99")}, row_ids)))
    check("census guard negative control: a reason-less entry is named", bool(guard_problems(["k"], {"k": ("none", "")}, row_ids)))


# --- the file ------------------------------------------------------------------------------------------------------------

def main() -> None:
    root = temp_dir("qa-validator-class-")
    try:
        rows = battery(root)
        check("the battery holds the fourteen rows of the spec", [r[0] for r in rows] == [f"B{i}" for i in range(1, 15)])
        for rid, script, call, needles, part in rows:
            ok, text, kind = lists_both(call, needles)
            check(f"battery {rid} ({script}, {part}): two defects, both named with their position, in one answer", ok,
                  f"{kind}: {text[:700]!r}; needles {needles!r}")
            if kind == "raised" and ok:
                check(f"friction {rid}: the multi-problem refusal is classified as validator friction",
                      friction.classify(f"{script}: " + text) == "validator", text[:300])

        # --- the negative control: the battery can fail ---------------------------------------------------------------
        b2 = next(r for r in rows if r[0] == "B2")
        two_bad = [{k: v for k, v in SEARCH.items() if k != "reason"}] * 2

        def first_error(records):
            for i, record in enumerate(records):
                if "reason" not in record:
                    raise ValueError(f"coverage_search[{i}]: missing required fields: reason")

        def no_locator(records):
            return ["coverage_search: missing required fields: reason"] * 2

        def crashes(records):
            return records[0]["reason"]

        def accepts(records):
            return []

        check("negative control: a first-error validator fails the battery",
              not lists_both(lambda: first_error(two_bad), b2[3])[0])
        check("negative control: a validator that lists both problems without locators fails the battery",
              not lists_both(lambda: no_locator(two_bad), b2[3])[0])
        check("negative control: a validator that crashes instead of refusing fails the battery (the type is named)",
              answer(lambda: crashes(two_bad))[0] == "crash:KeyError" and not lists_both(lambda: crashes(two_bad), b2[3])[0])
        check("negative control: a validator that accepts the bad input fails the battery",
              answer(lambda: accepts(two_bad))[0] == "accepted" and not lists_both(lambda: accepts(two_bad), b2[3])[0])
        check("negative control: one needle of two is not enough",
              not lists_both(lambda: ["coverage_search[0]: missing required fields: reason"], b2[3])[0])

        # --- the field pins -------------------------------------------------------------------------------------------
        for label, values, where in field_vocabularies():
            text = told_text(where)
            marker = SECTION_MARKERS.get(label)
            if marker:
                absent = words_absent(values, section_sentence(text, marker))
            else:
                absent = [str(v) for v in values if str(v) not in text]
            check(f"field pin {label}: name where the role is told ({where_text(where)}): absent {absent}", not absent)
        # the section pin can fail: the candidates row without repo, revision and path, while the coverage row still holds
        # `repo`/`revision` and `searched_paths` holds `path`
        card = told_text(("card", "qa-scout"))
        row = "`existing_test_candidates[]` rows: candidate_id, repo, revision, path,"
        check("section pin control: the real card holds the candidates row this control edits", row in card)
        damaged = card.replace(row, "`existing_test_candidates[]` rows: candidate_id,")
        check("section pin negative control: dropping repo, revision, path from the candidates row is caught while the whole-card "
              "substring check stays blind",
              words_absent(context_bundle.V2_REQUIRED["existing_test_candidates"],
                           section_sentence(damaged, "`existing_test_candidates[]` rows:")) == ["repo", "revision", "path"]
              and not [v for v in ("repo", "revision", "path") if v not in damaged])
        print(f"EXCLUDED {EXCLUDED[0]} -- {EXCLUDED[1]}")

        census_checks([r[0] for r in rows])
    finally:
        cleanup(root)
    finish("test_validator_class")


if __name__ == "__main__":
    main()
