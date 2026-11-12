"""Risk, case reuse and publication contracts shared by planning and gates.

Semantic equivalence is a designer/critic decision, never a title similarity score.
This module validates its evidence and prevents unsafe create on incomplete search.
"""
import argparse
import copy
import json
import os
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# `named` is `detector_verdict.named`; the alias is because `variant_errors` has a local set of that name
from detector_verdict import EXIT_UNREADABLE, unreadable_line  # noqa: E402  (the third state of a detector: it could not run, RH1-5)
from detector_verdict import named as named_ids, one_line, one_of  # noqa: E402  (a finding is one physical line in a detector's output)
from person_words import WHOLE_PART, door  # noqa: E402
import contract  # noqa: E402
import grammar as G  # noqa: E402

RISK_FIELDS = ("impact", "likelihood", "confidence", "risk_rationale", "risk_source_refs",
               "risk_policy_revision", "coverage_refs", "unknowns", "verification_depth",
               "required_scenarios", "test_level_rationale", "design_review_required")

DELTA_DISPOSITIONS = {"reuse", "strengthen", "replace_redundant", "gap"}

# Two different closed lists were both called `impact`. A plan row's `impact` is the RISK scale
# of `risk-policy.md` (low · moderate · severe · unknown). The DAMAGE class the row inherits
# verbatim from the register's `impact` column (`config.impact_scale`, the one priority is
# derived from) answers another question and lives in `impact_class`. On TP1-15045 the
# register value was copied into `impact` and every such row came back as "invalid starter
# impact" with nothing in any document naming a correct value.
IMPACT_CLASSES = ("data-loss", "money", "access", "blocked-flow", "degraded", "cosmetic", "none")
RISK_IMPACTS = ("low", "moderate", "severe", "unknown")
VERIFICATION_DEPTHS = ("low", "normal", "critical")
STARTER_LEVELS = ("low", "medium", "high", "unknown")


def _validate_coverage_delta(row):
    """Validate logical-case and executable-instance economics for the revised contract."""
    rid = row.get("id", "<unknown>")
    delta = row.get("coverage_delta")
    if not isinstance(delta, dict):
        return [f"{rid}: coverage_delta required by coverage contract revision"]
    errors = []
    entries = delta.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append(f"{rid}: coverage_delta entries must be nonempty")
        entries = []
    obligation_ids = {ob.get("obligation_id") for ob in row.get("coverage_obligations") or []
                      if isinstance(ob, dict)}
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"{rid}: coverage delta entry must be an object")
            continue
        oid = entry.get("obligation_id")
        if oid not in obligation_ids or oid in seen:
            errors.append(f"{rid}: coverage delta must map each obligation exactly once")
        seen.add(oid)
        if entry.get("disposition") not in DELTA_DISPOSITIONS:
            errors.append(f"{rid}: invalid coverage delta disposition")
        if not entry.get("rationale"):
            errors.append(f"{rid}: coverage delta rationale required")
        if entry.get("disposition") in {"reuse", "strengthen", "replace_redundant"} and not entry.get("existing_case_refs"):
            errors.append(f"{rid}: reuse or repair delta needs existing_case_refs")
        if entry.get("disposition") == "gap" and not entry.get("gap_reason"):
            errors.append(f"{rid}: gap delta needs gap_reason")
    if seen != obligation_ids:
        errors.append(f"{rid}: coverage delta must include every obligation")
    counts = delta.get("counts")
    baseline_kind = delta.get("baseline_kind")
    if baseline_kind not in {"initial", "accepted"}:
        errors.append(f"{rid}: coverage delta baseline_kind must be initial or accepted")
    if baseline_kind == "initial" and not delta.get("initial_scope_rationale"):
        errors.append(f"{rid}: initial coverage baseline needs a scope rationale for Gate A")
    if not isinstance(counts, dict):
        errors.append(f"{rid}: coverage delta counts required")
    else:
        values = {}
        for field in ("logical_cases_before", "logical_cases_after", "executable_instances_before", "executable_instances_after"):
            value = counts.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{rid}: {field} must be a nonnegative integer")
            else:
                values[field] = value
        increased = (values.get("logical_cases_after", 0) > values.get("logical_cases_before", 0) or
                     values.get("executable_instances_after", 0) > values.get("executable_instances_before", 0))
        expansion = delta.get("accepted_scope_expansion_ref")
        if baseline_kind == "accepted" and increased and (not isinstance(expansion, dict) or
                not expansion.get("ref") or not expansion.get("revision")):
            errors.append(f"{rid}: increased cases or instances require accepted scope expansion")
    instance_ids = delta.get("planned_instance_ids")
    if not isinstance(instance_ids, list) or any(not isinstance(value, str) or not value for value in instance_ids):
        errors.append(f"{rid}: planned_instance_ids must be an explicit string array")
    elif len(instance_ids) != len(set(instance_ids)):
        errors.append(f"{rid}: planned instances are counted once even when they prove multiple obligations")
    elif isinstance(counts, dict) and isinstance(counts.get("executable_instances_after"), int) and len(instance_ids) != counts["executable_instances_after"]:
        errors.append(f"{rid}: executable_instances_after must equal unique planned_instance_ids")
    return errors


WALK_DATA_EXAMPLE = '"walk_data": [{"kind": "book", "exclusive": true, "changes": "deletes one book"}], "walk_global": "the Then counts every book"'


def _validate_walk_fields(row):
    """TR3-10 E: the SHAPE of the optional `walk_data` / `walk_global` of ANY plan row that carries them, and nothing else.
    `walk_data`: a list of {kind: non-blank text, exclusive: true|false, changes: text}; `walk_global`: non-blank text. ABSENT
    (and `walk_data: []`) is not said = no constraint, so older plans stay valid. Whether what the strategist wrote is RIGHT is the
    S3 critic's judgment, never this check's (AR-29). Each problem names the row, the field and the right shape (FR-1, FR-38)."""
    rid = row.get("id", "<unknown>")
    errors = []
    if "walk_data" in row:
        if not isinstance(row["walk_data"], list):
            errors.append(f"{rid}: walk_data must be a list of objects, e.g. {WALK_DATA_EXAMPLE}")
        for i, entry in enumerate(row["walk_data"] if isinstance(row["walk_data"], list) else []):
            if not isinstance(entry, dict):
                errors.append(f"{rid}: walk_data[{i}] must be an object {{kind, exclusive, changes}}, e.g. {WALK_DATA_EXAMPLE}")
                continue
            if not isinstance(entry.get("kind"), str) or not entry["kind"].strip():
                errors.append(f"{rid}: walk_data[{i}].kind must be non-blank text naming the kind of record, e.g. \"book\"")
            if not isinstance(entry.get("exclusive"), bool):
                errors.append(f"{rid}: walk_data[{i}].exclusive must be true or false (a JSON boolean, not text), e.g. \"exclusive\": true")
            if not isinstance(entry.get("changes"), str):
                errors.append(f"{rid}: walk_data[{i}].changes must be text saying what the walk does to it, e.g. \"deletes one book\"")
    if "walk_global" in row and (not isinstance(row["walk_global"], str) or not row["walk_global"].strip()):
        errors.append(f"{rid}: walk_global must be non-blank text giving the reason, e.g. \"the Then counts every book\"; "
                      "leave the field out when nothing is global")
    return errors


def _needs_design_review(row) -> bool:
    """The ONE statement of when a row must carry `design_review_required: true` (`validate_plan` and the
    `variant_errors` hint both ask it)."""
    return bool(row.get("verification_depth") == "critical" or row.get("impact") == "unknown"
                or row.get("oracle_unknown") or row.get("source_conflict"))


def validate_plan(rows, require_v2=False):
    errors = []
    if not isinstance(rows, list):
        return ["plan must be an array of behavior rows"]
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("plan rows must be objects")
            continue
        rid = row.get("id", "")
        if not rid or rid in ids:
            errors.append("plan row IDs must be nonempty and unique")
        ids.add(rid)
        for field in RISK_FIELDS:
            if field not in row:
                errors.append(f"{rid}: missing {field}")
        for field in ("risk_rationale", "risk_policy_revision", "test_level_rationale"):
            if not row.get(field):
                errors.append(f"{rid}: empty {field}")
        if row.get("verification_depth") not in VERIFICATION_DEPTHS:
            errors.append(f"{rid}: invalid verification depth (one of {one_of(VERIFICATION_DEPTHS)})")
        if _needs_design_review(row) and row.get("design_review_required") is not True:
            errors.append(f"{rid}: independent design review required")
        for field in ("risk_source_refs", "coverage_refs", "unknowns", "required_scenarios"):
            if not isinstance(row.get(field), list):
                errors.append(f"{rid}: {field} must be an array")
        if not isinstance(row.get("design_review_required"), bool):
            errors.append(f"{rid}: design_review_required must be boolean")
        # Optional so a plan written by 0.7.x still validates; checked when it is there.
        if row.get("impact_class") is not None and str(row.get("impact_class")) not in IMPACT_CLASSES:
            errors.append(f"{rid}: impact_class '{row.get('impact_class')}' is not the register's "
                          f"closed list ({' · '.join(IMPACT_CLASSES)}) — it is inherited from the "
                          "register's `impact` column, never invented here")
        if row.get("risk_policy_revision") == "factory-starter-v1":
            for field, values in (("impact", RISK_IMPACTS),
                                  ("likelihood", STARTER_LEVELS),
                                  ("confidence", STARTER_LEVELS)):
                if row.get(field) not in values:
                    if field == "impact" and str(row.get("impact")) in IMPACT_CLASSES:
                        errors.append(f"{rid}: `impact` is the risk scale "
                                      f"({' · '.join(RISK_IMPACTS)}); '{row.get('impact')}' is the "
                                      "register's damage class and belongs in `impact_class`")
                    else:
                        errors.append(f"{rid}: invalid starter {field} (one of {one_of(values)})")
            if row.get("impact") == "severe" and row.get("verification_depth") != "critical":
                errors.append(f"{rid}: severe impact requires critical depth")
            if row.get("verification_depth") == "low" and not (
                    row.get("impact") == "low" and row.get("likelihood") == "low"
                    and row.get("confidence") == "high" and row.get("bounded_reversible") is True):
                errors.append(f"{rid}: low depth requires evidenced bounded, reversible, low-likelihood effect")
        if row.get("impact") == "unknown" and row.get("verification_depth") == "low":
            errors.append(f"{rid}: unknown impact cannot be low")
        if not row.get("risk_source_refs") or not row.get("required_scenarios"):
            errors.append(f"{rid}: risk sources and required scenarios must be explicit")
        if row.get("baseline_required"):
            if row.get("execution_scope") != "current_task":
                errors.append(f"{rid}: baseline is allowed only for current_task scope")
            # Before provenance may be resolved with the user at the end. An actual
            # capture still requires exact provenance in baseline_contract.py.
            for field in ("case_id", "case_version", "baseline_reason",
                          "verification_revision", "verification_build",
                          "fixture_identity"):
                if not isinstance(row.get(field), str) or not row[field]:
                    errors.append(f"{rid}: baseline_required needs {field}")
            for field in ("capture_steps", "comparison_assertions", "capture_artifact_refs"):
                if not isinstance(row.get(field), list) or not row[field] or any(
                        not isinstance(value, str) or not value for value in row[field]):
                    errors.append(f"{rid}: baseline_required needs nonempty {field}")
        if row.get("coverage_contract_revision") == "coverage-observation-v1":
            errors.extend(_validate_coverage_delta(row))
        errors.extend(_validate_walk_fields(row))      # TR3-10 E: any row that carries the optional fields (the carrier takes every owner row)
    from coverage_contract import validate_obligations
    return errors + validate_obligations(rows, require_v2=require_v2)


# --- what Gate A will require, checked at the S3 exit gate --------------------------------
# TP1-15045: the strategist handed over a plan whose rows carried no
# `coverage_contract_revision`. `controller.py` revalidates the plan when S3 is accepted, but
# only with `require_v2` when the task runs `coverage_contract_version == 2`, and that story
# ran `plan_contract_mode: legacy` - so S3 closed, S4 designed fifteen cases and ran two critic
# rounds, and only then did `controller.py --operation gate-inputs` refuse the plan with one
# opaque `COVERAGE_CONTRACT_REVISION_REQUIRED`. By then the author was three stages away.
# Everything gate-inputs will require is therefore re-run at the S3 exit gate (SubagentStop,
# through the stage's `detectors` entry in references/stages.json), while the strategist still
# has the context to repair its own row - and reported row by row, not as one word.


def stamp_revision(rows, plan_contract_mode="legacy"):
    """The plan rows with the revision mark CODE writes (RN1-2): a copy in which every dict row without a value in
    `coverage_contract_revision` (absent, None, "" or any falsy value) carries `COVERAGE_CONTRACT_REVISION`.

    The predicate is `Controller._coverage_contract_revisions`' own, literally (parity pinned by a test): a row "carries a
    value" when it is not None, and "is unmarked" when `not value`. A `legacy` plan in which no row carries a value stays
    legacy and is returned as it is (builder rule 9); otherwise (any other mode, or one row already marked) every unmarked
    row is stamped, because a mixed set is never silently turned green - the proof it owes (`coverage_delta`) is demanded
    of the stamped row before the role leaves. A row that has a value is never changed; a non-list is returned as it is.
    Pure: the argument is not touched (FR-45) - `project_plan` is the writer."""
    if not isinstance(rows, list):
        return rows
    from coverage_contract import COVERAGE_CONTRACT_REVISION
    dicts = [row for row in rows if isinstance(row, dict)]
    if plan_contract_mode == "legacy" and all(row.get("coverage_contract_revision") is None for row in dicts):
        return rows
    out = copy.deepcopy(rows)
    for row in out:
        if isinstance(row, dict) and not row.get("coverage_contract_revision"):
            row["coverage_contract_revision"] = COVERAGE_CONTRACT_REVISION
    return out


def coverage_revision_errors(rows):
    """A plan row that names a revision other than the one this factory plans against, said per row (RN1-2).

    The mark is written by code (`stamp_revision` at the S3 exit, `project_plan` at S3 completion), so a row that LACKS it is
    no finding of the role's. A present value that is not `COVERAGE_CONTRACT_REVISION` is: a row planned against another
    revision is re-planned, not relabelled. A `schema_version` 2 row has the same finding from `coverage_contract.
    validate_obligations`; `gate_plan_errors` drops that bare line for the rows named here (one fact, one line, and the one
    kept says the expected value). A row that LACKS the mark is not named here: that is `unmarked_revision_errors`."""
    from coverage_contract import COVERAGE_CONTRACT_REVISION as WANT
    out = []
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        value = row.get("coverage_contract_revision")
        if value and value != WANT:
            out.append(f"{row.get('id') or f'row[{index}]'}: coverage_contract_revision is {value!r}; this factory plans against "
                       f"{WANT!r} and writes the mark itself - remove the field from the row (a row planned against another "
                       "revision is re-planned, not relabelled)")
    return out


def unmarked_revision_errors(rows, plan_contract_mode="legacy"):
    """One line per plan row the controller would refuse for a missing revision mark (`COVERAGE_CONTRACT_REVISION_REQUIRED`): the rows
    `stamp_revision` would stamp in this mode (none in a `legacy` plan that carries no mark at all - the controller's own rule). The
    S3 exit never sees these lines (it judges the stamped plan); the gate A rehearsal does, on the FILE: a plan the S3 projection did
    not stamp is named before the person is asked (RN1-2 B-1)."""
    if not isinstance(rows, list) or stamp_revision(rows, plan_contract_mode) is rows:
        return []
    return [f"{row.get('id') or f'row[{index}]'}: missing coverage_contract_revision - gate A's gate-inputs refuses the whole plan "
            "(COVERAGE_CONTRACT_REVISION_REQUIRED) while this row is unmarked; code writes the mark when S3 closes, so the S3 projection "
            "did not run for this plan: the conductor reruns the S3 step (never the role)"
            for index, row in enumerate(rows) if isinstance(row, dict) and not row.get("coverage_contract_revision")]


def gate_plan_errors(rows, plan_contract_mode="legacy", coverage_contract_version=1):
    """Exactly what `controller.py --operation gate-inputs` will require of the plan."""
    errors = validate_plan(rows, require_v2=(coverage_contract_version == 2))
    ours = coverage_revision_errors(rows)
    named = tuple(f"{line.split(':', 1)[0]}: unsupported coverage_contract_revision " for line in ours)
    return [error for error in errors if not error.startswith(named)] + ours + unmarked_revision_errors(rows, plan_contract_mode)


def plan_warnings(rows):
    """Cheap pyramid signal, never a refusal.

    The owner's standing decision of 11.09 is `automate` only for the highest risk. On
    TP1-15045 fourteen of fifteen rows were `automate` and ten of them `e2e-ui`, including
    computed-colour and badge checks - the most brittle tests of the set. A disposition is the
    strategist's judgement and the vocabulary is closed, so this warns and lets the row stand.

    A row's `if_answered` branch can set the same thing (a patch that makes it `automate` at e2e-ui), so
    each row is read a second time with its branches laid over it (GW1-29, `resolve_patch` + `apply_patch`,
    the same condition): a branch does not bring an unearned e2e in silently. At most one such line per
    row; the fields read are the closed ones only (FR-12), no prose.
    """
    warnings = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if _unearned_e2e(row):
            warnings.append(_unearned_e2e_line(row.get("id"), row))
        found = _unearned_branch(row)
        if found:
            warnings.append(_unearned_e2e_line(f"{row.get('id')} ({found[0]} = {found[1]})", found[2]))
    return warnings


def _unearned_e2e(row) -> bool:
    """`automate` at e2e-ui while no closed risk field says highest risk (the one condition of `plan_warnings`)."""
    if row.get("disposition") != "automate" or row.get("level") != "e2e-ui":
        return False
    return not (row.get("impact") in {"severe", "unknown"} or row.get("likelihood") == "high"
                or row.get("verification_depth") == "critical")


def _unearned_e2e_line(label, row) -> str:
    return (f"{label}: `automate` at level e2e-ui without a highest-risk reason "
            f"(impact={row.get('impact')}, likelihood={row.get('likelihood')}, "
            f"depth={row.get('verification_depth')}) — the standing decision is `automate` only "
            "for the highest risk; name the risk that earns it, or move an appearance check "
            "to the plan's developer recommendations as a component-level one")


def _unearned_branch(row):
    """(question id, key, the row with that branch laid over it) of the FIRST `if_answered` branch that makes the row an
    unearned e2e, else None. A branch whose patch is no object gives `resolve_patch` None and is passed over; an `{}`
    patch is not read (its result is the row already checked)."""
    ifa = row.get("if_answered")
    if not isinstance(ifa, dict):
        return None
    for qid, entry in ifa.items():
        if not isinstance(entry, dict):
            continue
        for key in entry:
            patch = resolve_patch(entry, key)
            if not patch:
                continue
            patched = apply_patch(row, patch)
            if _unearned_e2e(patched):
                return str(qid), str(key), patched
    return None


def running_story(root=None, stage_id="S3"):
    """The task directory of the story this stage is running for, or None (fail-open).

    Same rule as `exit_gate._ticket_for_stage`: the most recently touched pipeline.json whose
    entry for this stage is `running`, else the most recently touched one.
    """
    from hooklib import artifact_root
    artifacts = artifact_root(root=Path(root).resolve()) if root else artifact_root()
    if not artifacts.exists():
        return None
    pipelines = sorted(artifacts.glob("*/pipeline.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in pipelines:
        try:
            stages = json.loads(path.read_text(encoding="utf-8")).get("stages")
        except Exception:
            continue
        if isinstance(stages, dict) and (stages.get(stage_id) or {}).get("status") == "running":
            return path.parent
    return pipelines[0].parent if pipelines else None


# The word the exit gate hands a detector it starts (GW1-10): the folder of the story the gate is judging. One name for
# the writer (`exit_gate._detector_env`) and the reader (`detector_story`).
DETECTOR_STORY_ENV = "QA_FACTORY_DETECTOR_STORY"


def detector_story(root=None, stage_id="S3"):
    """The story folder a zero-argument detector judges (GW1-10, AR-13): the one the exit gate NAMED, else the guess.

    `QA_FACTORY_DETECTOR_STORY` set and not blank -> `hooklib.story_root_at` over it (a folder that is not there raises
    `StoryRootError`, which the detector's own `except` turns into `UNREADABLE:`, exit 3: a named story is never swapped
    for another one). Unset -> `running_story(root, stage_id)`, called through this module's global, as before. A detector
    run by hand with no flags honours the variable the same way."""
    if detector_story_named():
        from hooklib import story_root_at
        return story_root_at(os.environ[DETECTOR_STORY_ENV], "detector")
    return running_story(root, stage_id)


def detector_story_named() -> bool:
    """Did the exit gate NAME the story (`QA_FACTORY_DETECTOR_STORY` set and not blank)? The ONE reading of that rule: `detector_story`
    and `branch_accounting._running` both ask here (AR-13), so a blank word is "not named" in both."""
    return bool((os.environ.get(DETECTOR_STORY_ENV) or "").strip())


# The second word the exit gate hands a detector (t-440): the stage the finisher holds (`dispatch["stage"]` at `finish`). Written by
# `exit_gate._detector_env` ONLY beside a named story, read by `detector_stage_named`.
DETECTOR_STAGE_ENV = "QA_FACTORY_DETECTOR_STAGE"


def detector_stage_named() -> str:
    """The stage the exit gate NAMED (stripped), or "" when it named none. "" is "no stage named": the detector then infers as it
    always did. A named stage is a fact the gate holds: it wins over any inference (FR-59, AR-28)."""
    return (os.environ.get(DETECTOR_STAGE_ENV) or "").strip()


# The third word the exit gate hands a detector (TR3-13): the dispatch id of the finisher (`story_step finish` and the driver hold it,
# `exit_gate.holding_dispatch`). Written by `exit_gate._detector_env` ONLY beside a named story; read by `dispatch_identity.named`
# (AR-13: the one reader of "which dispatch am I"), first, before `QA_FACTORY_DRIVER_RUN`.
import dispatch_identity as _dispatch_identity   # noqa: E402

DETECTOR_DISPATCH_ENV = _dispatch_identity.DETECTOR_DISPATCH_ENV   # ONE definition (AR-13), re-exported for `exit_gate._detector_env`


def story_plan_path(task_root):
    """`work/test-plan.json`, or the pre-`work/` spelling a story started on 0.7.4 still uses."""
    for name in ("work/test-plan.json", "test-plan.json"):
        candidate = Path(task_root) / name
        if candidate.is_file():
            return candidate
    return None


def story_contract_mode(task_root):
    """(plan_contract_mode, coverage_contract_version) from the task's controller projection.

    No projection means the story never opted into the coverage contract: read it as `legacy`,
    so the gate re-checks what gate-inputs would and nothing more.
    """
    try:
        state = json.loads((Path(task_root) / "state" / "controller.json").read_text(encoding="utf-8"))
    except Exception:
        return "legacy", 1
    if not isinstance(state, dict):
        return "legacy", 1
    version = state.get("coverage_contract_version")
    return str(state.get("plan_contract_mode") or "legacy"), version if isinstance(version, int) else 1


# --- the contradiction chain: S2's matrix -> S3's rows -------------------------------------
# The register's `## Contradiction matrix` is where S2 records that two sources disagree
# (`contradicts:"<quote>"`). `validate_plan` above already forces an independent design review
# on a row that carries `source_conflict` or `oracle_unknown` — but nothing put those fields on
# a row: they were named in no charter, no phase file and no reference, so a contradiction S2
# recorded simply stopped at S2. The chain is closed here, at the stage that still holds the
# register: every R the matrix contradicts must reach a plan row that says so.

def row_requirements(row) -> list:
    """Every register id a plan row claims, in each spelling the plan has used.

    The reader may err toward FINDING a requirement (a row that names R-n in any of these keys
    covers it) and never invents an id the row does not write. cmp2 (TP1-15045): the plan
    named them `requirement_refs` (strings, or `{ref, revision}` objects as the obligations do)
    and `register:R-n` in `risk_source_refs`, and the S3 exit gate refused "no plan row covers
    R-4" while TS-3 carried `requirement_refs: ["R-4"]`."""
    out: list = []
    if not isinstance(row, dict):
        return out

    def add(text) -> None:
        for part in str(text).replace(",", " ").split():
            part = part.strip().strip("`")
            if part.startswith("R-") and part not in out:
                out.append(part)

    def read(value) -> None:
        if not isinstance(value, (str, dict, list, tuple)):
            return
        for item in ([value] if isinstance(value, (str, dict)) else value):
            add(item.get("ref") if isinstance(item, dict) else item)

    for key in DIRECT_REQUIREMENT_KEYS:
        read(row.get(key))
    sources = row.get("risk_source_refs")
    for ref in sources if isinstance(sources, (list, tuple)) else []:
        text = str(ref).strip()
        if text.startswith(("requirement:", "register:")):
            add(text.split(":", 1)[1])
    # GW1-41 (13877 spelled the link `r_refs` on every row and `coverage_obligations[].requirement_refs` on the manual
    # checks). Read AFTER `risk_source_refs`: the order of first appearances is pinned (test_question_branches).
    # Deliberately NOT read: `if_answered` (a branch nobody has taken is no cover), `observation_contract.oracle_ref` /
    # `oracle` / `oracle_source_ref` (an oracle is not cover), `reason`, `branches`. Junk in a field names nothing and
    # never raises: it must not hide a known refusal.
    read(row.get("r_refs"))
    obligations = row.get("coverage_obligations")
    for obligation in obligations if isinstance(obligations, (list, tuple)) else []:
        if isinstance(obligation, dict):
            read(obligation.get("requirement_refs"))
    return out


DIRECT_REQUIREMENT_KEYS = ("requirements", "requirement_ids", "requirement_refs", "covers", "r", "R")


def _directly_named(row) -> list:
    """The ids a row writes in one of the plain keys (the form `test-plan.md` shows a person), not by a reference."""
    return row_requirements({key: row[key] for key in DIRECT_REQUIREMENT_KEYS if isinstance(row, dict) and key in row})


def _row_counts(row) -> bool:
    """A row counts for the fence only if its `disposition` is one of the contract's closed words."""
    return isinstance(row, dict) and row.get("disposition") in contract.DISPOSITIONS


def requirements_without_row(rows, md_rows, requirement_ids, md_known=True) -> list:
    """[{"id": "R-9", "where": "plan" | "md"}]; pure. A row counts only if its `disposition` is in contract.DISPOSITIONS.

    `where: plan` - no row of `work/test-plan.json` names the id; `where: md` - the JSON names it and the `R` column of
    `test-plan.md` does not (what the person reads and what the delivery trace follows). The id is matched as a WHOLE value
    (`R-09`, `R-90`, `BR-9`, `R-9.` do not close `R-9`). Prose in a closed key is not read (FR-12): a row that says
    `covers: "does not cover R-9"` with a disposition and an md line closes it - an accepted gap, the person sees it in
    the md and the plan's critic closes it. `md_known=False` (no test-plan.md): the md half is silent, the S3 exit refuses
    the missing output by itself (`stages.json` required_outputs). An md with no `## Plan` table (`md_rows == []`): every id is
    `where: md`."""
    named: set = set()
    for row in rows if isinstance(rows, list) else []:
        if _row_counts(row):
            named.update(row_requirements(row))
    in_md: set = set()
    for row in md_rows if isinstance(md_rows, list) else []:
        if isinstance(row, dict):
            in_md.update(row.get("requirements") or [])
    out = []
    for rid in requirement_ids:
        if rid not in named:
            out.append({"id": rid, "where": "plan"})
        elif md_known and rid not in in_md:
            out.append({"id": rid, "where": "md"})
    return out


def requirements_by_reference_only(rows, requirement_ids) -> list:
    """The register ids that rows name only by a reference (`r_refs`, an obligation, `register:R-n`) and in no plain key (F-5).
    One WARN line per plan, not per row."""
    plain: set = set()
    named: set = set()
    for row in rows if isinstance(rows, list) else []:
        if _row_counts(row):
            plain.update(_directly_named(row))
            named.update(row_requirements(row))
    return [rid for rid in requirement_ids if rid in named and rid not in plain]


def _action_dispositions() -> tuple:
    return ("automate", "manual-agent")


def row_tests_it(row) -> bool:
    """Does this plan row's own `disposition` plan a check that is executed (`automate` or `manual-agent`)? The ONE definition of
    "a row that tests it" (AR-13): `candidates_without_row` closes a candidate by it, and the delivery check (`check_delivery.
    grounding_records`) asks it of the rows that name a candidate. `skip`, `manual-human`, `unverifiable`, `not_needed`, a word outside
    the closed list, a row that is no dict: False (the error goes toward the candidate staying listed)."""
    return isinstance(row, dict) and row.get("disposition") in _action_dispositions()


def candidates_without_row(rows, candidates, questions) -> list:
    """The candidate-defect dicts (`contract.candidate_defects`) no row plans a test for (G2-15, N7).

    A candidate is closed by a row that names it (`row_requirements`) and either has `disposition` automate or manual-agent,
    or is `skip` / `unverifiable` and holds, for an OPEN question of `questions` (a branch for a question nobody asks, a
    letter beyond the readings, or a settled question never applies), a reading whose patch sets automate or manual-agent.
    `not_needed` never counts (a dropped check is not a test), `*` does (`resolve_patch`). Questions that could not be read
    ([]): no branch counts - the error goes toward the refusal. `skip` and `manual-human` alone do not close it."""
    import question_register as QR
    known = {str(q.get("id")).strip(): q for q in (questions if isinstance(questions, (list, tuple)) else ())
             if isinstance(q, dict) and isinstance(q.get("id"), str)}
    from branch_accounting import PLAN_EXCLUDING
    action = _action_dispositions()

    def planned(row) -> bool:
        if row_tests_it(row):
            return True
        if row.get("disposition") not in PLAN_EXCLUDING:
            return False
        branches = row.get("if_answered")
        for qid, entry in (branches.items() if isinstance(branches, dict) else ()):
            question = known.get(str(qid).strip())
            if question is None or QR.settled(question):
                continue
            for letter in _letters(question):
                patch = resolve_patch(entry, letter)
                if isinstance(patch, dict) and patch.get("disposition") in action:
                    return True
        return False

    out = []
    for candidate in candidates:
        if not any(_row_counts(row) and candidate["r"] in row_requirements(row) and planned(row)
                   for row in (rows if isinstance(rows, list) else [])):
            out.append(candidate)
    return out


def row_open_questions(row, questions) -> list:
    """Ids of the questions this JSON row rests on and `question_register.settled` does not call settled (A3): named in
    `question_refs`, a key of `if_answered`, or a whole token (`_id_token`) of `reason`, in the register's order. An id the
    register does not hold is not returned (`variant_errors` names it); a row or a field that is no dict / list / str reads as
    "rests on nothing". The ONE reader of "what this row stands on" for the trace and the delivery verdict (AR-13)."""
    import question_register as QR
    if not isinstance(row, dict):
        return []
    named = set()
    refs = row.get("question_refs")
    named.update(str(x).strip() for x in (refs if isinstance(refs, (list, tuple)) else ()) if isinstance(x, str))
    branches = row.get("if_answered")
    named.update(str(k).strip() for k in (branches if isinstance(branches, dict) else ()))
    reason = row.get("reason") if isinstance(row.get("reason"), str) else ""
    out = []
    for question in (questions if isinstance(questions, (list, tuple)) else ()):
        if not isinstance(question, dict) or not isinstance(question.get("id"), str):
            continue
        qid = question["id"].strip()
        if QR.settled(question):
            continue
        if qid in named or (reason and _id_token(qid).search(reason)):
            out.append(qid)
    return out


def open_questions_of_plan_rows(task_root, ts_ids) -> dict:
    """What the plan JSON rows `ts_ids` (the `TS-n` ids the md table names) rest on that is still open, for the trace and the
    delivery verdict (A3); never raises. {"open": [{"id": "Q3", "text": "<question>"}, ...], "unknown": ""}.
    No `work/test-plan.json` (an older story): nothing open, as it always was. The JSON present and unreadable, or the
    register unreadable (`skipped.unreadable_file`) when a row exists: `unknown` says what could not be read and `open`
    stays empty - the caller turns that into a gap, never into a pass (FR-59). A JSON with no row of such an id: nothing."""
    try:
        path = story_plan_path(task_root)
        if path is None:
            return {"open": [], "unknown": ""}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"open": [], "unknown": f"{path.name} is not readable JSON ({type(exc).__name__})"}
        rows = data.get("rows") if isinstance(data, dict) else data
        wanted = {str(t) for t in ts_ids}
        mine = [row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict) and str(row.get("id")) in wanted]
        if not mine:
            return {"open": [], "unknown": ""}
        import question_register as QR
        loaded = QR.load(task_root)
        questions = list(loaded.get("questions") or [])
        if (loaded.get("skipped") or {}).get("unreadable_file") or (loaded.get("problems") and not questions):
            return {"open": [], "unknown": "the question register could not be read"}
        by_id = {str(q.get("id")).strip(): q for q in questions if isinstance(q, dict) and isinstance(q.get("id"), str)}
        seen, found = set(), []
        for row in mine:
            for qid in row_open_questions(row, questions):
                if qid not in seen:
                    seen.add(qid)
                    found.append({"id": qid, "text": " ".join(str(by_id[qid].get("question") or "").split())})
        return {"open": found, "unknown": ""}
    except Exception as exc:  # noqa: BLE001
        return {"open": [], "unknown": f"the plan's open questions could not be read ({type(exc).__name__})"}


def _has_branch(row, qid, question) -> bool:
    """Does the row hold a NON-EMPTY patch for some reading letter of the question? (`not_needed` is no executor; `{}` is
    nothing: the answer changes nothing.) The one reading is `resolve_patch`."""
    branches = row.get("if_answered") if isinstance(row, dict) else None
    entry = branches.get(qid) if isinstance(branches, dict) else None
    return any(resolve_patch(entry, letter) for letter in _letters(question))


def _question_text(question) -> str:
    return " ".join(str(question.get(key) or "") for key in ("question", "source_says")) if isinstance(question, dict) else ""


def question_names_requirement(question) -> bool:
    """True when the question names a register id (`R-n`) as a whole token in `question` / `source_says`: A6's selection
    of "a question about a requirement" (the gate card reads it too, t-604 F-3)."""
    return bool(contract.REQ_ID_RE.search(_question_text(question)))


def requirements_waiting_without_branch(rows, questions, requirement_ids) -> list:
    """[{id, question}] (A6): an OPEN question names the register id (whole token in `question` / `source_says`), the rows of
    that id exist and are ALL `skip` / `unverifiable`, and none of them has a non-empty branch for a reading of that question.
    The S3 exit refuses these (no case exists on such a row, so there is no warning stage for it); one entry per (id, question)."""
    import question_register as QR
    from branch_accounting import PLAN_EXCLUDING
    out = []
    for qquestion in (questions if isinstance(questions, (list, tuple)) else ()):
        if not isinstance(qquestion, dict) or not isinstance(qquestion.get("id"), str):
            continue
        qid = qquestion["id"].strip()
        if QR.settled(qquestion) or qquestion.get("status") == QR.DEFERRED:
            continue
        text = _question_text(qquestion)
        for rid in requirement_ids:
            if not _id_token(rid).search(text):
                continue
            mine = [row for row in (rows if isinstance(rows, list) else []) if _row_counts(row) and rid in row_requirements(row)]
            if not mine or any(row.get("disposition") not in PLAN_EXCLUDING for row in mine):
                continue
            if any(_has_branch(row, qid, qquestion) for row in mine):
                continue
            out.append({"id": rid, "question": qid})
    return out


# --- the grounding step: three plan references, the thresholds, the table's ONE reader -------------------

# A plan row names what it answers in `risk_source_refs`: a risk of the grounding table (K-n), a blast area
# (B-n), a refactoring row (G-n). `row_requirements` does not read these prefixes. A string that does not
# match is NOT a reference - the row keeps a free-text entry and the gate counts the K/B undelivered
# (the safe side). `derived_risk` stays a KIND of requirement; there is no `derived_risk:` prefix.
GROUNDING_REF_RE = re.compile(r"^(grounding:K|blast:B|refactoring:G)-[1-9][0-9]*$")
GROUNDING_FILE = "work/grounding.yaml"
GROUNDING_SCHEMA_VERSION = 1
# The top-level keys a grounding table may hold (t-988 section L-2.K + L-3 + L-4, t-1046 F-9B). The reader
# refuses a key outside this tuple, naming it; it never judges what is inside a key.
GROUNDING_KEYS = ("schema_version", "implementation_source", "null_outcome", "diff", "hunks", "rows",
                  "requirements", "refactoring_share", "requirement_coverage", "blast_radius", "claims",
                  "base_slice", "orphans", "register_sha256")
GROUNDING_POLICY_FILE = "grounding-policy.json"
GROUNDING_MEASURE = "changed_production_lines"
_GROUNDING_PERCENTS = ("notify_above_percent", "stop_above_percent", "coverage_stop_below_percent")


def grounding_refs(row) -> dict:
    """`{"K": [...], "B": [...], "G": [...]}` - the ids (`K-1`, `B-2`, `G-3`) a plan row's `risk_source_refs`
    names with a grounding reference, in the row's order, each once. An entry is a reference only when the
    whole entry, after one `strip()` and one pair of backticks off, matches GROUNDING_REF_RE (`grounding:K-0`,
    `grounding:k-1`, `blast:B-`, `blast:B-1x`, two refs in one string: not references). A row that is not a
    dict, or whose `risk_source_refs` is not a list, names none."""
    out: dict = {"K": [], "B": [], "G": []}
    refs = row.get("risk_source_refs") if isinstance(row, dict) else None
    if not isinstance(refs, (list, tuple)):
        return out
    for ref in refs:
        if not isinstance(ref, str):
            continue
        text = ref.strip().strip("`")
        if GROUNDING_REF_RE.match(text):
            ident = text.split(":", 1)[1]
            if ident not in out[ident[0]]:
                out[ident[0]].append(ident)
    return out


def _area_number(ident) -> int:
    found = re.fullmatch(r"B-(\d+)", str(ident).strip())
    return int(found.group(1)) if found else 10 ** 9


def regression_from_blast(doc) -> list:
    """`[{area, command | gap, why}]`: the regression the blast radius of the grounding table asks for - the ONE code that derives it (R7
    reads it, and the strategist's lines of G2-2 will). `doc` is the table (a mapping) or the `Doc` `read_grounding` returns. For each
    area whose `regression` is filled, by the NUMBER of its `B-n` (`B-10` after `B-2`): a command -> `{area, command, why}`; `gap:<reason>`
    -> `{area, gap, why}`; areas with the same command are one entry (`area` lists them, `why` joins their distinct reasons). `why` is the
    area's own, else "shared path, no reason written". An area with nothing in `regression` gives no entry; nothing is written anywhere."""
    data = getattr(doc, "data", doc)
    blast = data.get("blast_radius") if isinstance(data, dict) else None
    areas = blast.get("areas") if isinstance(blast, dict) else None
    out: list = []
    by_command: dict = {}
    for area in sorted([a for a in areas if isinstance(a, dict)] if isinstance(areas, list) else [], key=lambda a: _area_number(a.get("id"))):
        regression = str(area.get("regression") or "").strip()
        if not regression:
            continue
        why = str(area.get("why") or "").strip() or "shared path, no reason written"
        gap = regression[len("gap:"):].strip() if regression.lower().startswith("gap:") else None
        key = ("gap", gap, str(area.get("id"))) if gap is not None else ("command", regression)   # only equal COMMANDS merge
        entry = by_command.get(key)
        if entry is None:
            entry = {"area": str(area.get("id")), key[0]: key[1], "why": why}   # `command` or `gap`, never both
            by_command[key] = entry
            out.append(entry)
        else:
            entry["area"] += f", {area.get('id')}"
            if why not in entry["why"].split("; "):
                entry["why"] += f"; {why}"
    return out


def grounding_policy(path=None) -> tuple:
    """`(policy, "")`, or `(None, why)` - the thresholds of `references/grounding-policy.json`. ONE reader (the
    caller of a `None` writes `road: unknown`, a line for the conductor, never a stop card and never `none`).
    `None` when the file is absent, is not a JSON object, `measure` is not `changed_production_lines`, a
    percent (`notify_above_percent`, `stop_above_percent`, `coverage_stop_below_percent`) is missing or is not a
    whole number 0..100 (a float, a boolean and a string are not), `notify_above_percent` is not below
    `stop_above_percent`, or `numerator_labels` is empty / not a list of strings / holds a word outside
    `vocabulary.grounding_labels`. Every problem names the file, the key and what was expected."""
    from hooklib import read_json
    import handoff
    target = Path(path) if path else Path(__file__).resolve().parents[1] / "references" / GROUNDING_POLICY_FILE
    name = f"references/{target.name}"
    if not target.is_file():
        return None, f"{name} cannot be found, so no threshold can be read"
    doc = read_json(target, None, kind=dict)
    if doc is None:
        return None, f"{name} is not a JSON object (empty, broken or not UTF-8 text)"
    if doc.get("measure") != GROUNDING_MEASURE:
        return None, f"{name}: `measure` is {doc.get('measure')!r}, expected {GROUNDING_MEASURE!r}"
    for key in _GROUNDING_PERCENTS:
        value = doc.get(key)
        if type(value) is not int or not 0 <= value <= 100:
            return None, f"{name}: `{key}` is {value!r}, expected a whole number 0..100 (no float, boolean or string)"
    if doc["notify_above_percent"] >= doc["stop_above_percent"]:
        return None, (f"{name}: `notify_above_percent` ({doc['notify_above_percent']}) must be below "
                      f"`stop_above_percent` ({doc['stop_above_percent']})")
    labels = doc.get("numerator_labels")
    allowed = list(handoff.vocabulary().get("grounding_labels") or [])
    if not isinstance(labels, list) or not labels or not all(isinstance(w, str) for w in labels):
        return None, f"{name}: `numerator_labels` must be a non-empty list of label words, one of {allowed}"
    outside = [w for w in labels if w not in allowed]
    if outside:
        return None, f"{name}: `numerator_labels` holds {outside}, which are not in vocabulary.grounding_labels {allowed}"
    return doc, ""


# What a refusal of `read_grounding` is, by KIND, and who acts on it (t-1046 section 9.2, R0 routing): the DRIVER owns the
# file's presence and the shape of the whole (no file, no key at all, not a mapping); the ROLE that wrote the text rewrites
# it (bytes, control characters, a line the parser cannot read, a key written twice); the CONDUCTOR decides on a form this
# build does not know (another `schema_version`, a key outside the table). Consumers route on `.kind` / `.who`, never on the text.
GROUNDING_PROBLEM_WHO = {"missing": "driver", "empty": "driver", "not_a_mapping": "driver",
                         "encoding": "role", "control_char": "role", "syntax": "role", "duplicate_key": "role",
                         "schema_version": "conductor", "unknown_key": "conductor"}
# Every character a line-oriented reader would split on or choke on, except the line feed and the tab: the C0 and C1 controls
# (NUL, CR, VT, FF, U+0085 ...), U+2028 and U+2029. `handoff.parse` breaks lines with `str.splitlines`, which splits on all of
# them, so a literal one silently cuts a value in two; an escaped one inside quotes (backslash, u, 2028) is text and stays legal.
_GROUNDING_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f" + chr(0x2028) + chr(0x2029) + "]")
_GROUNDING_TAB_INDENT = re.compile(r"^ *\t[ \t]*\S", re.M)


class GroundingProblem(str):
    """One refusal of `read_grounding`: a plain `str` (the FR-1 sentence a person reads, so `(Doc | None, problem)` keeps its
    shape and `if problem:` still works) that carries the typed record `{kind, who, text}`. `kind` is a key of
    GROUNDING_PROBLEM_WHO; `who` is derived from it, never passed."""

    def __new__(cls, kind: str, text: str):
        self = super().__new__(cls, text)
        self.kind, self.who = kind, GROUNDING_PROBLEM_WHO[kind]
        return self

    @property
    def text(self) -> str:
        return str.__str__(self)


def _grounding_text_problem(text: str):
    """The refusal of a file by its characters alone, before any parse: a byte-order mark, a control character (the
    character and its line are named), a tab in an indentation (YAML forbids it), no content line at all, or a
    top-level list. None when the text may be parsed."""
    if text.startswith(chr(0xFEFF)):
        return GroundingProblem("encoding", f"{GROUNDING_FILE} starts with a byte-order mark; write it as plain UTF-8 without one")
    found = _GROUNDING_CONTROL.search(text)
    if found:
        line = text.count("\n", 0, found.start()) + 1
        return GroundingProblem("control_char", f"{GROUNDING_FILE} line {line} holds the control character "
                                f"U+{ord(found.group()):04X}; end lines with a line feed only and write a special character "
                                f"as an escape inside quotes")
    tab = _GROUNDING_TAB_INDENT.search(text)
    if tab:
        line = text.count("\n", 0, tab.start()) + 1
        return GroundingProblem("syntax", f"{GROUNDING_FILE} line {line} is indented with a tab; indent with spaces")
    content = [line.strip() for line in text.split("\n") if line.strip() and not line.strip().startswith("#")]
    if not content or content == ["{}"]:
        return GroundingProblem("empty", f"{GROUNDING_FILE} is empty (it holds no key at all)")
    if content[0] == "-" or content[0].startswith(("- ", "[")):
        return GroundingProblem("not_a_mapping", f"{GROUNDING_FILE} is a list at the top; the table is a mapping of keys "
                                f"(expected `schema_version: 1` first)")
    return None


def _scalar_flaw(text: str):
    """`(kind, why)` when a scalar, as the parser reads it, is not whole - an unclosed quote or bracket, a closer that matches
    nothing, text after the closing quote or bracket (`syntax`), a key written twice in one flow map (`duplicate_key`) - else None. Only a scalar that starts with a quote or a flow opener is judged (a plain
    one is never flawed), and a quote opens only after a start, `[`, `{`, `,` or `:` (an apostrophe inside prose is text)."""
    t = text.strip()
    flow = t[:1] in ("[", "{")
    if not flow and t[:1] not in ("'", '"'):
        return None
    # `stack` holds (closer, keys-of-this-flow-map or None); a flow map's key is the token before its first `:`
    stack, quote, prev, end, i, token = [], "", "", -1, 0, ""
    while i < len(t):
        ch = t[i]
        if quote:
            token += ch
            if ch == "\\" and quote == '"':
                i += 1
            elif ch == quote and quote == "'" and t[i + 1:i + 2] == "'":
                i += 1
            elif ch == quote:
                quote = ""
                end = i if (i > 0 and end < 0 and not flow) else end
        elif ch in ("'", '"') and prev in ("", "[", "{", ",", ":"):
            quote, token = ch, token + ch
        elif flow and ch in ("[", "{"):
            stack.append(("]", None) if ch == "[" else ("}", {"keys": set(), "value": False}))
            token = ""
        elif flow and ch in ("]", "}"):
            if not stack or stack.pop()[0] != ch:
                return "syntax", f"a `{ch}` that closes nothing"
            end = i if (not stack and end < 0) else end
            token = ""
        elif flow and ch == "," and stack:
            if stack[-1][1]:
                stack[-1][1]["value"] = False
            token = ""
        elif flow and ch == ":" and stack and stack[-1][1] and not stack[-1][1]["value"]:
            key = token.strip().strip("'\"")
            if key in stack[-1][1]["keys"]:
                return "duplicate_key", f"the key `{key}` is written twice in one flow map"
            stack[-1][1]["keys"].add(key)
            stack[-1][1]["value"] = True
            token = ""
        else:
            token += ch
        if not ch.isspace():
            prev = ch
        i += 1
    if quote:
        return "syntax", "a quote is never closed"
    if stack:
        return "syntax", "a bracket is never closed"
    if end >= 0 and t[end + 1:].strip():
        return "syntax", "text follows the closing quote or bracket"
    return None


def _grounding_scalar_problem(doc, i, end, first):
    """The refusal of the scalar that starts on line index `i` (`first` is the text after its key or dash) and ends on line
    index `end` (the Doc's own node says where), or None when it is whole."""
    import handoff
    text = handoff._strip_comment(first)[0]
    for k in range(i + 1, end + 1):
        text = f"{text} {doc.lines[k].strip()}".strip()
    flaw = _scalar_flaw(text)
    if flaw:
        return GroundingProblem(flaw[0], f"{GROUNDING_FILE} line {i + 1}: {flaw[1]} (the value reads `{text[:60]}`)")
    return None


def _grounding_shape_problem(doc):
    """The refusal of a parsed table by its SHAPE, or None: a duplicate key at ANY depth (the parser keeps the last one
    silently), and any line the parser dropped without a word (a line that is no `key: value`, no `- item`, no comment, or
    sits where its container cannot take it). It mirrors the container discipline of `handoff.parse` line by line (which
    stays untouched, other contracts read through it) and reads no value; a scalar's extent comes from the Doc's own nodes.
    Each scope is `[indent, kind, keys, path, items]`."""
    import handoff
    lines, nodes = doc.lines, doc.nodes
    stack = [[-1, "map", set(), "", 0]]
    i = 0
    while i < len(lines):
        raw = lines[i]
        body = raw.strip()
        if not body or body.startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip())
        item = handoff.ITEM_LINE.match(raw)
        while len(stack) > 1 and indent <= stack[-1][0] and not (item and indent == stack[-1][0] and stack[-1][1] == "list"):
            stack.pop()
        scope = stack[-1]
        if item and scope[1] == "list":
            row_path = f"{scope[3]}[{scope[4]}]"
            scope[4] += 1
            found = handoff.KEY_LINE.match("  " + item.group(2))
            if not found:
                node = nodes.get(row_path)
                end = node.end_line if node else i
                flaw = _grounding_scalar_problem(doc, i, end, item.group(2))
                if flaw:
                    return flaw
                i = end + 1
                continue
            scope = [indent, "map", set(), row_path, 0]
            stack.append(scope)
            raw_key, value, key_indent = found.group(3), found.group(4) or "", indent + 2
        else:
            found = handoff.KEY_LINE.match(raw)
            if not found or scope[1] != "map" or found.group(2):
                return GroundingProblem("syntax", f"{GROUNDING_FILE} line {i + 1} cannot be read as a `key: value` line, a "
                                        f"`- item` line or a comment here: `{body[:60]}`")
            raw_key, value, key_indent = found.group(3), found.group(4) or "", indent
        key = raw_key[1:-1] if raw_key[0] in "'\"" else raw_key
        if key in scope[2]:
            where = f"`{scope[3]}`" if scope[3] else "the top level"
            return GroundingProblem("duplicate_key", f"{GROUNDING_FILE} line {i + 1} writes the key `{key}` twice in {where}; "
                                    f"only one copy can be kept")
        scope[2].add(key)
        path = f"{scope[3]}.{key}" if scope[3] else key
        value = value.strip()
        if re.match(r"^[|>][+-]?\s*(#.*)?$", value):
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > key_indent):
                j += 1
            i = j
        elif value == "" or value.startswith("#"):
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("#")):
                j += 1
            as_list = (j < len(lines) and handoff.ITEM_LINE.match(lines[j])
                       and len(lines[j]) - len(lines[j].lstrip()) >= key_indent)
            stack.append([key_indent, "list" if as_list else "map", set(), path, 0])
            i += 1
        else:
            node = nodes.get(path)
            end = node.end_line if node and node.line == i else i
            flaw = _grounding_scalar_problem(doc, i, end, value)
            if flaw:
                return flaw
            i = end + 1
    return None


def read_grounding(task) -> tuple:
    """`(Doc, "")` or `(None, problem)` - THE reader of `work/grounding.yaml` (the path is the artifact registry's,
    `contract.artifact_write_path`); no other module parses that file, and nothing partial is ever returned. The Doc is
    `handoff.Doc`: the parsed `data`, the source `lines` and a `nodes` entry (value, `.comment`, line) per SCALAR.
    Scalars are typed only for whole numbers, booleans and null (`400` is an int, `007` the int 7, `"007"` a string,
    `true` a bool); a float stays a STRING (`30.1` is `'30.1'`: a consumer that wants the number parses it, and a writer that
    wants the text quotes it). A row written as a flow map (`- {id: G-1, ...}`) is ONE node: its members carry no comment
    and no line of their own.

    `problem` is a `GroundingProblem` (a `str` with `.kind` and `.who`; GROUNDING_PROBLEM_WHO) for: `missing` - no file
    (an ABSENT table is not an EMPTY one), a path that is not a file, a file that cannot be read; `empty` - no key at all (0
    bytes, comments, `{}`); `not_a_mapping` - a list at the top; `encoding` - bytes that are not UTF-8, or a byte-order
    mark; `control_char` - a literal NUL / CR (CRLF) / VT / FF / U+0085 / U+2028 / U+2029 or any other control character;
    `syntax` - a tab in an indentation, or a line that is no `key: value`, no `- item` and no comment (named by line);
    `duplicate_key` - a key written twice in one mapping, at any depth; `schema_version` - none, or not exactly the whole number
    1 (`"1"`, `1.0`, `true` are not - the form is never guessed); `unknown_key` - a top-level key outside GROUNDING_KEYS
    (named). The CONTENT of a key is not judged here (the table's check does)."""
    import contract
    import handoff
    path = contract.artifact_write_path(Path(task), "grounding.yaml")
    if not path.is_file():
        what = "is not a file" if path.exists() else "does not exist (no table was written for this story)"
        return None, GroundingProblem("missing", f"{GROUNDING_FILE} {what}")
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        return None, GroundingProblem("missing", f"{GROUNDING_FILE} cannot be read ({type(exc).__name__})")
    except UnicodeDecodeError as exc:
        return None, GroundingProblem("encoding", f"{GROUNDING_FILE} is not UTF-8 text (byte {exc.start}); write it as UTF-8")
    problem = _grounding_text_problem(text)
    if problem:
        return None, problem
    doc = handoff.parse(text)
    problem = _grounding_shape_problem(doc)
    if problem:
        return None, problem
    if "schema_version" not in doc.data:
        return None, GroundingProblem("schema_version", f"{GROUNDING_FILE} has no `schema_version`; this build reads "
                                      f"schema_version {GROUNDING_SCHEMA_VERSION}")
    version = doc.data["schema_version"]
    if type(version) is not int or version != GROUNDING_SCHEMA_VERSION:
        return None, GroundingProblem("schema_version", f"{GROUNDING_FILE} has `schema_version` {version!r}; this build "
                                      f"reads only the whole number {GROUNDING_SCHEMA_VERSION} and does not guess a form")
    unknown = [key for key in doc.data if key not in GROUNDING_KEYS]
    if unknown:
        return None, GroundingProblem("unknown_key", f"{GROUNDING_FILE} holds the key `{unknown[0]}`, which is not a key of "
                                      f"the table (expected one of {', '.join(GROUNDING_KEYS)})")
    return doc, ""


# --- the lines of every list element of the table (SC1-3: a section is read by its lines, then changed by Edit) -----------

_GROUNDING_PATH_TOKEN = re.compile(r"\[(\d+)\]|\.?([^.\[\]]+)")
_GROUNDING_BLOCK_SCALAR = re.compile(r"^[|>][+-]?\s*(#.*)?$")
_NO_VALUE = object()


def _grounding_value(data, path: str):
    """The value `path` (`rows[3].risks[0]`, as `Doc.nodes` writes it) names in `data`, or `_NO_VALUE` when `data` has no such place."""
    current = data
    for index, key in _GROUNDING_PATH_TOKEN.findall(path):
        try:
            current = current[int(index)] if index != "" else current[key]
        except (KeyError, IndexError, TypeError):
            return _NO_VALUE
    return current


def _grounding_same(got, want) -> bool:
    """`got` is `want`, with ONE allowance: a text may differ in its trailing line feeds. The Doc takes the blank lines that follow a
    block scalar into its text (`end_line`), and a span does not end on a blank line, so the same element reads back without them."""
    if isinstance(got, str) and isinstance(want, str):
        return got.rstrip("\n") == want.rstrip("\n")
    if isinstance(got, dict) and isinstance(want, dict):
        return got.keys() == want.keys() and all(_grounding_same(got[k], want[k]) for k in got)
    if isinstance(got, list) and isinstance(want, list):
        return len(got) == len(want) and all(_grounding_same(a, b) for a, b in zip(got, want))
    return type(got) is type(want) and got == want


def _indent_of(text: str) -> int:
    return len(text) - len(text.lstrip())


class _GroundingWalk:
    """The container walk over the lines of the grounding table: which line opens which list element (`found`: `(path, index of the
    first line, indent, is a top-level key)`) and which lines continue a scalar (`inside`: a block scalar, a wrapped value - never
    trimmed as a comment). `stack` holds `[indent, kind, path, number of items so far]`. The walk only places the first line of each
    element; where an element ends, and whether the span is right, are decided after it (`_grounding_span_end`, `_grounding_span_gives_back`)."""

    def __init__(self, lines: list, nodes: dict):
        import handoff
        self.handoff, self.lines, self.nodes = handoff, lines, nodes
        self.inside = [False] * len(lines)
        self.found = []
        self.stack = [[-1, "map", "", 0]]

    def run(self) -> tuple:
        i = 0
        while i < len(self.lines):
            body = self.lines[i].strip()
            i = i + 1 if not body or body.startswith("#") else self.line(i)
        return self.found, self.inside

    def cover(self, first: int, last: int) -> None:
        for k in range(first, min(last, len(self.lines) - 1) + 1):
            self.inside[k] = True

    def node_end(self, path: str, i: int, starts_here: bool) -> int:
        """The line after the node at `path` that starts on line `i` (the next line when it has none); its later lines continue it."""
        node = self.nodes.get(path)
        ok = node and (node.line == i if starts_here else node.end_line >= i)
        end = node.end_line if ok else i
        self.cover(i + 1, end)
        return end + 1

    def line(self, i: int) -> int:
        """Place line `i`; the index of the next line to look at."""
        raw, indent = self.lines[i], _indent_of(self.lines[i])
        item, stack = self.handoff.ITEM_LINE.match(raw), self.stack
        while len(stack) > 1 and indent <= stack[-1][0] and not (item and indent == stack[-1][0] and stack[-1][1] == "list"):
            stack.pop()
        scope = stack[-1]
        if item and scope[1] == "list":
            return self.list_item(i, item, scope, indent)
        member = self.handoff.KEY_LINE.match(raw)
        if not member or scope[1] != "map" or member.group(2):
            return i + 1                                          # a line this walk cannot place: the reader refuses such a file
        return self.key(i, scope, member.group(3), member.group(4) or "", indent)

    def list_item(self, i: int, item, scope: list, indent: int) -> int:
        path = f"{scope[2]}[{scope[3]}]"
        scope[3] += 1
        self.found.append((path, i, indent, False))
        member = self.handoff.KEY_LINE.match("  " + item.group(2))
        if not member:                                            # a scalar item, or a flow map: ONE node
            return self.node_end(path, i, False)
        scope = [indent, "map", path, 0]
        self.stack.append(scope)
        return self.key(i, scope, member.group(3), member.group(4) or "", indent + 2)

    def key(self, i: int, scope: list, raw_key: str, value: str, key_indent: int) -> int:
        key = raw_key[1:-1] if raw_key[0] in "'\"" else raw_key
        path = f"{scope[2]}.{key}" if scope[2] else key
        if not scope[2]:
            self.found.append((path, i, _indent_of(self.lines[i]), True))
        value = value.strip()
        if _GROUNDING_BLOCK_SCALAR.match(value):
            return self.block_end(i, key_indent)
        if value == "" or value.startswith("#"):
            return self.open_container(i, path, key_indent)
        return self.node_end(path, i, True)

    def block_end(self, i: int, key_indent: int) -> int:
        lines, j = self.lines, i + 1
        while j < len(lines) and (not lines[j].strip() or _indent_of(lines[j]) > key_indent):
            j += 1
        self.cover(i + 1, j - 1)
        return j

    def open_container(self, i: int, path: str, key_indent: int) -> int:
        lines, j = self.lines, i + 1
        while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("#")):
            j += 1
        as_list = j < len(lines) and self.handoff.ITEM_LINE.match(lines[j]) and _indent_of(lines[j]) >= key_indent
        self.stack.append([key_indent, "list" if as_list else "map", path, 0])
        return i + 1


def _grounding_walk(lines: list, nodes: dict) -> tuple:
    """`(found, inside)` of `_GroundingWalk`."""
    return _GroundingWalk(lines, nodes).run()


def _grounding_span_end(lines: list, first: int, indent: int, top: bool, inside: list) -> int:
    """The index of the last line of the element that opens on line `first`: up to the first line that leaves it (a top-level key
    owns its zero-indent items), less the blank lines and the comments (outside a scalar) that trail it."""
    import handoff
    stop = first + 1
    while stop < len(lines):
        text = lines[stop]
        if text.strip() and not text.strip().startswith("#"):
            at = _indent_of(text)
            leaves = at < indent or (at == indent and not handoff.ITEM_LINE.match(text))
            if leaves if top else at <= indent:
                break
        stop += 1
    last = stop - 1
    while last > first and (not lines[last].strip() or (lines[last].strip().startswith("#") and not inside[last])):
        last -= 1
    return last


def _grounding_span_gives_back(doc, path: str, first: int, last: int, top: bool) -> bool:
    """M-2: the lines `first..last`, put under a key and parsed again, give back exactly `doc.data`'s element at `path`."""
    import handoff
    body = "\n".join(doc.lines[first:last + 1])
    if top:
        expected = {path: doc.data[path]} if path in doc.data else _NO_VALUE
        got = handoff.parse(body).data
    else:
        value = _grounding_value(doc.data, path)
        expected = [value] if value is not _NO_VALUE else _NO_VALUE
        got = handoff.parse("x:\n" + body).data.get("x")
    return expected is not _NO_VALUE and _grounding_same(got, expected)


def grounding_item_lines(doc) -> dict:
    """`{path: (first, last)}` - the LINES of the table's `Doc` that hold each list element (`rows[3]`, `requirements[0]`,
    `blast_radius.areas[5]`, `claims[1]`, `hunks[12]`, `orphans[0]`, `diff[0]`, a nested `rows[3].risks[0]`, a scalar item
    `rows[3].hunks[0]`) and each top-level key (`rows`, under its own name). Line numbers are 1-based and inclusive (the number
    `Read offset` takes). `first` is the element's `- ` line (also when its first key is a block list with no node of its own);
    `last` is its last line that is not blank (a block scalar's trailing blank lines are not the element's) and not a comment
    outside a scalar (a comment between two elements belongs to neither). A flow map is the line(s) of its one node.

    The function reads only `doc.lines` and `doc.nodes`; the container discipline is the one `_grounding_shape_problem` mirrors
    from `handoff.parse`. The error direction is "no span": every span is checked against the element it names - its lines, put
    under a key and parsed again, must give back exactly `doc.data`'s element - and an element that does not pass is LEFT OUT
    (a span that points at other bytes is worse than none: the role reads and then edits exactly those lines). A table the
    walk cannot place line by line gets fewer paths, never a wrong one."""
    found, inside = _grounding_walk(doc.lines, doc.nodes)
    out: dict = {}
    for path, first, indent, top in found:
        last = _grounding_span_end(doc.lines, first, indent, top, inside)
        if _grounding_span_gives_back(doc, path, first, last, top):
            out[path] = (first + 1, last + 1)
    return out


def register_contradictions(register_text: str) -> dict:
    """`{R-n: "<the quote the matrix recorded>"}` from `## Contradiction matrix`."""
    import grammar as G
    out: dict = {}
    for cells in G.table_rows((register_text or "").splitlines(), "## Contradiction matrix"):
        if not cells or not G.REQ_ID_RE.match(cells[0]):
            continue
        for cell in cells[1:]:
            if str(cell).strip().startswith("contradicts:"):
                out.setdefault(cells[0], " ".join(str(cell).split())[:200])
    return out


def register_contradiction_cells(register_text: str) -> list:
    """`[(R-n, column, quote)]`: every cell of `## Contradiction matrix` that STARTS with `contradicts:` (exactly, as
    `register_contradictions` reads it), with the header of the column it stands in. `column` is `""` when the row has another
    cell count than the header (a `|` in the quote): the column is then not known and no origin is taken from it. The one reader
    of WHICH column a contradiction was recorded in (AR-13); a caller asks `matrix_origin(column)` for its origin. Never raises."""
    import grammar as G
    header = _section_header(register_text, "## Contradiction matrix")
    out: list = []
    for cells in G.table_rows((register_text or "").splitlines(), "## Contradiction matrix"):
        if not cells or not G.REQ_ID_RE.match(cells[0]):
            continue
        aligned = len(cells) == len(header)
        for index, cell in enumerate(cells[1:], start=1):
            if str(cell).strip().startswith("contradicts:"):
                out.append((cells[0], header[index] if aligned else "", " ".join(str(cell).split())[:200]))
    return out


# A matrix column names the source the requirement was compared against; that name is where
# the second reading comes from, so it is mapped to `contract.READING_ORIGINS` rather than
# printed raw. On TP1-15045 the matrix scored R-4 against the parent story as `silent`
# and the one source that held the answer — the implementing developer's comment on the
# parent ticket — reached nobody, so the factory tested the letter of the AC.
# Ordered, and `comment` comes first on purpose: a column reading "comments of the ticket and
# its parent" is a comment, not the parent ticket, and on TP1-15045 the comment is the side
# that held the answer.
MATRIX_ORIGINS = ((("comment", "note", "discussion", "scope"), "comment"),
                  (("parent", "feature", "epic"), "parent_ticket"),
                  (("case", "tc-", "test", "suite"), "test"),
                  (("bug", "defect"), "test"),
                  (("code", "diff", "implementation"), "code"),
                  (("precedent", "prior"), "precedent"),
                  (("attachment",), "attachment"))      # LAST (1d): a column named `comments and attachments` stays a comment


def matrix_origin(column: str) -> str:
    """The `from` origin of a reading taken from one contradiction-matrix column."""
    text = str(column or "").strip().lower()
    for needles, origin in MATRIX_ORIGINS:
        if any(needle in text for needle in needles):
            return origin
    return "description"


def _section_header(register_text: str, heading: str) -> list:
    """The header cells of the table under `heading` — `grammar.table_rows` drops them, and a
    reading has to say WHICH source it came from, not only that one disagreed."""
    lines = (register_text or "").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().startswith(heading)), None)
    if start is None:
        return []
    for line in lines[start + 1:]:
        text = line.strip()
        if text.startswith("## "):
            break
        if text.startswith("|"):
            return G.split_cells(text)
    return []


# A register row's `source` word (`grammar.REQ_SOURCES`) -> the `contract.READING_ORIGINS` word of the FIRST reading
# of a contradiction, when the row has no `ac_ref` to name its criterion. A requirement read from a comment is
# never signed "description" to the person (t-928: a wrong origin shown at gate A). EXACT words, not needles like
# `MATRIX_ORIGINS`: a source cell is one word of a closed list, and a needle `ac` would match any text that holds
# it. `derived` and any word not here read as `description`, as before - a requirement taken from the diff has no
# ticket origin, and an unknown word is no reason to guess one (G1-3 adds the words for an attachment and a linked
# ticket; until then those two ride `story` and `feature`, qa-requirements-tester.md). The keys plus `derived` are
# `grammar.REQ_SOURCES`; test_gate_question_form pins it, so a new source word fails there, loudly.
REGISTER_SOURCE_ORIGINS = {"discussion": "comment", "feature": "parent_ticket", "story": "description",
                           "assumption": "description", "ac": "acceptance_criteria"}


def register_reading_origin(statement: dict) -> str:
    """The `from` of the first reading of a register requirement: its `ac_ref` names the criterion
    (`acceptance_criteria:AC-4`, as ever); without one its `source` word decides (`REGISTER_SOURCE_ORIGINS`);
    without either, `description`. Always a `contract.READING_ORIGINS` word (`question_errors` checks it)."""
    ref = str((statement or {}).get("ac_ref") or "").strip()
    if ref:
        return f"acceptance_criteria:{ref}"
    return REGISTER_SOURCE_ORIGINS.get(str((statement or {}).get("source") or "").strip().lower(), "description")


def register_statements(register_text: str) -> dict:
    """`{R-n: {"text": <the requirement as written>, "ac_ref": <AC-n or "">, "source": <the source word, lowercase,
    or "">}}` from `## Register`: the ONE reader of these two columns for a question (gate_brief reads this, not the table)."""
    import grammar as G
    header = [c.lower() for c in _section_header(register_text, "## Register")]
    try:
        ac_at = header.index("ac_ref")
    except ValueError:
        ac_at = -1
    try:
        source_at = header.index("source")
    except ValueError:
        source_at = -1
    out: dict = {}
    for cells in G.table_rows((register_text or "").splitlines(), "## Register"):
        if not cells or not G.REQ_ID_RE.match(cells[0]) or len(cells) < 2:
            continue
        ac = cells[ac_at] if 0 <= ac_at < len(cells) else ""
        source = cells[source_at] if 0 <= source_at < len(cells) else ""
        out.setdefault(cells[0], {"text": " ".join(str(cells[1]).split())[:300],
                                  "ac_ref": "" if str(ac).strip() in ("-", "—", "") else str(ac).strip(),
                                  "source": str(source).strip().lower()})
    return out


def register_contradiction_readings(register_text: str) -> dict:
    """`{R-n: {"quote", "against", "origin", "origins", "statement", "ac_ref", "first_from"}}` — both sides of one
    contradiction, in the form a gate question's `readings` needs (`origin` is the FIRST contradicting cell's, `origins`
    the origins of ALL of them).

    `register_contradictions` above returns the cell only; a person cannot answer "which
    reading do we test?" from one side of the disagreement and no name for the other."""
    import grammar as G
    header = _section_header(register_text, "## Contradiction matrix")
    statements = register_statements(register_text)
    out: dict = {}
    for cells in G.table_rows((register_text or "").splitlines(), "## Contradiction matrix"):
        if not cells or not G.REQ_ID_RE.match(cells[0]):
            continue
        for index, cell in enumerate(cells[1:], start=1):
            text = " ".join(str(cell).split())
            if not text.startswith("contradicts:"):
                continue
            against = header[index] if index < len(header) else "another source"
            statement = statements.get(cells[0]) or {}
            entry = out.setdefault(cells[0], {
                "quote": text.split(":", 1)[1].strip()[:200] or text[:200],
                "against": against,
                "origin": matrix_origin(against),
                "origins": [],
                "statement": statement.get("text", ""),
                "ac_ref": statement.get("ac_ref", ""),
                "first_from": register_reading_origin(statement),
            })
            if matrix_origin(against) not in entry["origins"]:
                entry["origins"].append(matrix_origin(against))      # EVERY contradicting source of the R (F3 t-1752)
    return out


def _fork_question_id():
    import question_register as QR      # the one whole-id boundary (AR-13), read at first use: this module does not import it at load
    return re.compile(QR.ID_BOUNDARY_BEFORE + r"Q\d+" + QR.ID_BOUNDARY_AFTER)




def register_fork_questions(register_text: str) -> dict:
    """`{R-n: [Qn, ...]}` from `## Reading forks`: the register questions a fork says closed it (HF4-8, F-3 (a)).

    The carrier is the `Decision` cell of the fork's row, read through the ONE cell reader of the package's tables
    (`project_decisions._cells`, axis 21: a `\\|` in a cell does not shift the columns). A fork closed by a question
    has a Decision that STARTS with the id of that question (`Q1 b adopted: ...`); a Decision that starts with
    anything else (`question at gate A`, a phrase, empty) names none. An id is a whole id by the `_mentions` rule
    (`Q1` is not `Q10`, `Q-1`, `q1` or `work/Q1.md`), and once the cell starts with one, EVERY whole id in it is
    returned, so a cell naming two questions is closed only when both are (the error direction is toward asking,
    FR-41). The words around an id (`adopted`, a reading letter) are never read (FR-12). No `## Reading forks`, no
    `Decision` column, a row with another cell count than the header (a stray pipe), an `R` that is not an
    `R-n`: nothing for that row, never an exception."""
    out: dict = {}
    for rid, decision in _fork_decisions(register_text):
        if _fork_question_id().match(decision) is None:      # `match`: the id must START the cell
            continue
        out.setdefault(rid, list(dict.fromkeys(_fork_question_id().findall(decision))))
    return out


def _fork_decisions(register_text: str) -> list:
    """`[(R-n, the Decision cell, stripped)]` of the `## Reading forks` rows, in register order: the ONE reader of that table's cells
    (`register_fork_questions` and `register_fork_quotes` read the Decision through it). No section, no `Decision` column, a row with
    another cell count than the header (a stray pipe), an `R` that is not an `R-n`: nothing for that row, never an exception."""
    import grammar as G
    import project_decisions as PD
    out: list = []
    columns: list = []
    inside = False
    for line in (register_text or "").splitlines():
        text = line.strip()
        if text.startswith("## "):
            inside = text.startswith("## Reading forks")
            columns = []
            continue
        if not inside or not text.startswith("|"):
            continue
        cells = PD._cells(text)
        if not columns:
            columns = [c.strip().lower() for c in cells]
            continue
        if not cells or set(cells[0]) <= set("-: ") or "decision" not in columns or len(cells) != len(columns):
            continue
        if not G.REQ_ID_RE.match(cells[0]):
            continue
        out.append((cells[0], cells[columns.index("decision")].strip()))
    return out


def register_fork_quotes(register_text: str) -> dict:
    """`{R-n: {"quote", "file"}}` from `## Reading forks`: the forks the person closed in their OWN words (D1-B B1, RN1-14). The carrier
    is the `Decision` cell, read through `_fork_decisions`; a cell that STARTS with the quote form `"<their words>" (<file>.txt)` (the
    `: <why>` tail is optional) is returned with the quote (whitespace squeezed) and the file. Whether the quote is the person's is NOT
    decided here - `branch_accounting.quote_problem` is the one reader of the words file (AR-13). A cell that starts with anything else
    (a question id, a phrase, empty) is not in the map (FR-12: no phrase is read). Never raises: nothing readable is `{}`."""
    try:
        import branch_accounting as BA
        out: dict = {}
        for rid, decision in _fork_decisions(register_text):
            found = BA.QUOTE_HEAD_RE.match(decision)
            if found:
                out.setdefault(rid, {"quote": " ".join(found.group("quote").split()), "file": found.group("file").strip()})
        return out
    except Exception:  # noqa: BLE001
        return {}


def contradiction_errors(rows, register_text: str) -> list:
    """Every contradicted requirement reaches a plan row that carries the flag.

    `source_conflict: true` (sources disagree with each other or with the code) and
    `oracle_unknown: true` (no settled expected value) are what the rest of the pipeline reads:
    `validate_plan` requires an independent design review on such a row, the critic reviews it,
    and gate A asks the owner about it with the quote. A contradiction that never lands on a
    row is a decision the factory made by silence."""
    contradicted = register_contradictions(register_text)
    if not contradicted:
        return []
    errors = []
    for rid, quote in sorted(contradicted.items()):
        matching = [row for row in (rows if isinstance(rows, list) else [])
                    if isinstance(row, dict) and rid in row_requirements(row)]
        if not matching:
            errors.append(f"{rid}: the register's matrix records {quote}, and no plan row covers "
                          f"{rid} — a contradiction cannot be closed by leaving it out of the plan")
            continue
        unflagged = [str(row.get("id") or "?") for row in matching
                     if not (row.get("source_conflict") or row.get("oracle_unknown"))]
        if len(unflagged) == len(matching):
            errors.append(f"{rid}: the register's matrix records {quote}; the plan row(s) "
                          f"{', '.join(unflagged)} carry neither `source_conflict: true` nor "
                          "`oracle_unknown: true`, so the reading you chose reaches gate A as a "
                          "settled fact and nobody reviews it")
    return errors


def story_register_text(task_root) -> str:
    """The story's requirements register, wherever this story keeps it ('' when there is none)."""
    try:
        import contract
        path = contract.artifact(Path(task_root), "requirements-register.md")
    except Exception:
        path = Path(task_root) / "work" / "requirements-register.md"
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


# --- question branches: what a row and a case do once an open question is answered ----------
# TP1-13797 (cmp1, B-216): five register questions stood at gate A and the person answered
# four of them by letter, but nothing in the plan or the cases said what an answer DOES - TS-6's
# disposition and TC_006's Then stayed as authored, and the row's `reason` went on naming a
# question the person had already settled. The authors now write the branch BEFORE the gate:
#   row   `question_refs: ["Q1"]` and `if_answered: {"Q1": {"a": <patch>, "b": <patch>,
#         "not_needed": <patch>, "*": <patch>}}`; the row as authored is the UNANSWERED branch.
#   case  `question_thens: [{"question": "Q1", "then": 1, "readings": {"a": "..", "b": ".."},
#         "not_needed": ".."}]`; Then 1 keeps its number in every branch, an empty reading text
#         means "this answer asserts nothing here" and never renumbers anything.
# `variant_errors` is the pure half of the gate rehearsal (`gate_preflight.check_question_
# branches` reads the files and calls it): nothing is read or written here. Error direction: it
# may only err toward a finding that sends the AUTHOR back; it never decides an answer, and a
# story with none of these fields is never refused (builder rule 9, stories in flight).

ANY_READING = "*"          # the patch of every reading letter that has no key of its own
NOT_NEEDED = contract.NOT_NEEDED_KEY  # its own key: `*` never covers it (a dropped check is not a reading)
SETTLED_STATUSES = ("answered", "not_needed")
BRANCH_KEYS_PATH = Path(__file__).resolve().parent.parent / "references" / "question-branch-keys.json"
BRANCH_KINDS = ("unresolved_ref", "missing_refs", "bad_branch", "invalid_variant", "stale_reason",
                "missing_reading_text", "settled_question", "dependent_pair", "case_unreadable",
                "missing_branch", "no_row_for_question", "row_owes_case")
BRANCH_WAY = {"strategist": "the strategist's rework repairs this row",
              "designer": "the case designer's rework repairs this case"}
# RN1-2: the kinds of `BRANCH_KINDS` the STRATEGIST owns and the S3 exit REFUSES, in the strategist's own context (an exit that
# let them through made a formal rework round after S3 closed). The designer-owned kinds cannot arise without cases.
# `no_row_for_question` is NOT here: at S3 no case exists, so a question whose executor is a case's `question_thens` would be
# refused falsely, and for a requirement whose rows all exclude it the register fence already refuses the same fact (B-4).
S3_EXIT_KINDS = ("missing_branch", "unresolved_ref", "missing_refs", "bad_branch", "invalid_variant", "stale_reason",
                 "settled_question", "dependent_pair")
S3_WARN_KINDS = ("no_row_for_question",)         # printed as a WARN at the exit; never a refusal, never a remark round
NEW_REF = re.compile(r"new:([1-9][0-9]?)")       # the door for a question the register does not hold: new:<n>, n in 1..99 (per row)
NEW_REF_WORDS = ('write "new:<n>" (n from 1 to 99) in question_refs and an entry in the row\'s new_questions '
                 '{"key": "new:<n>", "question", "source_says": [{"quote", "where"}], "readings": [{"reading", "from", "if_chosen"}, '
                 'two or more], "severity", "owner_role"}; code raises it as the next Q-n when S3 closes')


def branch_patch_keys() -> tuple:
    """The row fields a variant may patch, from `references/question-branch-keys.json` (FR-13).
    A missing or malformed file is a package defect, never a verdict about the story."""
    try:
        keys = json.loads(BRANCH_KEYS_PATH.read_text(encoding="utf-8-sig"))["patch_keys"]
        if not (isinstance(keys, list) and keys and all(isinstance(k, str) and k for k in keys)):
            raise ValueError("`patch_keys` must be a non-empty list of row field names")
        return tuple(keys)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"{BRANCH_KEYS_PATH} is unusable ({type(exc).__name__}: {exc}); it holds "
                           "the closed list `patch_keys` - restore it from the package") from exc


def resolve_patch(entry, key):
    """The ONE reader of `if_answered[<question id>]` - the S3 check, the gate card
    (`gate_brief._patch_for`) and the applier (`apply_gate_answers`) all call it (FR-10, t-227b C5).

    `key` is a reading letter or `not_needed`. Returns a NEW dict, or None when nothing is written
    for the answer (the row stays as authored). A reading letter gets the patch under `*` (every
    reading) and then the one under its own letter laid over it, so the letter wins where both set
    a key; `not_needed` is its own key and `*` never covers it (a dropped check is not a reading).
    MERGE, not replace: the card used to merge and the applier to replace, so one `if_answered`
    showed the person a row the applier would not produce. A value that is not an object is no
    patch; the shape finding for it is `variant_errors`'s."""
    if not isinstance(entry, dict):
        return None
    names = (NOT_NEEDED,) if key == NOT_NEEDED else (ANY_READING, key)
    merged, found = {}, False
    for name in names:
        patch = entry.get(name)
        if isinstance(patch, dict):
            merged.update(patch)
            found = True
    return merged if found else None


def apply_patch(row, patch) -> dict:
    """A copy of `row` with `patch` laid over it; a patched `coverage_obligations` replaces the
    whole list. Pure: neither argument is changed."""
    return {**copy.deepcopy(row), **copy.deepcopy(patch if isinstance(patch, dict) else {})}


def _carries(value) -> bool:
    """A field that says something: present, and not an empty placeholder."""
    return value is not None and value != [] and value != {} and value != ""


def plan_created(task_root):
    """The `created` date of the story's plan (the front matter of `test-plan.md`, else a `created` key
    of `test-plan.json`), or None when it names none."""
    try:
        import contract
        found = contract.front_line(contract.read_text(contract.artifact(Path(task_root), "test-plan.md")), "created")
        if found:
            return found.strip().strip("\"'")
        path = story_plan_path(Path(task_root))
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path is not None else None
        return str(data.get("created")) if isinstance(data, dict) and data.get("created") else None
    except Exception:
        return None


def has_branch_fields(rows, cases=(), plan_created=None) -> bool:
    """Is this plan under the branch contract? Yes when it or any case carries a branch field, OR when
    the plan was `created` on or after ORACLE_CUTOFF (O12): from that day a plan with no branch field
    anywhere is a plan whose rows that rest on a question forgot the branch, not a story written
    before the contract ("manual until Q5 is answered" is exactly that input). No - and nothing
    about it is ever a finding - for a plan created before the cutoff or with no date: the invariant
    "a story with no branch field is never refused" is DATED here, not dropped (builder rule 9)."""
    if plan_created is not None:
        import contract
        if contract.after_oracle_cutoff(plan_created):
            return True
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and (_carries(row.get("question_refs")) or _carries(row.get("if_answered"))):
            return True
    # A case's `question_thens:` line counts even when blank: a nested block the flat
    # front-matter parser loses is a designer's defect worth saying, not legacy silence.
    return any(isinstance(case, dict) and case.get("question_thens") is not None
               for case in (cases if isinstance(cases, (list, tuple)) else ()))


def _letters(question) -> list:
    import contract
    return contract.reading_letters(question)


def _obligation_ids(value) -> list:
    """The `obligation_id`s of a `coverage_obligations` value (a list of objects, or of bare ids); junk reads as none."""
    out = []
    for item in (value if isinstance(value, list) else ()):
        oid = item.get("obligation_id") if isinstance(item, dict) else item
        if isinstance(oid, str) and oid.strip():
            out.append(oid.strip())
    return list(dict.fromkeys(out))


def _id_token(qid: str):
    """The id as a whole token: `Q1` is in "per Q1." and "(Q1)", and is not in `Q10` or `Q1-b`."""
    return re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(qid) + r"(?![A-Za-z0-9_-])")


def _delta_hint(row, patch) -> str:
    """The way out of a trap the closed patch list sets (SC1-1, M1; FR-11). A row of the coverage-observation
    revision carries a `coverage_delta` that maps its obligations by id; `coverage_delta` is no patch key, so a
    patch that replaces `coverage_obligations` under other ids can only break the delta ("must map each
    obligation exactly once"), and the author, told only that, put `coverage_delta` into the patch (12586: a
    second round for a key outside the list). Structure, not wording (FR-12): '' unless the row has that
    revision, a `coverage_delta` with entries, and the patch replaces the list with a different id set. The
    revision is `coverage_contract.COVERAGE_CONTRACT_REVISION`, never a copy of its text (AR-13)."""
    from coverage_contract import COVERAGE_CONTRACT_REVISION
    try:
        delta = row.get("coverage_delta")
        obligations = patch.get("coverage_obligations")
        if (row.get("coverage_contract_revision") != COVERAGE_CONTRACT_REVISION or not isinstance(delta, dict)
                or not isinstance(delta.get("entries"), list) or not isinstance(obligations, list)):
            return ""
        mapped = list(dict.fromkeys(e["obligation_id"] for e in delta["entries"]
                                    if isinstance(e, dict) and isinstance(e.get("obligation_id"), str)))
        patched = {o["obligation_id"] for o in obligations
                   if isinstance(o, dict) and isinstance(o.get("obligation_id"), str)}
        if not mapped or set(mapped) == patched:
            return ""
        return ("the row's coverage_delta is not patchable: keep the obligation ids it maps "
                f"({', '.join(mapped)})")
    except (AttributeError, TypeError):
        return ""


def _review_hint(row, after, allowed) -> str:
    """The way out of the second trap the closed patch list sets (SC1-1 A-4; FR-11). A patch that makes the result
    unknown (`oracle_unknown: true`) obliges the row to carry `design_review_required: true`
    (`_needs_design_review`), a field no patch can set, so the variant breaks the contract on it and the author, told
    only that, put the field into the patch (a `bad_branch` round). Structure, not wording (FR-12): '' unless the
    patched row needs the review and the authored row did not, the patched row does not carry it, and the key is
    not in the closed list (with the key in the list the sentence would be false)."""
    try:
        if ("design_review_required" in allowed or not _needs_design_review(after) or _needs_design_review(row)
                or after.get("design_review_required") is True):
            return ""
        return ("`design_review_required` is not patchable: set `design_review_required: true` on the row itself, "
                "outside the branch")
    except (AttributeError, TypeError):
        return ""


def _canon(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError, RecursionError):
        return repr(value)


def case_entry_answers(item, key, question) -> bool:
    """Does one `question_thens` entry of a case say what the answer `key` (a reading letter or `not_needed`, as
    `question_register.answer_key` gives it) asserts for `question`? The text may be empty: an empty reading text means
    "this answer asserts nothing here" and is still an answer (`readings: {"a": ""}`). No key (None: the question is not
    settled, or was answered in words only), an entry that is no object, or a text that is no string: no. The ONE door of
    "is this case entry resolved for the recorded answer": `variant_errors` and the late-answer applier both ask it, and it
    asks `contract.question_then_text` - the one reader the card and the resolver share (a before/now question's texts are
    keyed by meaning, `now` / `before`, not by letter)."""
    if not isinstance(item, dict) or not isinstance(key, str) or not key:
        return False
    return isinstance(contract.question_then_text(question, item, key)[0], str)


def _claim_key_errors(item, question) -> list:
    """What is wrong with the KEYS of one case entry's `readings` for `question`, as plain sentences (HF4-7); [] when
    they are right. A before/now question's texts are keyed `now` / `before` - the factory fixes which reading is which,
    not the case; a letter there is a text the person would see under a reading it was not written for. Every other
    question's texts are keyed by letter, and the words `now` / `before` there are the same mistake mirrored; both kinds
    in one entry are a mix. Pure; the caller decides where it stands (after the settled / resolved exits)."""
    readings = item.get("readings") if isinstance(item, dict) else None
    if not isinstance(readings, dict):
        return []
    words = [str(key) for key in readings if key in contract.CLAIM_KEYS]
    others = [str(key) for key in readings if key not in contract.CLAIM_KEYS]
    now, before = contract.CLAIM_KEYS
    if contract.is_claim_question(question):
        if not others:
            return []
        shown = ", ".join(f"`{key}`" for key in others)
        return [f"letters on a before/now question: the reading order is fixed by the factory, not by the case; the "
                f"entry is keyed {shown}, and it is expected under `{now}` (the behaviour now is the expected one) and "
                f"`{before}` (the behaviour before is)"
                + (f", not mixed with {', '.join('`%s`' % w for w in words)}" if words else "")]
    if words:
        return [f"`{now}` / `{before}` on a question that does not mark which reading is the behaviour now: its readings are lettered, so the "
                f"entry is keyed by letter ({', '.join('`%s`' % w for w in words)} is no reading of it)"]
    return []


def variant_errors(rows, questions, cases=(), *, allow_keys=None, plan_contract_mode="legacy",
                   coverage_contract_version=1, plan_created=None, at_cases_stage=False) -> list:
    """Every reason a row's or a case's branches cannot be trusted at gate A. Pure; never raises.

    `at_cases_stage` (GW1-41): True only from the S4 rehearsal (`gate_preflight.check_question_branches`), where the cases
    exist and each carries its `plan_row`. `row_owes_case` is silent without it: at the S3 exit there are no cases yet, and an
    empty case list at S4 is a finding, not silence.

    `rows` the plan rows. `questions` the register's questions as `question_register.load`
    returns them (each: `id`, `status`, `letters` or `readings`). `cases` one dict per case of
    the story: `{"case": id, "readable": bool, "question_thens": <the front-matter value, JSON
    text or a list, None when the case has none>, "thens": [the numbers of the items under
    `## Then`]}`. `allow_keys` the patch keys (default: `question-branch-keys.json`).

    Returns `[{"kind": one of BRANCH_KINDS, "owner": "strategist" | "designer", "where": row or
    case id, "question": register id or "", "message": plain words, ending in the owner's
    rework}]`. [] for a story with no branch field anywhere (unless `plan_created` is on or after
    ORACLE_CUTOFF, O12: `has_branch_fields`). A question is settled only when `question_register.settled`
    says so (the ONE definition, AR-13): `answered` / `not_needed` on the bytes the person saw. Every other
    one counts as open: a question with the designer, one only named in old gate words, a deferred one, an
    answered one whose row changed since or whose `before` value is missing. A case entry on a settled
    question that carries the text for the RECORDED answer is resolved (`case_entry_answers`); one that does
    not is `settled_question`. Ids match exactly after trimming: `Q1` is not `Q10`."""
    import question_register as QR
    rows = rows if isinstance(rows, list) else []
    cases = [case for case in (cases if isinstance(cases, (list, tuple)) else ()) if isinstance(case, dict)]
    if not has_branch_fields(rows, cases, plan_created):
        return []
    allowed = tuple(allow_keys) if allow_keys is not None else branch_patch_keys()
    known: dict = {}
    for question in (questions if isinstance(questions, (list, tuple)) else ()):
        if isinstance(question, dict) and isinstance(question.get("id"), str) and question["id"].strip():
            known.setdefault(question["id"].strip(), question)
    # a row-local `new:<n>@<row>` question (`plan_questions_view`) is no id of the register: the list below names the register's
    ids = named_ids([k for k in known if "@" not in k or not k.startswith("new:")], 8, where="the plan's questions") or "none"
    out: list = []
    seen: set = set()

    def add(kind, owner, where, question, body, lacking=""):
        message = f"{body} - {BRANCH_WAY[owner]}"
        # RN1-2 (R-2): one fact is ONE line. `unresolved` runs for the same ref from `question_refs` and again from `if_answered`;
        # the key holds the message, so two different findings are never merged (E-19).
        if (kind, where, question, message) in seen:
            return
        seen.add((kind, where, question, message))
        out.append({"kind": kind, "owner": owner, "where": where, "question": question,
                    "message": message, **({"lacking": lacking} if lacking else {})})

    def unresolved(owner, where, ref):
        # the door for a question the register lacks is the STRATEGIST's (the plan row); a case designer has no such field
        door_text = f". For a question the register does not hold, {NEW_REF_WORDS}" if owner == "strategist" else ""
        add("unresolved_ref", owner, where, ref,
            f"{where}: `{ref}` is not a question id of the register (ids are matched exactly: Q1 is "
            f"not Q10, and an alias such as Q-R14 is no id); the register's ids are {ids}{door_text}")

    def settled(owner, where, qid, what):
        add("settled_question", owner, where, qid,
            f"{where}: {qid} is already answered, yet {what} still branches on it; an answered "
            "question stays no branch - remove the branch")

    refs_carried = any(isinstance(row, dict) and _carries(row.get("question_refs")) for row in rows)
    from branch_accounting import PLAN_EXCLUDING
    case_rows = {str(case.get("plan_row") or "").strip() for case in cases}
    case_qids: set = set()       # the questions some case's `question_thens` answers (an executor of the answer, A6)
    base = None
    touched: dict = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or f"row[{index}]")
        refs = row.get("question_refs")
        if _carries(refs):
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                add("bad_branch", "strategist", rid, "",
                    f"{rid}: `question_refs` must be a list of register question ids, such as [\"Q1\"]")
            else:
                for ref in dict.fromkeys(ref.strip() for ref in refs):
                    if ref not in known:
                        unresolved("strategist", rid, ref)
        elif refs_carried and row.get("oracle_unknown"):
            add("missing_refs", "strategist", rid, "",
                f"{rid}: the expected result is unknown (`oracle_unknown`) but the row names no "
                "question in `question_refs`, so nothing says which answer would settle it")
        branches = row.get("if_answered")
        # t-227b (F14, F15): a row that RESTS on an open question says what every answer does. It
        # rests on Q when Q is in `question_refs` or Q's id stands as a whole token in its `reason`
        # (structure, not a phrase list: FR-12). cmp2 (TP1-15045): five rows named Q1-Q6, none
        # carried a branch, and the person's six answers changed nothing. This stands BEFORE the
        # "no branches" skip below: a row with no `if_answered` at all is exactly the case. A
        # question settled already (answered at an S2/S3 stop, or here) is never asked for a branch
        # (C4); the finding for a branch that stays on it is `settled_question`.
        # Invariants kept: a story with no branch field anywhere returned above; a row that names no
        # question and whose reason names none is never touched; a malformed `if_answered` is
        # `bad_branch`'s and is not also called missing.
        listed = refs if isinstance(refs, list) and all(isinstance(ref, str) for ref in refs) else []
        named = {ref.strip() for ref in listed}
        reason = row.get("reason") if isinstance(row.get("reason"), str) else ""
        shaped_ok = not _carries(branches) or isinstance(branches, dict)
        rests_on = []
        for qid, question in known.items():
            if not shaped_ok or QR.settled(question):
                continue
            if qid not in named and not (reason and _id_token(qid).search(reason)):
                continue
            rests_on.append(qid)
            entry = branches.get(qid) if isinstance(branches, dict) else None
            if qid in (branches if isinstance(branches, dict) else {}) and not isinstance(entry, dict):
                continue            # `bad_branch` says what is wrong with it below
            have = set(entry) if isinstance(entry, dict) else set()
            letters = _letters(question)
            lacking = [letter for letter in letters if letter not in have and ANY_READING not in have]
            if NOT_NEEDED not in have:
                lacking.append(NOT_NEEDED)
            if lacking:
                add("missing_branch", "strategist", rid, qid,
                    f"{rid}: it rests on {qid} but `if_answered` has no branch for "
                    f"{', '.join(lacking)} - give `if_answered[\"{qid}\"]` a key for every reading "
                    f"letter ({', '.join(letters) or 'this question has none'}) or `{ANY_READING}` for "
                    f"all of them, and `{NOT_NEEDED}`; an empty object `{{}}` says the row stays as written",
                    lacking=", ".join(lacking))
        # O10 (F22, decided by Lead: do now). A branch that EXISTS must also say what the answer settles.
        # (1) cmp2: all six rows were `oracle_unknown: true`, TS-4's `a`/`b` did not clear it, and the
        # answer changed nothing in the plan - the row still said the expected result was unknown after
        # the person had told it. A row that rests on exactly ONE open question and is `oracle_unknown`
        # sets `oracle_unknown: false` in every reading's branch (with two open questions one answer
        # settles only half, so it is not asked). (2) A branch whose patch sets a `manual-*` disposition
        # carries its `test_level_rationale` (P19: the rung and why the lower ones do not apply); code checks
        # presence, the meaning is the critic's (F22, FR-47). A patch with no `disposition` key leaves the
        # row's own words (and its own rationale) as they are. `not_needed` keeps the row as written and
        # is asked for neither. A letter with no branch at all is the finding above, not this one.
        for qid in rests_on:
            entry = branches.get(qid) if isinstance(branches, dict) else None
            if not isinstance(entry, dict):
                continue
            patches = {letter: resolve_patch(entry, letter) for letter in _letters(known[qid])}
            patches = {letter: patch for letter, patch in patches.items() if isinstance(patch, dict)}
            if row.get("oracle_unknown") and len(rests_on) == 1:
                lacks = [letter for letter, patch in patches.items() if patch.get("oracle_unknown") is not False]
                if lacks:
                    add("missing_branch", "strategist", rid, qid,
                        f"{rid}: it rests on {qid} and is `oracle_unknown`, but its branch for {', '.join(lacks)} "
                        "does not set `oracle_unknown: false` - an answer settles the expected result, so every "
                        "reading's branch says so; without it the plan still calls the result unknown after "
                        "the person has answered", lacking=f"`oracle_unknown: false` for {', '.join(lacks)}")
            bare = [letter for letter, patch in patches.items()
                    if str(patch.get("disposition") or "").startswith("manual")
                    and not str(patch.get("test_level_rationale") or "").strip()]
            if bare:
                add("missing_branch", "strategist", rid, qid,
                    f"{rid}: it rests on {qid} and its branch for {', '.join(bare)} sets a `manual-*` "
                    "disposition without a `test_level_rationale` - name the P19 rung that check sits on and "
                    "why the lower rungs do not apply, in that branch",
                    lacking=f"`test_level_rationale` for {', '.join(bare)}")
            # GW1-41 (N9): the answer that makes the row `automate` carries its pyramid `level` (the plan contract asks
            # `automate` for one); the refusal is lawful at S3 like `test_level_rationale`. Only a patch that SETS the
            # disposition is read, so a row already broken is not named twice.
            unlevelled = [letter for letter, patch in patches.items() if patch.get("disposition") == "automate"
                          and not str(apply_patch(row, patch).get("level") or "").strip()]
            if unlevelled:
                add("missing_branch", "strategist", rid, qid,
                    f"{rid}: it rests on {qid} and its branch for {', '.join(unlevelled)} makes the row `automate` "
                    "without a `level` - name the pyramid level in that branch (P19)",
                    lacking=f"`level` for {', '.join(unlevelled)}")
            # GW1-41 (N9): a case quotes the obligation ids its row WROTE; a patch that replaces `coverage_obligations` and drops
            # one of them leaves the case quoting an id the answered row no longer has. Adding new ids is fine (a subset check, the
            # cases quote what was written). Cases exist only at the S4 rehearsal, where this is a refusal; at S3 there are none.
            written = _obligation_ids(row.get("coverage_obligations"))
            quoted = [oid for oid in written if any(
                str(case.get("plan_row") or "").strip() == rid and _id_token(oid).search(str(case.get("text") or "")) for case in cases)]
            if quoted:
                for letter, patch in patches.items():
                    if "coverage_obligations" not in patch:
                        continue
                    dropped = [oid for oid in quoted if oid not in _obligation_ids(patch.get("coverage_obligations"))]
                    if dropped:
                        add("bad_branch", "strategist", rid, qid,
                            f"{rid}: the patch for {qid} = {letter} drops obligation ids {', '.join(dropped)} that a case of this row "
                            "quotes; keep them")
        if at_cases_stage and row.get("disposition") in PLAN_EXCLUDING and rid not in case_rows:
            # N9 (F-1 (a)): gate A stands AFTER S4, and a `skip` / `unverifiable` row gets no case. An answer that turns the
            # row into one that needs a case has no road back to S4 for a row id (controller.py), so the case is written
            # now with `question_thens`. A person's word passes this.
            for qid in rests_on:
                entry = branches.get(qid) if isinstance(branches, dict) else None
                hit = next(((letter, patch) for letter in _letters(known[qid])
                            for patch in [resolve_patch(entry, letter)]
                            if isinstance(patch, dict) and patch.get("disposition") in contract.DISPOSITIONS
                            and patch.get("disposition") not in PLAN_EXCLUDING), None)
                if hit:
                    add("row_owes_case", "designer", rid, qid,
                        f"{rid}: the row is `{row.get('disposition')}` and {qid} = {hit[0]} makes it `{hit[1]['disposition']}`, "
                        "but no case is written for it. Expected: a case with `Plan row: " + rid + "` and `question_thens` on "
                        f"{qid}, written before gate A: after the answer there is no road back to S4 for a row id. A person's word passes this")
                    break
        if not _carries(branches):
            continue
        if not isinstance(branches, dict):
            add("bad_branch", "strategist", rid, "",
                f"{rid}: `if_answered` must be an object of {{question id: {{reading letter: patch}}}}")
            continue
        for raw_id, entry in branches.items():
            qid = str(raw_id).strip()
            question = known.get(qid)
            if question is None:
                unresolved("strategist", rid, qid)
                continue
            if QR.settled(question):
                settled("strategist", rid, qid, "the row")
                continue
            if not isinstance(entry, dict):
                add("bad_branch", "strategist", rid, qid,
                    f"{rid}: `if_answered` for {qid} must be an object of {{reading letter: patch}}")
                continue
            letters = _letters(question)
            # SC1-1: a malformed key is named (`bad_branch`) and the rest of the branch is still judged, so one
            # round names everything. `clean` is the branch WITHOUT what was named: a key that is no reading,
            # a patch that is no object, and in every patch the fields outside the closed list. Invariant: a
            # field outside the closed list is never applied to a row; `apply_patch` below sees `clean` only.
            clean: dict = {}
            fields: set = set()
            for key, patch in entry.items():
                if key not in letters and key not in (NOT_NEEDED, ANY_READING):
                    add("bad_branch", "strategist", rid, qid,
                        f"{rid}: `{key}` under {qid} is not a reading of {qid} (its readings are "
                        f"{', '.join(letters) or 'none'}; `{NOT_NEEDED}` and `{ANY_READING}` are the other keys)")
                elif not isinstance(patch, dict):
                    add("bad_branch", "strategist", rid, qid,
                        f"{rid}: the patch for {qid} = {key} must be an object of row fields")
                elif [k for k in patch if k not in allowed]:
                    add("bad_branch", "strategist", rid, qid,
                        f"{rid}: the patch for {qid} = {key} sets "
                        f"{', '.join('`%s`' % k for k in patch if k not in allowed)}, outside the "
                        f"closed list ({', '.join(allowed)})")
                    clean[key] = {k: v for k, v in patch.items() if k in allowed}
                else:
                    fields.update(patch)
                    clean[key] = patch
            touched.setdefault(index, {})[qid] = fields
            if not clean:
                continue            # no patch object is left to apply
            groups: dict = {}
            for label in (*letters, NOT_NEEDED):
                patch = resolve_patch(clean, label)
                if isinstance(patch, dict):
                    groups.setdefault(_canon(patch), (patch, []))[1].append(label)
            for patch, labels in groups.values():
                answer = ", ".join(labels)
                reason = patch.get("reason")
                if isinstance(reason, str) and _id_token(qid).search(reason):
                    add("stale_reason", "strategist", rid, qid,
                        f"{rid}: once {qid} is answered ({answer}) the row's `reason` still names "
                        f"{qid}, a question that is settled by then; write that reason without it "
                        "(only the other reason the row stays as it is, if there is one)")
                elif ("reason" not in patch and "disposition" in patch
                      and patch["disposition"] != row.get("disposition")
                      and isinstance(row.get("reason"), str) and _id_token(qid).search(row["reason"])):
                    # E-19: the answer moves the row and leaves the authored reason, which names
                    # the question, as it was. Invariant: after the answer no reason names it; a
                    # reason that also names ANOTHER question is repaired to that one alone.
                    add("stale_reason", "strategist", rid, qid,
                        f"{rid}: once {qid} is answered ({answer}) the row's disposition changes, but "
                        f"its authored `reason` still names {qid}, a question that is settled by then; "
                        "patch `reason` with the reason that remains, without it (only the other "
                        "reason, if the row has one)")
                if base is None:
                    try:
                        base = set(gate_plan_errors(rows, plan_contract_mode, coverage_contract_version))
                    except Exception:
                        base = set()
                patched = list(rows)
                patched[index] = apply_patch(row, patch)
                try:
                    errors = gate_plan_errors(patched, plan_contract_mode, coverage_contract_version)
                except Exception as exc:
                    errors = [f"the patched row could not be validated ({type(exc).__name__}: {exc})"]
                new = [error for error in errors if error not in base]
                if new:
                    # SC1-1: EVERY new error of the patched row, in the contract's order: the volume is bounded
                    # by one row. The print sites cut with their own renderers, never this function.
                    # E7 (kept loss): the head of the message is byte-identical, so a person's word that quotes the
                    # head still passes; a word that quotes the WHOLE old message, tail included, no longer matches
                    # once a row has more than two errors (the old text stopped at the second).
                    hints = [h for h in (_delta_hint(row, patch), _review_hint(row, patched[index], allowed)) if h]
                    add("invalid_variant", "strategist", rid, qid,
                        f"{rid}: if {qid} is answered ({answer}) the row would break the plan "
                        f"contract: {'; '.join([*new, *hints])}")
    for index, per_question in touched.items():
        names = sorted(per_question)
        rid = str(rows[index].get("id") or f"row[{index}]")
        for position, first in enumerate(names):
            for second in names[position + 1:]:
                shared = sorted(per_question[first] & per_question[second])
                if shared:
                    add("dependent_pair", "strategist", rid, first,
                        f"{rid}: {first} and {second} both patch "
                        f"{', '.join('`%s`' % f for f in shared)} - a DEPENDENT pair: one answer changes "
                        "what the other means, so code cannot apply both; give one of the two "
                        "questions no variant on those fields")
    users: dict = {}
    for case in cases:
        cid = str(case.get("case") or "?")
        if case.get("readable") is False:
            add("case_unreadable", "designer", cid, "",
                f"{cid}: the case file cannot be read, so its `question_thens` were not checked")
            continue
        raw = case.get("question_thens")
        if raw is None:
            continue
        items = raw
        if isinstance(raw, str):
            try:
                items = json.loads(raw)
            except (ValueError, RecursionError):
                items = None
        if not isinstance(items, list):
            add("bad_branch", "designer", cid, "",
                f"{cid}: `question_thens` must be ONE line of JSON, a list of {{\"question\", \"then\", "
                "\"readings\"}} objects (an empty value, or a nested block the flat front matter "
                "loses, reads as nothing)")
            continue
        listed = case.get("thens")
        numbers = [n for n in listed if isinstance(n, int)] if isinstance(listed, (list, tuple)) else []
        for item in items:
            if not isinstance(item, dict):
                add("bad_branch", "designer", cid, "",
                    f"{cid}: every `question_thens` entry must be an object of question, then, readings")
                continue
            qid = str(item.get("question") or "").strip()
            question = known.get(qid)
            if question is None:
                unresolved("designer", cid, qid or "(empty)")
                continue
            case_qids.add(qid)
            # N2 (HF2-7): a settled question's entry that holds the text for the RECORDED answer is resolved at read time
            # (the approved case is never edited: `contract.resolve_then_oracle` reads it the same way); an entry
            # without that key is the author's rework, as before. Only a question `QR.settled` calls settled has a key.
            resolved = case_entry_answers(item, QR.answer_key(question), question)
            if QR.settled(question) and not resolved:
                settled("designer", cid, qid, "a Then of the case")
                continue
            then = item.get("then")
            if isinstance(then, int) and not isinstance(then, bool) and then in numbers:
                users.setdefault((cid, then), []).append(qid)
            else:
                add("bad_branch", "designer", cid, qid,
                    f"{cid}: `then` for {qid} must be the number of an item under `## Then` "
                    f"(this case has {', '.join(map(str, numbers)) or 'none'}), not {then!r}")
            if resolved:
                continue            # the readings of an answer already given are no longer checked: nothing branches on them
            # an answer by letter that is recorded but not `settled` (a legacy question awaiting the value of `before`) was
            # given on the text the person was shown; nothing is asked of its entry anew (N7-3: clean before, clean now)
            by_letter = (question.get("status") == "answered" and str(question.get("reading") or "").strip()
                         and question.get("changed_since_answer") is not True)
            letters = contract.reading_letters(question) if by_letter else contract.question_then_keys(question)
            readings = item.get("readings")
            if not isinstance(readings, dict):
                add("bad_branch", "designer", cid, qid,
                    f"{cid}: `readings` for {qid} must be an object of {{reading letter: Then text}}")
                continue
            # HF4-7: the keys of a before/now question's entry are its meanings (after the `settled` / `resolved` exits)
            wrong_keys = [] if by_letter else _claim_key_errors(item, question)
            if wrong_keys:
                for problem in wrong_keys:
                    add("bad_branch", "designer", cid, qid, f"{cid}: Then {item.get('then')!r} asks {qid}, and {problem}")
                continue
            missing = [letter for letter in letters if not isinstance(readings.get(letter), str)]
            if missing:
                add("missing_reading_text", "designer", cid, qid,
                    f"{cid}: Then {then} asks {qid} but has no text for reading {', '.join(missing)}; "
                    "give every reading a text (an empty text is allowed and means this answer "
                    "asserts nothing here - the Then keeps its number)")
            extra = [key for key in readings if key not in letters]
            if extra:
                add("bad_branch", "designer", cid, qid,
                    f"{cid}: `readings` for {qid} names {', '.join(map(str, extra))}, which "
                    f"{'is' if len(extra) == 1 else 'are'} no reading of {qid} (its readings are "
                    f"{', '.join(letters) or 'none'})")
            if NOT_NEEDED in item and not isinstance(item[NOT_NEEDED], str):
                add("bad_branch", "designer", cid, qid,
                    f"{cid}: `{NOT_NEEDED}` for {qid} must be a text (empty is allowed)")
    for (cid, then), qids in users.items():
        if len(set(qids)) > 1:
            names = sorted(set(qids))
            add("dependent_pair", "designer", cid, names[0],
                f"{cid}: {' and '.join(names)} both give Then {then} a reading - a DEPENDENT pair: "
                "one answer changes what the other means, so code cannot apply both; let one "
                "question own that Then")
    # GW1-41 (A6, F-2): an answer to an OPEN question about a requirement changes the plan or the plan says so out loud. The
    # executor of a question is a row with a NON-EMPTY branch for a reading of it (`not_needed` does not count, nor does `{}`)
    # or a case with a `question_thens` entry on it; a mention in `question_refs` / `reason` is not one. A question about a
    # requirement is one whose `question` / `source_says` holds a register id as a whole token (`raised_for` says nothing of
    # a requirement); a question with no such token is not examined. A negation ("not about R-9") gives a false finding on the
    # safe side: a person's word passes it (FR-12).
    for qid, question in known.items():
        if QR.settled(question) or question.get("status") == QR.DEFERRED:
            continue
        ids_named = [m for m in dict.fromkeys(re.findall(r"(?<![A-Za-z0-9_-])R-\d+(?![A-Za-z0-9_-])", _question_text(question)))]
        if not ids_named or qid in case_qids:
            continue
        if any(_has_branch(row, qid, question) for row in rows if isinstance(row, dict)):
            continue
        add("no_row_for_question", "strategist", qid, qid,
            f"{qid}: this question names {', '.join(ids_named)}, and no answer changes anything: no plan row has a non-empty "
            "branch for a reading of it and no case has a `question_thens` entry for it. Expected: `if_answered[\"" + qid + "\"]` "
            "on the row of the requirement with a patch for at least one reading (for example "
            "`{\"a\": {\"disposition\": \"automate\", \"level\": \"api\"}}`), or a `question_thens` entry in a case. If the answer "
            "really changes nothing, a person's word passes this")
    return out


# --- the executor of the person's gate-A words (t-227b: F16, F17, C1, C4, C10; Lead's 14:00 add) --
# TP1-15045 (cmp2): the person answered Q1-Q6 at gate A and nothing in the factory applied any
# of it - `work/question-answers.jsonl` did not exist, the register read the questions as `named`,
# and the two `accept as blocked` cards promised "S5 then reports exactly these as not executed"
# with no reader behind the promise (FR-8, FR-9). `apply_gate_answers` is that executor. Since DC1-19 it runs inside
# `controller.py --operation gate-decision --gate A` (`_gate_decision_call`), for the conductor and the driver alike, BEFORE the
# decision is built, on the same words,
# so the decision binds the plan as patched (`plan_content_hash` is read from the file at that
# moment; a write AFTER it makes every S5+ dispatch refuse "Gate A plan content changed after
# approval", controller.py `_validate_gate_a_content_current`). It writes ROW-LEVEL changes only: no
# key of the plan's top level is added or removed (C1), and what it did lives in
# `work/question-answers.jsonl`, never in the plan.
# Error direction: it errs toward NOT applying (an answer it cannot read as a whole-line token, two
# answers for one question, a letter beyond the readings, a case it cannot find): each says so in
# one line and the story goes on. It never decides an answer and never undoes the gate decision.

ACCEPT_AS_BLOCKED = "accept as blocked"   # the answer a stand card offers, as the cards print it
ANSWERS_APPLIED = "answers_applied"       # `kind` of the record this executor appends beside the answers


def _applied_records(root: Path) -> list:
    """The `answers_applied` records already in `work/question-answers.jsonl`, [] when none."""
    try:
        import question_register as QR
        text = Path(root).joinpath(*QR.ANSWERS_REL).read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.split("\n"):
        try:
            record = json.loads(line) if line.strip() else None
        except (ValueError, RecursionError):
            continue
        if isinstance(record, dict) and record.get("kind") == ANSWERS_APPLIED:
            out.append(record)
    return out


def _said_disposition(word, waited=False) -> str:
    """A disposition as a person reads it; the word itself when the table does not hold it (FR-13). `waited`: the row held
    `if_answered`, so its `unverifiable` was waiting for an answer (A8, `gate_brief.disposition_word`), not "not verifiable"."""
    try:
        import gate_brief
        if waited:
            return gate_brief.disposition_word(str(word), True) or "unstated"
        return gate_brief.DISPOSITION_WORDS.get(str(word), str(word) or "unstated")
    except Exception:
        return str(word) or "unstated"


# --- the manual-agent pass (t-250 §1, t-261): a row checked by hand becomes EXECUTABLE at gate A ---------------
# Nothing in the factory used to turn a `manual-agent` row's obligations into `decision: manual-agent`
# (TP1-15045: of eleven rows, not one), so `manual_evidence.prepare` refused every one of them and the
# manual agent never ran. The pass lays that decision over the plan in the SAME atomic write as the
# applier's other changes - before the gate decision, so the decision binds the plan as it is (position
# invariant: no plan byte changes after the decision, "Gate A plan content changed after approval" must
# still fire on a later edit). ERROR DIRECTION: toward NOT executable. An obligation becomes
# `manual-agent` only when everything below holds, and otherwise stays as planned with ONE line naming why
# (never a crash, never a silent conversion): `execution_scope: current_task`, `oracle_status: resolved`
# (an unresolved oracle never authorises execution, P20), no unconfirmed expectation on a case that covers
# it (C2: `manual_evidence.expectation_gaps`, the same reader `prepare` uses), an evidence policy that is
# the obligation's own, else the row's, else the level table's (FR-13), and the row still passes
# `coverage_contract.validate_obligations` (C1: a conversion that would invalidate the plan would make the
# person's gate A refused by the controller).
MANUAL_POLICY_PATH = Path(__file__).resolve().parent.parent / "references" / "manual-policy-by-level.json"


def manual_policy_table() -> dict:
    """{level: {"policy": word} or {"refused": words}} from `references/manual-policy-by-level.json` (FR-13).
    `{}` when the file is absent, unreadable or lists no usable level: the pass then converts nothing and says
    so - a table nobody can read is a package defect, never a licence to guess a policy."""
    try:
        levels = json.loads(MANUAL_POLICY_PATH.read_text(encoding="utf-8-sig"))["levels"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if not isinstance(levels, dict):
        return {}
    return {str(level): entry for level, entry in levels.items() if isinstance(entry, dict)
            and ((isinstance(entry.get("policy"), str) and entry["policy"].strip())
                 or (isinstance(entry.get("refused"), str) and entry["refused"].strip()))}


def _plain(text) -> str:
    return " ".join(str(text).split())


def _manual_cases_by_row(root: Path):
    """({plan row id: [(case id, case facts)]}, "") from `contract.case_index`, or (None, why) when the cases
    cannot be read (an identity collision, a malformed front matter)."""
    try:
        import contract
        by_row: dict = {}
        for cid, fact in contract.case_index(Path(root)).items():
            row_id = str(fact.get("plan_row") or "")
            if row_id:
                by_row.setdefault(row_id, []).append((cid, fact))
        return by_row, ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {_plain(exc)[:160]}"


def _unconfirmed_words(root: Path, case_id: str, fact: dict) -> str:
    """"expectation unconfirmed - Q-n: <why>" for a case whose expected result nobody confirmed (C2), or "".
    The words `manual_evidence.prepare` gives for the same case. A reader that fails is a gap too: the error
    direction is toward refusing."""
    try:
        import manual_evidence
        gaps = manual_evidence.expectation_gaps(root, fact)
    except Exception as exc:
        gaps = [("", f"the sources of the case's expected results could not be read ({type(exc).__name__})")]
    if not gaps:
        return ""
    ids = sorted({qid for qid, _ in gaps if qid})
    return ("expectation unconfirmed" + (" — " + ", ".join(ids) if ids else "") + ": "
            + "; ".join(words for _, words in gaps))


def _row_of_nobody(root: Path, profile: str, config: dict, lines: list, where: str, label, rid: str) -> str:
    """The table's words for a profile whose surface nobody drives (`hands: none`), or "" (EP1-41f N-17; t-599 F-14).

    `config` is the caller's lazy cache (`cfg`, `read`): the project config is read once per pass. ERROR DIRECTION: any doubt
    (no config, an unknown profile, a broken table) gives "" - the row is converted as before, never lost; a broken table is
    said once in `lines` when the config itself was read. Writes nothing else."""
    try:
        if not config["read"]:
            config["read"] = True
            import manual_capture
            config["cfg"] = manual_capture.load_config(root)[0]
        if config["cfg"] is not None:
            import surfaces
            table_row = surfaces.row_for_profile(config["cfg"], profile)
            if table_row is not None and table_row.get("hands") == "none":
                return str(table_row.get("words") or "") or "nobody drives this surface"
    except ValueError as exc:
        if config["cfg"] is not None:       # the table, not the config: a factory defect, said once
            lines.append(f"{where}: {label(rid)}: the factory's table of test surfaces could not be read "
                         f"({_plain(exc)[:160]}); this row is handled as before")
    return ""


def _manual_agent_pass(root: Path, rows, where: str, label, lines: list) -> bool:
    """Make the obligations of every `manual-agent` row executable by hand; True when a row changed.

    An obligation whose decision is `unresolved` gets one reason line on both roads (HF4-14 Q-2, AR-19), but only in a run
    that converted a row: the same words applied again change nothing and say nothing.

    Mutates `rows` in place (a row is replaced by its changed copy, never edited half-way) and appends the
    lines the person reads: one per row that changed, one per obligation that stays as planned and why.
    Idempotent: an obligation that already says `manual-agent` is not touched, so the same words applied
    again change nothing. Reads the cases (`contract.case_index`) and the level table; writes nothing."""
    if not isinstance(rows, list):
        return False
    manual = [i for i, r in enumerate(rows) if isinstance(r, dict) and r.get("disposition") == "manual-agent"]
    if not manual:
        return False
    table = manual_policy_table()
    if not table:
        lines.append(f"{where}: the table of evidence rules by level (references/manual-policy-by-level.json) is "
                     "missing or empty, so no check by an agent is made executable here; those rows stay as planned")
        return False
    from coverage_contract import validate_obligations
    from manual_evidence import POLICIES
    by_row, problem = _manual_cases_by_row(root)
    if by_row is None:
        lines.append(f"{where}: the cases could not be read ({problem}), so no check by an agent is made "
                     "executable here; those rows stay as planned")
        return False
    changed, unsettled = False, []
    config = {"cfg": None, "read": False}       # the project config, read once and lazily (EP1-41f, N-17)
    hands_of: dict = {}                         # profile id -> the table row's words when its hands are none, "" otherwise
    for index in manual:
        row = rows[index]
        rid = str(row.get("id") or f"row[{index}]")
        obligations = row.get("coverage_obligations")
        # EP1-41f (N-17): a row whose profile is a surface nobody drives (`hands: none`) is not made `manual-agent`: it stays as
        # planned and the table's words say why (P19 step 4). ERROR DIRECTION: any doubt (no profile, no config, an unknown profile,
        # a broken table) is the old road - the row is converted as before, never lost. Web: the table is not read.
        profile = str(row.get("execution_profile_id") or "").strip()
        if profile and isinstance(obligations, list) and obligations:
            if profile not in hands_of:
                hands_of[profile] = _row_of_nobody(root, profile, config, lines, where, label, rid)
            if hands_of[profile]:
                for ob in obligations:
                    if isinstance(ob, dict):
                        lines.append(f"{where}: {label(rid)}: {str(ob.get('obligation_id') or '?')} stays as planned - "
                                     f"{hands_of[profile]}")
                continue
        if not isinstance(obligations, list) or not obligations:
            lines.append(f"{where}: {label(rid)} is checked by an agent by hand, but the plan lists nothing the "
                         "check must prove for it, so it is not made executable")
            continue
        # C2: the obligations a case with an unconfirmed expectation covers (the same join `prepare` uses:
        # the case's requirements against the obligation's requirement_refs)
        held: dict = {}
        for case_id, fact in by_row.get(rid, []):
            why = _unconfirmed_words(root, case_id, fact)
            if not why:
                continue
            asked = {str(r) for r in fact.get("requirements") or []}
            for ob in obligations:
                refs = {str(ref.get("ref") or "") for ref in (ob.get("requirement_refs") if isinstance(ob, dict) else None) or []
                        if isinstance(ref, dict)}
                if isinstance(ob, dict) and refs & asked:
                    held.setdefault(str(ob.get("obligation_id") or ""), f"{case_id}: {why}")
        work = copy.deepcopy(row)
        made = []
        for ob in work["coverage_obligations"]:
            if not isinstance(ob, dict):
                continue
            oid = str(ob.get("obligation_id") or "?")
            if ob.get("decision") == "unresolved":      # FR-59: the gap is named here, not only at S6 (said below, when a row changed)
                unsettled.append(f"{where}: {label(rid)}: {oid} stays as planned - what the right answer is has not "
                                 "been settled (an unsettled answer never authorises a check)")
                continue
            if ob.get("decision") not in ("new", "extend", "reuse"):
                continue            # manual-agent already (idempotent); manual-human is a person's
            if ob.get("execution_scope") != "current_task":
                lines.append(f"{where}: {label(rid)}: {oid} stays as planned - it is a recommendation for later, "
                             "not part of this story's run")
                continue
            if ob.get("oracle_status") != "resolved":
                lines.append(f"{where}: {label(rid)}: {oid} stays as planned - what the right answer is has not "
                             "been settled (an unsettled answer never authorises a check)")
                continue
            if oid in held:
                lines.append(f"{where}: {label(rid)}: {oid} stays as planned - {held[oid]}")
                continue
            policy = str(ob.get("evidence_policy") or row.get("evidence_policy") or "").strip()
            if policy and policy not in POLICIES:
                lines.append(f"{where}: {label(rid)}: {oid} stays as planned - its evidence rule `{policy}` is not "
                             f"one of {', '.join(sorted(POLICIES))}")
                continue
            if not policy:
                level = str(row.get("level") or "").strip()
                entry = table.get(level)
                if entry is None:
                    lines.append(f"{where}: {label(rid)}: {oid} stays as planned - the level "
                                 f"`{level or 'unstated'}` has no evidence rule in "
                                 "references/manual-policy-by-level.json")
                    continue
                if entry.get("refused"):
                    lines.append(f"{where}: {label(rid)}: {oid} stays as planned - level `{level}`: "
                                 f"{entry['refused']}")
                    continue
                policy = entry["policy"].strip()
                if policy not in POLICIES:
                    lines.append(f"{where}: {label(rid)}: {oid} stays as planned - the table gives level "
                                 f"`{level}` the rule `{policy}`, which is not one of {', '.join(sorted(POLICIES))}")
                    continue
            before = dict(ob)
            ob["decision"], ob["evidence_policy"] = "manual-agent", policy
            try:
                errors = validate_obligations([work])
            except Exception as exc:
                errors = [f"{type(exc).__name__}: {_plain(exc)}"]
            if errors:
                ob.clear()
                ob.update(before)
                # every problem is named (a person decides on the whole list), each cut to 200 characters
                # as before - the cut is the length of one line, not a slice of the list
                said = (_plain(errors[0])[:200] if len(errors) == 1 else
                        f"{len(errors)} problem(s): " + "; ".join(_plain(e)[:200] for e in errors))
                lines.append(f"{where}: {label(rid)}: {oid} stays as planned - made executable by hand the plan "
                             f"would stop passing its own check ({said})")
                continue
            made.append((oid, policy))
        if made:
            rows[index] = work
            changed = True
            lines.append(f"{where}: {label(rid)}: made executable for the agent's check by hand - "
                         + ", ".join(f"{oid} (evidence: {policy})" for oid, policy in made) + ".")
    if changed:     # a run that converted something names the obligations it could not; a repeat of the same words says nothing
        lines.extend(unsettled)
    return changed


def _write_plan_rows(plan_path, document, rows) -> None:
    """The rows back into the plan document, ONE atomic write; no key of the top level is added (C1)."""
    from event_store import atomic_json
    if isinstance(document, dict):
        document["rows"] = rows
    else:
        document = rows
    atomic_json(plan_path, document)


def _pass_failure_line(where: str, exc) -> str:
    """The one sentence both roads say when the manual-agent pass broke (P1: the rows stay as planned)."""
    return (f"{where}: the checks by an agent were not made executable ({type(exc).__name__}: "
            f"{_plain(exc)[:160]}); those rows stay as planned")


MD_COLUMN_OF_KEY = {"disposition_cell": "disposition + reason", "level": "level", "fit": "fit",
                    "question_rename": "disposition + reason"}


def _rerender_plan_cells(task_root, changes: dict, write: bool = True) -> list:
    """Rewrite the cells of the rows an answer moved in `test-plan.md` (C10, O9).

    The strategist wrote the `disposition + reason` cell as a CONDITIONAL (`per Q1: a -> automate api;
    ...`); once the person has answered it is a statement that no longer holds, and the human view must
    say what the plan JSON now says. The same holds for every other column a patch key maps to
    (`MD_COLUMN_OF_KEY`: `level`, `fit`): a patch that changes `level` left the md column on the old
    value while the JSON moved (the E-13 class: two views of one row disagreeing, and the person reads
    the md at gate A). `changes` is {row id: {"disposition_cell": (disposition, reason), "level": v,
    "fit": v}} - only the keys that CHANGED. Only those cells of only those rows are touched; every other
    byte stays, the row count and any total included. A cell that was written in backticks stays in
    them. THE one exception to "code never edits test-plan.md": this function, from the gate-A applier,
    before the decision. Returns the row ids rewritten ([] when the file or the row is not there - the
    JSON is what the pipeline reads).

    RN1-2 (B-1): a fourth key, `question_rename`: [(old id, new id), ...] - the whole-token (`_id_token`) id in the row's
    `disposition + reason` cell becomes the new one, every other byte of the cell stays. It is how the human view follows the
    JSON when code changes the id a row rests on (`new:<n>` -> `Q<m>` in `project_plan`, `Q<m>` -> `Q<n>` in
    `repoint_question_ref`); a cell that names neither is not touched. `write=False` writes nothing and returns the rows whose
    cell WOULD change (the probe `repoint_question_ref` asks before it moves a branch between letters)."""
    if not changes:
        return []
    try:
        import contract
        path = contract.artifact(Path(task_root), "test-plan.md")
        text = path.read_bytes().decode("utf-8")
    except Exception:
        return []
    lines, done, in_table, columns, first = text.splitlines(keepends=True), [], False, None, 0
    for index, raw in enumerate(lines):
        body = raw.rstrip("\r\n")
        stripped = body.strip()
        if stripped.startswith(contract.PLAN_HEADING):
            in_table, columns = True, None
            continue
        if in_table and stripped.startswith("## "):
            break
        if not in_table or not stripped.startswith("|"):
            continue
        cells = G.split_cells(stripped)  # unescaped: a `\|` of the row is a bar of its cell; written back through escape_cell
        if set("".join(cells)) <= set("-: "):
            continue
        if columns is None:
            header = [contract.strip_cell(cell).lower() for cell in cells]
            columns = {key: header.index(name) for key, name in MD_COLUMN_OF_KEY.items() if name in header}
            first = header.index("ts") if "ts" in header else 0
            continue
        if first >= len(cells):
            continue
        rid = contract.strip_cell(cells[first])
        if rid not in changes:
            continue
        touched = False
        for key, value in changes[rid].items():
            column = columns.get(key, -1)
            if column < 0 or column >= len(cells):
                continue
            if key == "question_rename":
                renamed = cells[column]
                for old, new in value:
                    renamed = _id_token(old).sub(lambda _m, _new=new: _new, renamed)
                if renamed == cells[column]:
                    continue
                cells[column] = renamed
            elif key == "disposition_cell":
                disposition, reason = value
                cells[column] = f"`{disposition}`" + (f" — {reason}" if str(reason or "").strip() else "")
            else:
                ticked = cells[column].startswith("`") and cells[column].endswith("`") and len(cells[column]) > 1
                cells[column] = f"`{value}`" if ticked and str(value or "") else str(value if value is not None else "")
            touched = True
        if touched:
            lines[index] = "| " + " | ".join(G.escape_cell(cell) for cell in cells) + " |" + raw[len(body):]
            done.append(rid)
    if done and write:
        path.write_bytes("".join(lines).encode("utf-8"))
    return done


def _drop_question(new_row: dict, row: dict, qid: str) -> dict:
    """`new_row` with `qid` taken out of `if_answered` and `question_refs` (C4: a settled question is no branch), as `row`
    held them; an emptied field leaves the row. Changes and returns `new_row`."""
    ifa = row.get("if_answered") if isinstance(row.get("if_answered"), dict) else {}
    refs = row.get("question_refs") if isinstance(row.get("question_refs"), list) else []
    for field, value in (("if_answered", {k: v for k, v in ifa.items() if k != qid}),
                         ("question_refs", [r for r in refs if r != qid])):
        if value:
            new_row[field] = value
        else:
            new_row.pop(field, None)
    return new_row


def _apply_question_patch(row, qid: str, key: str):
    """THE patch of one answer on one plan row, for gate A and for the late applier alike (m1): a NEW row with the patch
    of `key` (a reading letter or `not_needed`) laid over `row` and `qid` taken out of its `if_answered` / `question_refs`;
    None when `row` has no branch for that answer (no `if_answered[qid]` object, or none of its keys covers `key`) -
    the row is then not touched here. Gate A keeps its own reading of None (the question leaves the row, as authored); the
    late applier leaves the row as it is and hands it to the strategist's rework. Pure."""
    ifa = row.get("if_answered") if isinstance(row, dict) else None
    patch = resolve_patch(ifa.get(qid) if isinstance(ifa, dict) else None, key)
    if patch is None:
        return None
    return _drop_question(apply_patch(row, patch), row, qid)


def _labeller(rows):
    """`label(row id)` -> "TS-3 (what the row is about)" from the plan's gloss; the bare id when it has none."""
    gloss = {}
    try:
        import gate_brief
        gloss = gate_brief.plan_gloss(rows)
    except Exception:
        pass
    return lambda rid: f"{rid} ({gloss[rid]})" if gloss.get(rid) else rid


def _move_effect(head: str, label, rid: str, row: dict, new_row: dict, patch) -> tuple:
    """(the line saying what an answer did to a row, the cells of `test-plan.md` it moved) - ("", {}) when the patch
    changed no value of the row. `head` opens the line ("Q5 = `a`"); the cells are `_rerender_plan_cells`'s keys (O9)."""
    changed = [k for k, v in (patch or {}).items() if row.get(k) != v]
    if not changed:
        return "", {}
    old_d, new_d = str(row.get("disposition") or ""), str(new_row.get("disposition") or "")
    effect = (f"{_said_disposition(old_d, waited=bool(row.get('if_answered')))} becomes {_said_disposition(new_d)}"
              if "disposition" in changed and old_d != new_d else "its plan entry is updated")
    cells = {}
    if "disposition" in changed or "reason" in changed:
        cells["disposition_cell"] = (new_d, str(new_row.get("reason") or ""))
    for name in ("level", "fit"):   # O9: every md column a changed key maps to (MD_COLUMN_OF_KEY)
        if name in changed:
            cells[name] = new_row.get(name)
    return f"{head} - {label(rid)}: {effect}.", cells


def _note_cells(md_changes: dict, rid: str, cells: dict) -> None:
    """Lay one answer's moved cells into `md_changes` (a row two answers move keeps both); an empty set adds nothing."""
    if cells:
        md_changes.setdefault(rid, {}).update(cells)


def _put_unresolved(task_root, rows: list, put) -> tuple:
    """(exit code, text): `manifest_put.py --fragment {unresolved: rows}`. `put(fragment_json)` is the
    caller's own way to run the script from the project root (the driver passes `self.py`); with none,
    the script's `run` is called in this process with its output captured."""
    fragment = json.dumps({"unresolved": rows}, ensure_ascii=False)
    if put is not None:
        code, out = put(fragment)
        return code, str(out or "")
    import contextlib
    import io
    import manifest_put
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            code = manifest_put.run(Path(task_root).name, fragment)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    return code, sink.getvalue().strip()


def apply_gate_answers(task_root, words, where="gate A", by="driver", put=None, shown=None, remedies=None,
                       pass_lines=None, blocked="now") -> list:
    """Apply what the person's gate-A words DECIDE and return the lines to print - never raises.

    1. Closed tokens (`question_register.parse_choices`): `Q5: a` / `Q5: not needed`. Each answered
       question is recorded (`QR.record`, `where`, `by`) and, in every plan row that carries
       `if_answered[Q]`, the patch `resolve_patch` gives for the answer is laid over the row; that
       question leaves the row's `question_refs` and `if_answered` (C4: a settled question is no
       branch). One line per row moved. The plan is written once, row-level, atomically (C1).
    2. `<case id>: manual`: the case's row keeps being checked by hand (its authored `manual-*`
       disposition, else `manual-agent`) - the gate card's own promise; one line per case.
    3. `accept as blocked` on a line that names cases: each case whose row is automated gets an
       `unresolved` row `blocked_by_env` through `manifest_put.py` (instance ids empty: the automator
       names them, t-219), so S5 reports it as not executed instead of running it.
    4. The manual-agent pass (t-250 §1): in the same atomic plan write, every obligation of a `manual-agent`
       row that can be checked by an agent becomes `decision: manual-agent` with its evidence policy
       (`_manual_agent_pass`); what cannot stays as planned with one line saying why.
    Every application appends ONE `answers_applied` record to `work/question-answers.jsonl` (created
    when the story has none yet) - the file the register reads, never a key of the plan.

    Edges: own wording (no token), two answers for one question, a letter beyond the readings, an
    unknown id: nothing applied, one line each. Idempotent: a question that is `answered` already,
    a case decision and an `answers_applied` record already on file are never done twice, so the
    same words applied again (a gate decision that did not record, a relaunch) change nothing.

    `shown` (t-271 F5, t-279 K-HASH): {question id: the fingerprint of the register row the person's CARD carried}
    - `gate_brief.shown_hashes(<the packet text shown>)`. An answer is recorded against THAT hash, so a row that
    changed between the card and the answer reads `changed_since_answer` (the claim stays unconfirmed). With no
    `shown`, or no entry for the question (a caller that does not hold the shown packet yet), the answer is
    recorded against the row as it stands now - which can never detect that change - exactly as it was.

    `remedies` (B-414 F19 (a)): {case id: a remedy} for the cases a LEVEL accept names (`stand_accept_remedies`, the level gap's
    own `remedy`, whole). `_stand_remedy` derives a remedy from the case's OWN preconditions and blocks nothing for a case whose
    preconditions are all met, which left part of a level accept unexecuted (FR-9); a case named here is blocked by that remedy
    instead. A remedy the contract refuses is not used (the derivation answers, as before).

    `pass_lines` (DC1-19): a list the manual-agent pass's lines go into INSTEAD of the returned list, so the caller (the gate-decision
    answer's `manual_pass`) keeps them apart from the answers' lines; None = they are in the returned list, as before.

    `blocked` (DC1-19, B1): when step 3 runs. `"now"` (default) = in this call, as before; `"skip"` = steps 1, 2 and 4 only - the
    manifest is not touched (`manifest_put` commits an event to the journal, which no rollback undoes), so a call that may still
    be refused moves no manifest event; `"only"` = step 3 alone (the caller ran `"skip"` first, and the decision is now certain to
    record): nothing else is read, written or said again."""
    lines: list = []
    try:
        _apply_gate_answers(Path(task_root), words if isinstance(words, str) else str(words or ""),
                            where, by, put, lines, shown if isinstance(shown, dict) else {}, remedies,
                            pass_lines if isinstance(pass_lines, list) else None, blocked)
    except Exception as exc:
        lines.append(f"{where}: the answers could not all be applied ({type(exc).__name__}: "
                     f"{' '.join(str(exc).split())[:160]}); the decision is still recorded, and what was "
                     "not applied stays as the plan has it")
    return lines


def _apply_gate_answers(root: Path, words: str, where: str, by: str, put, lines: list, shown: dict | None = None,
                        remedies: dict | None = None, pass_out: list | None = None, blocked: str = "now") -> None:
    import question_register as QR
    view = QR.load(root)
    questions = [q for q in view.get("questions") or [] if isinstance(q, dict) and q.get("id")]
    known = {q["id"]: q for q in questions}
    try:
        import gate_brief
        cases, _unreadable = gate_brief.story_cases(root)
    except Exception:
        cases = {}
    fulls = list(cases)
    read = QR.parse_choices(words, questions, fulls)
    # F6 (t-269, t-279): a decision the person wrote INSIDE a code block (or after a fence nobody closed) is applied
    # to nothing, and said so - one line each - instead of leaving the answer silently missing. One print serves
    # `accept as blocked` too: `parse_choices` reports every decision-shaped line of a fence, case tokens included.
    if blocked != "only":
        lines.extend(f"{where}: {notice}" for notice in QR.fence_notices(read))
    applied_before = _applied_records(root)
    plan_path = story_plan_path(root)
    document = rows = None
    if plan_path is not None:
        document = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        rows = document.get("rows") if isinstance(document, dict) else document
        rows = rows if isinstance(rows, list) else None
    rows_by_id = {str(r.get("id")): i for i, r in enumerate(rows or []) if isinstance(r, dict) and r.get("id")}
    authored = {rid: str(rows[i].get("disposition") or "") for rid, i in rows_by_id.items()}
    label = _labeller(rows)
    if blocked == "only":       # step 3 alone: the first pass (`blocked="skip"`) did everything else and said it
        _accept_as_blocked(root, where, by, put, lines, cases, fulls, rows, rows_by_id, applied_before, read, known, words, remedies or {})
        return

    def dependents(qid: str) -> list:
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ifa = row.get("if_answered")
            refs = row.get("question_refs")
            if (isinstance(ifa, dict) and qid in ifa) or (isinstance(refs, list) and qid in refs):
                out.append(str(row.get("id") or "?"))
        return out

    # --- 1. the questions ------------------------------------------------------------------------
    todo = [(qid, letter, "answered") for qid, letter in read["choices"].items()]
    todo += [(qid, "", "not_needed") for qid in read["not_needed"]]
    moved_lines, to_record, md_changes, plan_changed, fresh_todo = [], [], {}, False, []
    for qid, letter, status in todo:
        question = known[qid]
        now = str(question.get("status") or "open")
        if now in SETTLED_STATUSES:
            before = str(question.get("reading") or "") if now == "answered" else ""
            if (now == "answered" and status == "answered" and before == letter) or \
                    (now == "not_needed" and status == "not_needed"):
                continue                      # the same answer again: nothing to do (idempotent)
            said = f"`{before}`" if now == "answered" and before else "not needed" if now == "not_needed" else "answered"
            lines.append(f"{where}: {qid} was already settled ({said}), so what you wrote now for it "
                         "changes nothing; the plan keeps following the first answer")
            continue
        key = letter or NOT_NEEDED
        fresh_todo.append((qid, letter))
        moved_rows = []
        for index, row in enumerate(rows or []):
            ifa = row.get("if_answered") if isinstance(row, dict) else None
            entry = ifa.get(qid) if isinstance(ifa, dict) else None
            if not isinstance(entry, dict):
                continue                      # no branch for this question on this row: nothing to apply
            patch = resolve_patch(entry, key)
            new_row = _apply_question_patch(row, qid, key)
            if new_row is None:               # m1 (kept as it is, queued as a finding): no branch for THIS answer here,
                new_row = _drop_question(copy.deepcopy(row), row, qid)   # so the question leaves and the row stays as authored
            rid = str(row.get("id") or f"row[{index}]")
            rows[index] = new_row
            plan_changed = True
            moved_rows.append(rid)
            line, cells = _move_effect(f"{where}: {qid} = {'`' + letter + '`' if letter else 'not needed'}",
                                       label, rid, row, new_row, patch)
            if line:
                moved_lines.append(line)
            _note_cells(md_changes, rid, cells)
        to_record.append((qid, letter, status, moved_rows))
    # `<id>: until the report` (m3, H25): the person keeps the question open on purpose. It is recorded through the same
    # road as an answer (never silently dropped, never read as "no answer of the form"), changes no plan row, and a
    # question that is settled already, or kept open on this very row, is left alone (first answer wins; idempotent).
    kept_open = []
    for qid in read["deferred"]:
        question = known[qid]
        if QR.settled(question):
            lines.append(f"{where}: {qid} was already settled, so what you wrote now for it changes nothing; "
                         "the plan keeps following the first answer")
        elif question.get("status") != QR.DEFERRED or QR.is_open(question):
            kept_open.append(qid)
    if fresh_todo:
        lines.append(f"{where}: answers recorded by code - "
                     + ", ".join(f"{qid}: {letter or 'not needed'}" for qid, letter in fresh_todo))
    # what was not read as an answer, each in one line (F16: the person's own wording changes nothing)
    skipped = set()
    for conflict in read["conflicts"]:
        if conflict["id"] in known:
            skipped.add(conflict["id"])
            lines.append(f"{where}: {conflict['id']} has two different answers ({', '.join(conflict['values'])}); "
                         "nothing is applied for it and it stays open")
    for item in read["out_of_range"]:
        skipped.add(item["id"])
        lines.append(f"{where}: {item['id']}: the letter {item['letter']} is beyond its {item['readings']} "
                     "readings; nothing is applied for it and it stays open")
    if read["unknown_ids"]:
        lines.append(f"{where}: not questions of this story, so nothing is recorded for them: "
                     + ", ".join(read["unknown_ids"]))
    for qid in read["untokened_questions"]:
        if qid in skipped or str((known.get(qid) or {}).get("status") or "open") in SETTLED_STATUSES:
            continue
        rows_on = dependents(qid)
        if rows_on:
            lines.append(f"{where}: {qid} has no answer of the form `{qid}: <letter>` or `{qid}: not needed`, "
                         f"so nothing is applied for it: {named_ids(rows_on, 6, where='the test plan')} stay as planned and the "
                         f"question stays open")
    # --- 2. `<case id>: manual`, in memory like the questions: the plan is written once below ------
    manual_lines, case_records = [], []
    for token in read["case_tokens"]:
        full, decision = token["case"], token["decision"]
        if decision != "manual":
            continue                          # `automate`: the row already says so; nothing to apply (F18)
        if (view.get("case_decisions") or {}).get(full, {}).get("decision") == "manual":
            continue                          # idempotent
        rid = str((cases.get(full) or {}).get("plan_row") or "")
        index = rows_by_id.get(rid)
        if rows is None or index is None:
            manual_lines.append(f"{where}: {full}: no row of the plan holds this case, so there is nothing "
                                "to keep checked by hand; your word is recorded")
        else:
            row = rows[index]
            others = [c for c, v in cases.items() if c != full and str(v.get("plan_row") or "") == rid]
            wanted = authored.get(rid) if str(authored.get(rid) or "").startswith("manual") else "manual-agent"
            if others:
                manual_lines.append(f"{where}: {full}: its row {rid} also holds {', '.join(others[:4])} and a "
                                    "row is checked one way for all its cases, so the row is left as it is; "
                                    "your word is recorded")
            elif str(row.get("disposition") or "") == wanted:
                manual_lines.append(f"{where}: {full}: already kept checked by hand "
                                    f"({_said_disposition(wanted)}); nothing changes")
            else:
                old = str(row.get("disposition") or "")
                rows[index] = dict(row, disposition=wanted)
                plan_changed = True
                manual_lines.append(f"{where}: {full}: {label(rid)} stays checked by hand: "
                                    f"{_said_disposition(old)} becomes {_said_disposition(wanted)}.")
                md_changes[rid] = {"disposition_cell": (wanted, str(row.get("reason") or ""))}
        case_records.append((full, rid))
    # --- 2b. the manual-agent pass (t-250 §1): AFTER the loop above (a row it just made `manual-agent` is
    # converted in the same write) and BEFORE the one plan write below and before the gate decision ----
    pass_lines: list = []
    try:
        if rows is not None and _manual_agent_pass(root, rows, where, label, pass_lines):
            plan_changed = True
    except Exception as exc:    # a pass that breaks never takes the applier's other answers down (P1)
        pass_lines.append(_pass_failure_line(where, exc))
    # --- the plan is written ONCE: row-level, atomic, no key of the top level added (C1) -----------
    if plan_changed and plan_path is not None:
        _write_plan_rows(plan_path, document, rows)
    lines.extend(moved_lines + manual_lines + ([] if pass_out is not None else pass_lines))
    if pass_out is not None:
        pass_out.extend(pass_lines)         # the gate-decision answer's `manual_pass`, apart from the answers' lines
    _rerender_plan_cells(root, md_changes)
    # --- the records, AFTER the plan: a crash between the two leaves the question open, never
    # answered-but-unapplied; the rerun then finds the branch gone and still records the answer ----
    now_ts = QR._now()
    for qid, letter, status, moved_rows in to_record:
        try:
            # the hash of the row AS THE CARD SHOWED IT when the caller holds it; else the row as it stands now
            recorded = QR.record(root, qid, status, words, where, by,
                                 str((shown or {}).get(qid) or "") or known[qid].get("row_hash") or "", reading=letter)
            # `record_at` = the register record of THIS answer, as the late applier writes it: without it `_same_record` matches the
            # record by (id, answer) at ANY time and an answer given at gate A, changed and given again is read as applied (HF3-10, E3)
            QR._append(root, {"kind": ANSWERS_APPLIED, "what": "question", "id": qid,
                              "answer": letter or NOT_NEEDED, "rows": moved_rows, "record_at": recorded["at"], "where": where,
                              "by": by, "at": now_ts})
        except QR.Refused as exc:
            lines.append(f"{where}: {qid} was applied to the plan but could not be recorded as answered "
                         f"({' '.join(str(exc).split())[:160]})")
    for qid in kept_open:
        try:
            QR.record(root, qid, QR.DEFERRED, words, where, by,
                      str((shown or {}).get(qid) or "") or known[qid].get("row_hash") or "")
            lines.append(f"{where}: {qid} is kept open until the report, on your word")
        except QR.Refused as exc:
            lines.append(f"{where}: {qid} could not be kept open ({' '.join(str(exc).split())[:160]})")
    for full, rid in case_records:
        try:
            QR.record_case(root, full, "manual", words, where, by, case_ids=fulls)
            QR._append(root, {"kind": ANSWERS_APPLIED, "what": "case_manual", "id": full, "answer": "manual",
                              "rows": [rid] if rid else [], "where": where, "by": by, "at": now_ts})
        except QR.Refused as exc:
            lines.append(f"{where}: {full}: not recorded ({' '.join(str(exc).split())[:160]})")
    # --- 3. `accept as blocked` -> unresolved rows through manifest_put --------------------------
    if blocked != "skip":
        _accept_as_blocked(root, where, by, put, lines, cases, fulls, rows, rows_by_id, applied_before, read, known,
                           words, remedies or {})


# --- the late-answer applier (HF2-7, TP1-12586): an answer recorded AFTER the plan was written --------------------
# 12586 (24.10.2026): the person answered at the S2/S3 stops and in the conductor's chat, and nothing laid those answers
# over the plan: gate A skipped them as "settled already" and its rehearsal then sent the plan back for branching on a
# question the person had answered - the same answer asked, applied and refused by three readers. `apply_recorded_answers`
# is the one move that reads the recorded answers and applies them, at the stage thresholds and before the rehearsal.
# ERROR DIRECTION (it writes the plan, so it is stricter than gate A): only "not applied". A reading the person did not
# choose is never applied; a changed or `before_value_needed` answer is never applied; the plan row stays byte for byte
# and the owner's rework is named instead. It writes only plan rows (atomic) and `answers_applied` records, and it never
# raises. Records are written AFTER the plan: a crash between them repeats the pass, it never leaves an answer applied
# and unrecorded as applied.

NOT_APPLIED_CHANGED = "changed_since_answer"             # the row changed after the answer
NOT_APPLIED_BEFORE = "before_value_missing"              # the row is unchanged, but the person chose the 'before' reading and nothing writes its value (RN1-11)
NOT_APPLIED_APPROVED = "gate A approved"                 # the person approved the plan: code does not edit it any more
NOT_APPLIED_DIFFERENT = "the plan follows an earlier answer"   # reopened and answered differently: the owner reworks


def plan_intent(record) -> bool:
    """Is `record` (an `answers_applied` record) an answer the plan was asked to follow: applied by code (no `not_applied`) or handed to an
    owner as a rework (`different`) - not one refused (a changed row, an approved plan), not a `before_plan` mark. The ONE definition: the
    applier compares a new answer with the last such record, and the driver replaces a queued rework only by such an answer (HF3-10)."""
    return (isinstance(record, dict) and not record.get("before_plan")
            and (not record.get("not_applied") or record.get("not_applied") == NOT_APPLIED_DIFFERENT))


def _said(question: dict) -> str:
    """The answer a question's winning record gives, as an `answers_applied` record names it: the reading letter,
    `not_needed`, or "" for an answer in the person's own words (no letter: nothing to patch with)."""
    return NOT_NEEDED if question.get("status") == "not_needed" else str(question.get("reading") or "")


def _answer_words(answer: str) -> str:
    """The answer as a person reads it in a line: `b`, `not needed`, or "your own words"."""
    return "`not needed`" if answer == NOT_NEEDED else f"`{answer}`" if answer else "your own words"


def _same_record(rec: dict, qid: str, answer: str, at: str) -> bool:
    """Is `rec` an `answers_applied` record of THIS answer: the same id, the same answer and the same record of it (`at`)?
    A record written before `record_at` existed (gate A up to 0.10.2) has none and matches by (id, answer) (edge 12); gate A writes it
    since HF3-10, so an answer given there, changed and given again is a new answer like any other."""
    return (rec.get("id") == qid and rec.get("answer") == answer
            and (not rec.get("record_at") or rec.get("record_at") == at))


def _plan_state(root: Path) -> tuple:
    """(path, document, rows, problem) of the story's plan: path None when there is no plan yet; `problem` non-empty
    (and rows None) when the plan is there and cannot be read as a list of rows."""
    path = story_plan_path(root)
    if path is None:
        return None, None, None, ""
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        return path, None, None, f"the test plan could not be read ({type(exc).__name__})"
    rows = document.get("rows") if isinstance(document, dict) else document
    if not isinstance(rows, list):
        return path, document, None, "the test plan holds no list of rows"
    return path, document, rows, ""


def _gate_a_state(root: Path) -> tuple:
    """(approved, problem): did the person approve gate A (`contract.gate_approved`, the one reader)? A `pipeline.json`
    that cannot be read is a problem, not an answer - the plan is left alone then."""
    path = root / "pipeline.json"
    if not path.is_file():
        return False, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        return False, f"pipeline.json could not be read ({type(exc).__name__})"
    import contract
    return contract.gate_approved(data if isinstance(data, dict) else {}, "A"), ""


def append_question_ref(task_root, row_id: str, qid: str, case: str = "a case") -> tuple:
    """`(written, line)`: add the register question `qid` to the `question_refs` of plan row `row_id` (HF4-9), the way a
    question raised at S4 reaches the row its case belongs to. Never raises.

    The code writer of `work/test-plan.json` is this module (`_apply_recorded` / `_apply_gate_answers` write it with
    `event_store.atomic_json`; `plan_row.py` is the ROLE's tool); this is one more row-level write through it, ONE
    write of the whole plan, and the row changes in this one field only (appended at the end, no duplicate; a row that
    already names `qid` is not written). The error direction is "the question is never lost": the plan is left as it was,
    and `line` says why, when the plan is absent or unreadable, the gate A approval cannot be read, the plan was approved
    at gate A (the plan the person approved is not changed by code - the same ban `apply_recorded_answers` keeps), the
    plan has no row `row_id`, or the row's `question_refs` is not a list. `line` is "" when nothing needs saying (written,
    or the row names `qid` already)."""
    root = Path(task_root)
    row_id, qid = str(row_id or "").strip(), str(qid or "").strip()
    nothing = f"{qid} was raised for {case}; "
    state, line = _plan_row_for_write(root, row_id, nothing)
    if state is None:
        return False, line
    refs = state.rows[state.index].get("question_refs")
    if qid in [str(ref).strip() for ref in refs or []]:
        return False, ""
    if state.approved:
        return False, nothing + "you have already approved the test plan at gate A, so the plan is unchanged; the question is still asked"
    state.rows[state.index] = dict(state.rows[state.index], question_refs=list(refs or []) + [qid])
    return _write_row_state(state, nothing)


def _plan_row_for_write(root: Path, row_id: str, nothing: str) -> tuple:
    """`(state, "")` or `(None, line)`: the ONE preamble of every row-level write of a question ref (`append_question_ref`,
    `repoint_question_ref`; AR-14): the plan exists and reads, gate A's approval can be read, the row is there and its
    `question_refs` is a list (or absent). `state` carries `path`, `document`, `rows`, `index`, `approved`; the caller applies
    the approval ban only when it owes a write. `nothing` opens every refusal line."""
    path, document, rows, problem = _plan_state(root)
    if path is None:
        return None, nothing + "the story has no test plan yet, so the plan is unchanged"
    if problem:
        return None, nothing + f"{problem}, so the plan is unchanged; the question is still asked"
    approved, why = _gate_a_state(root)
    if why:
        return None, nothing + f"{why}, so the plan is unchanged; the question is still asked"
    index = next((i for i, row in enumerate(rows) if isinstance(row, dict) and str(row.get("id") or "").strip() == row_id), None)
    if not row_id or index is None:
        return None, nothing + "no plan row names it, so the plan is unchanged"
    refs = rows[index].get("question_refs")
    if refs is not None and not isinstance(refs, list):
        return None, nothing + "the row's question_refs is not a list, so the plan is unchanged; the question is still asked"
    return types.SimpleNamespace(path=path, document=document, rows=rows, index=index, approved=approved), ""


def _write_row_state(state, nothing: str) -> tuple:
    """`(written, line)`: the rows of `_plan_row_for_write`'s state back into the plan, ONE `_write_plan_rows` write."""
    try:
        _write_plan_rows(state.path, state.document, state.rows)
    except OSError as exc:
        return False, nothing + f"the plan could not be written ({type(exc).__name__}), so it is unchanged; the question is still asked"
    return True, ""


def _repoint_obstacle(root: Path, row: dict, row_id: str, old: str, new: str) -> str:
    """"" when the branch of `old` may move to `new` on this row, else the first failed condition in words (RN1-2, F-5).

    The judgment that the new question narrows the old one is the case designer's (`replaces`, AR-2); code only checks that
    the move is by MEANING and safe: (a) `old` is on the row and open, (b) both questions say which reading is the behaviour
    now and which the behaviour before (`contract.claim_reading_index`, the one reader: byte-equal to the code's own pair or
    marked by `claim`, else None), (c) the row's reason does not name `old`, (d) there is a branch to move and none yet for
    `new`, (e) the `test-plan.md` cell is not left naming `old` when letters change places. Error direction: any doubt is
    an obstacle (the strategist's rework sets the branch); a letter is never mapped to a letter."""
    import question_register as QR
    refs = [str(ref).strip() for ref in row.get("question_refs") or []]
    if old not in refs:
        return f"{old} is not in the row's question_refs"
    loaded = QR.load(root)
    by_id = {str(q.get("id")).strip(): q for q in loaded.get("questions") or [] if isinstance(q, dict)}
    if old not in by_id or new not in by_id:
        return f"the register does not hold {old if old not in by_id else new}"
    if QR.settled(by_id[old]):
        return f"{old} is already answered"
    letters = {}
    for qid in (old, new):
        for meaning in contract.CLAIM_KEYS:
            index = contract.claim_reading_index(by_id[qid], meaning)
            have = _letters(by_id[qid])
            if index is None or index >= len(have):
                return f"{qid} does not say which of its readings is the behaviour {meaning}"
            letters[(qid, meaning)] = have[index]
    reason = row.get("reason")
    if isinstance(reason, str) and _id_token(old).search(reason):
        return f"the row's reason names {old}"
    branches = row.get("if_answered")
    if not isinstance(branches, dict) or not isinstance(branches.get(old), dict):
        return f"the row has no branch for {old} to move"
    if new in branches:
        return f"the row already has a branch for {new}"
    moved = any(letters[(old, m)] != letters[(new, m)] for m in contract.CLAIM_KEYS)
    if moved and _rerender_plan_cells(root, {row_id: {"question_rename": [(old, "?")]}}, write=False):
        return f"test-plan.md names {old} next to letters that change places"
    return ""


def repoint_question_ref(task_root, row_id: str, old_qid: str, new_qid: str, case: str = "a case") -> tuple:
    """`(written, line)`: a question raised at S4 that the case designer DECLARED it replaces (`replaces`, item 5) takes the
    place of `old_qid` on plan row `row_id`: the ref, and the branch `if_answered[old_qid]` moved to `new_qid` BY MEANING
    (the patch under the old question's letter for `now` goes under the new question's letter for `now`, the same for
    `before`; `*` and `not_needed` are copied), the `test-plan.md` cell renamed. Written only when `_repoint_obstacle` finds
    none; otherwise it is today's `append_question_ref` and the line says why the strategist's rework sets the branch.
    Never raises; the same bans as `append_question_ref` (they are one preamble)."""
    root = Path(task_root)
    row_id, old_qid, new_qid = (str(x or "").strip() for x in (row_id, old_qid, new_qid))
    nothing = f"{new_qid} was raised for {case}; "
    state, line = _plan_row_for_write(root, row_id, nothing)
    if state is None:
        return False, line
    row = state.rows[state.index]
    if new_qid in [str(ref).strip() for ref in row.get("question_refs") or []]:
        return False, ""
    if state.approved:
        return append_question_ref(root, row_id, new_qid, case)
    try:
        why = _repoint_obstacle(root, row, row_id, old_qid, new_qid)
    except Exception as exc:  # noqa: BLE001 - never a raise for the plan's sake
        why = f"the question could not be compared ({type(exc).__name__})"
    if why:
        written, note = append_question_ref(root, row_id, new_qid, case)
        said = (f"{new_qid} raised for {case} replaces {old_qid} on {row_id}, but {why}; the strategist's rework sets the branch")
        return written, said + (f" ({note})" if note else "")
    import question_register as QR
    by_id = {str(q.get("id")).strip(): q for q in QR.load(root).get("questions") or [] if isinstance(q, dict)}
    mine = {m: (_letters(by_id[old_qid])[contract.claim_reading_index(by_id[old_qid], m)],
                _letters(by_id[new_qid])[contract.claim_reading_index(by_id[new_qid], m)]) for m in contract.CLAIM_KEYS}
    old_branch = row["if_answered"][old_qid]
    moved = {new_letter: copy.deepcopy(old_branch[old_letter]) for old_letter, new_letter in mine.values() if old_letter in old_branch}
    moved.update({key: copy.deepcopy(old_branch[key]) for key in (ANY_READING, NOT_NEEDED) if key in old_branch})
    state.rows[state.index] = dict(row,
                                   question_refs=[new_qid if str(ref).strip() == old_qid else ref for ref in row["question_refs"]],
                                   if_answered={(new_qid if key == old_qid else key): (moved if key == old_qid else value)
                                                for key, value in row["if_answered"].items()})
    written, line = _write_row_state(state, nothing)
    if written:
        _rerender_plan_cells(root, {row_id: {"question_rename": [(old_qid, new_qid)]}})
    return written, line


# --- the door for a question the register does not hold (RN1-2, item 3) -------------------------------------------------
# The strategist has no tool to raise a question (it writes the plan and nothing else), so a row that rests on a question
# the register lacks used to be written with an invented id and refused after S3 closed. A row names it `new:<n>` in
# `question_refs` and describes it in its own `new_questions` entry; the S3 exit judges the plan with the entry as a question
# of the register (`plan_questions_view`, on a COPY: nothing is written by a check, FR-45) and `project_plan` raises it when
# S3 closes - the S4 exit's `raise_for_case` is its twin (AR-19).

NEW_ENTRY_FORM = ("question, source_says (a list of {quote, where}), readings (two or more, each {reading, from, if_chosen}), "
                  "severity, owner_role")


def question_owners() -> tuple:
    """The `owner_role` words of an open question: `question_owners` of `handoffs/vocabulary.yaml` (FR-13), read through
    `handoff.allowed` (the existing reader, AR-13), THE one list for `check_witness` (readiness form) and `_new_question_flaws`.
    () when the file cannot be read or holds no word: a package defect, which `owner_role_flaw` then names (never a pass, AR-28)."""
    try:
        import handoff
        return tuple(handoff.allowed("question_owners"))
    except Exception:  # noqa: BLE001
        return ()


def owner_role_flaw(value) -> str:
    """`""` when `value` is one of `question_owners()`, else ONE sentence, the same text for every caller. An empty value is a flaw
    too (each caller keeps its own wording of the empty case and asks this only for a non-empty one)."""
    owners = question_owners()
    if not owners:
        return ("owner_role cannot be checked: `question_owners` of handoffs/vocabulary.yaml is unreadable or empty "
                "(a package defect: tell the conductor)")
    if str(value or "") in owners:
        return ""
    return f"owner_role {str(value or '')!r} is not one of {'|'.join(owners)} (vocabulary.question_owners)"


def _new_question_flaws(entry: dict) -> list:
    """What is wrong with one `new_questions` entry as a question, as plain sentences ([] when a person can answer it)."""
    flaws = list(contract.question_errors(dict(entry, id="Q0")))
    flaws += [f"{field} is empty" for field in ("severity", "owner_role") if not str(entry.get(field) or "").strip()]
    if str(entry.get("owner_role") or "").strip():     # an empty one is named above; a listed word is the one list's (`question_owners`)
        flaws += [flaw for flaw in (owner_role_flaw(entry.get("owner_role")),) if flaw]
    return flaws


def _row_new_entries(row: dict, rid: str, problems: list) -> dict:
    """`{key: (position, entry)}` of the usable `new_questions` entries of one row; each unusable one is a problem
    `(row id, key, sentence)`. A key is usable when it has the form `new:<n>` (n from 1 to 99) and is not repeated in the row."""
    entries = row.get("new_questions")
    if not _carries(entries):
        return {}
    if not isinstance(entries, list):
        problems.append((rid, "", f"{rid}: new_questions must be a list of entries. Expected: {NEW_ENTRY_FORM}"))
        return {}
    keys: dict = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append((rid, "", f"{rid}: new_questions[{position}] is not an object. Expected: {NEW_ENTRY_FORM}"))
            continue
        key = str(entry.get("key") or "").strip()
        if not NEW_REF.fullmatch(key):
            problems.append((rid, key, f"{rid}: new_questions[{position}] has key {key!r}. Expected: \"new:<n>\" with n from 1 to 99"))
            continue
        if key in keys:
            problems.append((rid, key, f"{rid}: new_questions[{position}] repeats the key {key}. Expected: one entry per key in a row"))
            continue
        keys[key] = (position, entry)
        for flaw in _new_question_flaws(entry):
            problems.append((rid, key, f"{rid}: new_questions[{position}] ({key}): {flaw}. Expected: {NEW_ENTRY_FORM}"))
    return keys


def plan_questions_view(rows) -> tuple:
    """`(scoped rows, virtual questions, problems)`: the plan as the S3 exit judges it when rows name questions that are not in
    the register yet. A `new:<n>` key is local to its row, while `variant_errors` matches ids over the whole plan, so the view
    is a DEEP COPY in which the `new:<n>` of a row (in `question_refs` and as an `if_answered` key) becomes `new:<n>@<row id>`
    when the row has its entry, and each usable entry is a virtual OPEN question of that id with the entry's readings. A
    `new:<n>` with no entry in ITS OWN row is left as it is (`unresolved_ref`); one that is no key at all (`new:100`) is a
    problem and is left out of the copy (one fact, one line). `problems`: `(row id, key, sentence)` for an entry that is
    not usable, and for an entry no `question_refs` of its row names. Pure: the argument is not touched."""
    if not isinstance(rows, list):
        return rows, [], []
    scoped, virtual, problems = copy.deepcopy(rows), [], []
    for index, row in enumerate(scoped):
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or f"row[{index}]")
        keys = _row_new_entries(row, rid, problems)
        flagged: set = set()

        def scope(name):
            """The name for the copy: the scoped id, itself, or None (a malformed `new:` key, reported once)."""
            token = str(name).strip()
            if not token.startswith("new:"):
                return name
            if not NEW_REF.fullmatch(token):
                if token not in flagged:
                    flagged.add(token)
                    problems.append((rid, token, f"{rid}: `{token}` is not a key of a new question. Expected: \"new:<n>\" with n from 1 to 99"))
                return None
            return f"{token}@{rid}" if token in keys else token
        if isinstance(row.get("question_refs"), list):
            scoped_refs = [scope(ref) if isinstance(ref, str) else ref for ref in row["question_refs"]]
            row["question_refs"] = [ref for ref in scoped_refs if ref is not None]
        if isinstance(row.get("if_answered"), dict):
            scoped_keys = {key: scope(key) for key in row["if_answered"]}
            row["if_answered"] = {scoped_keys[key]: value for key, value in row["if_answered"].items() if scoped_keys[key] is not None}
        for key, (position, entry) in keys.items():
            virtual.append({"id": f"{key}@{rid}", "status": "open", "question": entry.get("question"),
                            "source_says": entry.get("source_says"),
                            "readings": copy.deepcopy(entry.get("readings")) if isinstance(entry.get("readings"), list) else []})
            if key not in {ref.strip() for ref in (rows[index].get("question_refs") or []) if isinstance(ref, str)}:
                problems.append((rid, key, f"{rid}: new_questions[{position}] ({key}) is named by no question_refs of the row. "
                                           f"Expected: \"{key}\" in question_refs, or the entry removed"))
    return scoped, virtual, problems


def _declares_new(rows) -> bool:
    """Does any row carry `new_questions` or a `new:` ref (a question the S3 close owes the register)?"""
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        refs = row.get("question_refs")
        if _carries(row.get("new_questions")) or any(
                isinstance(ref, str) and ref.strip().startswith("new:") for ref in (refs if isinstance(refs, list) else ())):
            return True
    return False


def _unscoped(finding: dict, virtual: list) -> dict:
    """The finding with each `new:<n>@<row id>` of the view said as the author wrote it, `new:<n>`."""
    out = dict(finding)
    for item in sorted(virtual, key=lambda q: -len(q["id"])):
        short = item["id"].split("@", 1)[0]
        out["message"] = out["message"].replace(item["id"], short)
        if out.get("question") == item["id"]:
            out["question"] = short
    return out


def s3_branch_refusals(task_root, rows, view=None) -> tuple:
    """`(findings, why_unread)`: what the S3 exit says of the plan's question branches (RN1-2); never raises.

    `findings`: the kinds of `S3_EXIT_KINDS` (refused) and of `S3_WARN_KINDS` (a WARN), from `variant_errors` over the rows with
    no case, plus the problems of the rows' `new_questions` (as `bad_branch`); a declared `new:<n>` is a question of the view.
    Invariants: an id the register does not hold never passes (a register of ZERO questions makes every ref `unresolved_ref`);
    a register that cannot be read while a row carries refs is `why_unread`, never `[]` (FR-59); a check that raises is
    `why_unread` too. A plan with no branch field (dated before ORACLE_CUTOFF) and no `new_questions` says nothing (builder
    rule 9). `view` is `plan_questions_view(rows)` when the caller has it already."""
    try:
        scoped, virtual, problems = view if view is not None else plan_questions_view(rows)
        found = [{"kind": "bad_branch", "owner": "strategist", "where": rid, "question": key,
                  "message": f"{text} - {BRANCH_WAY['strategist']}"} for rid, key, text in problems]
        created = plan_created(task_root)
        if not has_branch_fields(scoped, (), created):
            return found, ""
        import question_register as QR
        loaded = QR.load(task_root)
        questions = list(loaded.get("questions") or [])
        carried = any(isinstance(row, dict) and (_carries(row.get("question_refs")) or _carries(row.get("if_answered")))
                      for row in (scoped if isinstance(scoped, list) else []))
        if carried and (not loaded.get("register_present") or (loaded.get("problems") and not questions)):
            why = ((loaded.get("problems") or [""])[0]
                   or "the story has no work/requirements-readiness.json")
            return found, f"question branches could not be checked: the register's questions could not be read ({why})"
        mode, version = story_contract_mode(task_root)
        every = variant_errors(scoped, questions + virtual, (), plan_contract_mode=mode, coverage_contract_version=version,
                               plan_created=created)
    except Exception as exc:  # noqa: BLE001 - an unknown is not a pass
        return [], f"question branches could not be checked ({type(exc).__name__}: {str(exc)[:160]})"
    return found + [_unscoped(item, virtual) for item in every if item.get("kind") in S3_EXIT_KINDS + S3_WARN_KINDS], ""


def _raise_new_questions(root: Path, rows: list) -> tuple:
    """`({(row id, key): "Q<m>"}, problems)`: every usable `new_questions` entry of `rows` raised in the register, in
    plan order, ONE `_write_readiness` for the batch, under the answers lock. The register row is `question_register.
    _question_row` (the one shaper); `raised_for` = `{row, origin: "S3-plan", key, digest}` where the digest is that of the
    entry's question, quotes and readings: the SAME entry (a rerun after a crash) finds its question, and a DIFFERENT later
    `new:1` of the same row is a new question and never silently takes the earlier id (B-3; `_raise` refuses a changed
    before/now, here the plan is past the exit, so it raises afresh). The plan is NOT touched here."""
    import hashlib
    import claim_projector as CP        # the ONE reader of the readiness file (lazy: claim_projector imports this module)
    import question_register as QR
    made, problems = {}, []
    with QR.answers_lock(root):
        try:
            path, data, listed = CP.read_readiness(root)
        except CP._Carrier as exc:
            return {}, [f"{exc}: the S3 plan's new questions were not raised"]
        current, fresh, top = list(listed), [], 0
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or f"row[{index}]")
            for key, (_position, entry) in _row_new_entries(row, rid, []).items():
                question = {name: entry[name] for name in QR.QUESTION_KEYS if name in entry}
                digest = hashlib.sha256(json.dumps([question.get("question"), question.get("source_says"), question.get("readings")],
                                                   sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:12]
                new_row, earlier = QR._question_row(current + fresh, question,
                                                    {"row": rid, "origin": "S3-plan", "key": key, "digest": digest}, taken=top)
                if earlier is not None:
                    made[(rid, key)] = earlier["id"]
                    continue
                fresh.append(new_row)
                made[(rid, key)] = new_row["id"]
                top = max(top, int(new_row["id"][1:]))
        if fresh:
            data["open_questions"] = current + fresh
            try:
                QR._write_readiness(path, data)
            except OSError as exc:
                return {}, [f"{path.name} could not be written ({type(exc).__name__}): the S3 plan's new questions were not raised"]
    return made, problems


def _rename_new_refs(rows: list, made: dict) -> tuple:
    """`(rows, renames)`: the rows with each raised `new:<n>` replaced by its `Q<m>` in `question_refs` (same position) and as
    the `if_answered` key, and the entry taken out of `new_questions` (the key goes when it is empty). `renames`:
    `{row id: [(new:<n>, Q<m>)]}` for the human view. Pure."""
    out, renames = copy.deepcopy(rows), {}
    for index, row in enumerate(out):
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or f"row[{index}]")
        mine = {key: qid for (owner, key), qid in made.items() if owner == rid}
        if not mine:
            continue
        renames[rid] = list(mine.items())
        if isinstance(row.get("question_refs"), list):
            row["question_refs"] = list(dict.fromkeys(mine.get(ref.strip(), ref) if isinstance(ref, str) else ref
                                                      for ref in row["question_refs"]))
        if isinstance(row.get("if_answered"), dict):
            row["if_answered"] = {mine.get(str(key).strip(), key): value for key, value in row["if_answered"].items()}
        left = [e for e in row.get("new_questions") or [] if not (isinstance(e, dict) and str(e.get("key") or "").strip() in mine)]
        if left:
            row["new_questions"] = left
        else:
            row.pop("new_questions", None)
    return out, renames


def project_plan(task_root, reopening: bool = False) -> types.SimpleNamespace:
    """Write what code owes the S3 plan when S3 closes (RN1-2): the revision mark (`stamp_revision`) and the register
    questions the rows declared as `new:<n>`. `SimpleNamespace(wrote, problems)`; never raises. `reopening`: the TICKET re-run of
    S3 (`story_run.Driver.s3_ticket_completion`) - gate A's approval is on the OLD text and the driver reopens it right after this
    stage (`ticket_reopen_gate_a`), so the approval ban does not apply (B-2); every other caller keeps the ban.

    The check at the exit is pure; THIS is the writer, called from the driver's S3 projection step (`story_run.Driver.
    s3_project`, the seam of the claim projection, AR-15). Nothing owed -> nothing written (a plan with no new question and
    every row marked passes through unchanged). A plan that is absent: nothing. A plan that cannot be read, gate A already
    approved while a write is owed (the same ban `append_question_ref` keeps), a `new_questions` entry that is not usable or a
    `new:<n>` without its entry, a register that cannot be read or written: a PROBLEM line and nothing is written - never a plan
    that S4 reads with a `new:` ref (FR-59, AR-28). Order: register first, plan second, the human view last: a crash in between
    leaves a question no row names, never a row naming a missing question; a rerun converges (`raised_for`)."""
    out = types.SimpleNamespace(wrote=False, problems=[])
    try:
        root = Path(task_root)
        path, document, rows, problem = _plan_state(root)
        if path is None:
            return out
        if problem:
            out.problems.append(f"{problem}; the revision mark and the plan's new questions were not written")
            return out
        mode, _version = story_contract_mode(root)
        stamped = stamp_revision(rows, mode)
        declared = _declares_new(rows)
        if not declared and stamped == rows:
            return out
        approved, why = _gate_a_state(root)
        if why or (approved and not reopening):
            out.problems.append(why or "gate A is approved: code does not change the plan the person approved (the revision mark "
                                       "or a new question is owed). Door: the person sends the plan back at gate A (a rework of S3 with "
                                       "their words reopens the approval), and the mark and the question are written when S3 closes again")
            return out
        made, renames = {}, {}
        if declared:
            view = plan_questions_view(stamped)
            # a `new:` ref the view left unscoped has no entry in its own row; an entry with a problem is named by the view
            dangling = [text for _rid, _key, text in view[2]] + [
                f"{row.get('id')}: `{ref}` has no entry in new_questions" for row in view[0] if isinstance(row, dict)
                for ref in (row.get("question_refs") if isinstance(row.get("question_refs"), list) else ())
                if isinstance(ref, str) and ref.startswith("new:") and "@" not in ref]
            if dangling:
                out.problems.append("the plan's new questions are not usable (" + "; ".join(dangling[:5]) + "). Door: the conductor sends S3 back to the "
                                   "test planner for these rows (a rework of S3 with these lines as the reason); a person's waiver of the exit "
                                   "line does not make them usable")
                return out
            import question_register as QR
            try:
                made, problems = _raise_new_questions(root, stamped)
            except QR.Refused:
                out.problems.append("another writer holds the answers lock: the plan's new questions were not raised; the driver repeats the step")
                return out
            if problems:
                out.problems.extend(problems)
                return out
            stamped, renames = _rename_new_refs(stamped, made)
        _write_plan_rows(path, document, stamped)
        out.wrote = True
        if renames:
            _rerender_plan_cells(root, {rid: {"question_rename": pairs} for rid, pairs in renames.items()})
    except Exception as exc:  # noqa: BLE001 - a projection step never raises over story data
        out.problems.append(f"the S3 plan projection could not finish ({type(exc).__name__}: {str(exc)[:160]})")
    return out


def _case_rework(cases: dict, question: dict, key, answer: str, at: str) -> list:
    """The designer's rework for the answer: every case with a `question_thens` entry on `question` that does not carry the
    text for the recorded answer (`case_entry_answers`) - exactly the cases `variant_errors` calls `settled_question`."""
    out = []
    qid = str(question.get("id") or "").strip()
    for cid, case in cases.items():
        entries = [e for e in (case.get("thens") or []) if isinstance(e, dict) and str(e.get("question") or "").strip() == qid]
        if entries and not all(case_entry_answers(e, key, question) for e in entries):
            out.append({"owner": "designer", "where": str(cid), "question": qid, "answer": answer, "record_at": at})
    return out


def _late_note(question: dict) -> str:
    """The line for an answer that is not applied because it no longer holds: the gate's own note for it
    (`gate_brief.question_note`, the one writer of that text), the plain sentence when it cannot be made."""
    try:
        import gate_brief
        note = gate_brief.question_note(question)
    except Exception:
        note = ""
    return f"{question.get('id')}: {note or 'its text changed after your answer, so it is asked again'}"


def _row_branches(rows: list, qid: str):
    """(index, row, entry) of every plan row that holds an `if_answered[qid]` OBJECT - the rows an answer to `qid` is
    laid over. A row whose `if_answered` or whose entry is no object is a shape finding (`bad_branch`), not touched here."""
    for index, row in enumerate(rows):
        ifa = row.get("if_answered") if isinstance(row, dict) else None
        entry = ifa.get(qid) if isinstance(ifa, dict) else None
        if isinstance(entry, dict):
            yield index, row, entry


def _apply_to_rows(rows: list, qid: str, key, answer: str, at: str, label, md_changes: dict) -> tuple:
    """Lay the answer over the plan rows in memory: (ids of the rows moved, their lines, the strategist's rework). A row
    with no branch for the answer (or any row when the answer has no letter) stays byte for byte and is named for rework."""
    moved, lines, rework = [], [], []
    branched = set()

    def unprepared(rid):
        # R5 (run 3): every row that rests on the answer is either moved or NAMED - the person was told "recorded" and a row
        # that stays byte for byte with no word is the promise broken in silence (P22)
        rework.append({"owner": "strategist", "where": rid, "question": qid, "answer": answer, "record_at": at})
        lines.append(f"{rid}: your answer {qid} = {_answer_words(answer)} has no prepared change in the test plan, "
                     "so the test planner reworks this row")

    for index, row, entry in _row_branches(rows, qid):
        rid = str(row.get("id") or f"row[{index}]")
        branched.add(index)
        new_row = _apply_question_patch(row, qid, key) if key else None
        if new_row is None:
            unprepared(rid)
            continue
        rows[index] = new_row
        moved.append(rid)
        line, cells = _move_effect(f"{qid} = {_answer_words(answer)}", label, rid, row, new_row, resolve_patch(entry, key))
        if line:
            lines.append(line)
        _note_cells(md_changes, rid, cells)
    for index, row in enumerate(rows):
        # a row that names the question in `question_refs` and holds no `if_answered[qid]` OBJECT was never yielded above (E-A7:
        # one that was is not named twice)
        refs = row.get("question_refs") if isinstance(row, dict) else None
        if index not in branched and isinstance(refs, list) and qid in refs:
            shape = row.get("if_answered")
            if shape is not None and not isinstance(shape, dict):
                continue  # a shape finding (an `if_answered` that is no object) is not ours: skipped, never a crash (D1-A)
            if isinstance(shape, dict) and qid in shape and not isinstance(shape[qid], dict):
                continue  # the other half of the shape finding: `if_answered[qid]` present and no object (Q2 t-1752)
            unprepared(str(row.get("id") or f"row[{index}]"))
    return moved, lines, rework


def _late_record(question: dict, rows: list, **flags) -> dict:
    """The `answers_applied` record of one answer: what was done to which rows, keyed by (id, answer, record_at)."""
    return {"kind": ANSWERS_APPLIED, "what": "question", "id": question["id"], "answer": _said(question),
            "rows": rows, "record_at": question["at"], **flags}


def apply_recorded_answers(task_root, where, by="driver") -> dict:
    """Apply the answers recorded in `work/question-answers.jsonl` that the plan does not follow yet - never raises.

    Returns {"lines": [what a person or the next role is told], "rework": [{"owner": "strategist" | "designer", "where":
    row or case id, "question": id, "answer": letter | "not_needed" | "", "record_at": the answer's record, "was": the earlier answer the
    plan was written for - only on the rework of a CHANGED answer}], "applied":
    [the `answers_applied` records written]}. Per answered question, in the register's order (`QR.settled` decides, the
    one definition; `QR.answer_key` is the answer's key):
      - the answer was applied already (an `answers_applied` record with the same id, answer and `record_at`): nothing;
      - the row changed since (`not_applied: changed_since_answer`), or it did not and its `before` value is missing
        (`not_applied: before_value_missing`) (`not settled`): not applied, one record and one line - the question is
        asked again;
      - no plan yet: one mark `before_plan`; the first pass after the plan exists applies it (the mark is no key);
      - the plan or `pipeline.json` cannot be read: one line, nothing written, the next pass tries again;
      - gate A approved: not applied, `not_applied: gate A approved`, one line; the plan is the one the person approved;
      - the plan was asked to follow an earlier answer (an `intent`: a record with no `not_applied`, or `not_applied:
        the plan follows an earlier answer`; the LAST one is what a new answer is compared with) and the new answer is
        ANOTHER one (reopened): the plan is not patched; the owner reworks every row ANY intent moved (`rows`) or handed
        to the strategist (`rework_rows`) and the cases without the new answer's text, each rework record saying `was`
        (the intent's answer), one line, one `not_applied` record carrying the `rework_rows` (HF3-10, H41);
      - the last intent has the SAME answer, recorded again (asked again after a change): one record with no rows. An
        answer in the person's own words given twice is the exception: the code does not read words (FR-12), so it
        reworks as for another answer;
      - else every plan row with an `if_answered[id]` object gets `_apply_question_patch` and leaves the question; a
        row with no branch for the answer stays byte for byte and is named for the strategist; a case whose
        `question_thens` entry lacks the answer's text is named for the designer. The plan is written once, atomically,
        then the records; a second call finds them and returns nothing."""
    out = {"lines": [], "rework": [], "applied": []}
    try:
        _apply_recorded(Path(task_root), where, by, out)
    except Exception as exc:
        out["lines"].append(f"your recorded answers could not all be applied ({type(exc).__name__}: "
                            f"{' '.join(str(exc).split())[:160]}); the test plan is as it was")
    return out


def _apply_recorded(root: Path, where: str, by: str, out: dict) -> None:
    import question_register as QR
    answered = [q for q in QR.load(root).get("questions") or []
                if isinstance(q, dict) and q.get("id") and q.get("status") in SETTLED_STATUSES]
    if not answered:
        return
    lines, rework = [], []          # handed to `out` only when the pass got through: a failed write reports nothing it did not do
    before = [r for r in _applied_records(root) if r.get("what") == "question"]
    records, pending = [], []
    for q in answered:
        qid, answer, at = q["id"], _said(q), q["at"]
        if any(_same_record(r, qid, answer, at) and not r.get("before_plan") for r in before):
            continue
        if not QR.settled(q):
            # RN1-11: two causes, two honest labels - the row changed after the answer, or it did not and the value of the
            # "before" reading it chose is still missing (a person reads "changed" as "my answer was lost to an edit")
            cause = NOT_APPLIED_CHANGED if q.get("changed_since_answer") is True else NOT_APPLIED_BEFORE
            records.append(_late_record(q, [], not_applied=cause))
            lines.append(_late_note(q))
        else:
            pending.append(q)
    plan_changed, md_changes = False, {}
    path, document, rows, problem = _plan_state(root) if pending else (None, None, None, "")
    approved, pipeline_problem = _gate_a_state(root) if pending else (False, "")
    problem = problem or pipeline_problem
    if problem:
        lines.append(f"{problem}, so your recorded answers are not applied to it yet; the plan is as it was and they are "
                     "tried again at the next stop")
    elif pending and path is None:
        records += [_late_record(q, [], before_plan=True) for q in pending
                    if not any(_same_record(r, q["id"], _said(q), q["at"]) for r in before)]
    elif pending and approved:
        for q in pending:
            records.append(_late_record(q, [], not_applied=NOT_APPLIED_APPROVED))
            lines.append(f"{q['id']}: you have already approved the test plan at gate A, so your answer is recorded but "
                         "does not change the plan.")
    elif pending:
        label = _labeller(rows)
        try:
            import gate_brief
            cases = gate_brief.story_cases(root)[0]
        except Exception:
            cases = {}
        for q in pending:
            qid, answer, at, key = q["id"], _said(q), q["at"], QR.answer_key(q)
            # the answers the plan was asked to follow, in order: applied by code (no `not_applied`) or handed to an owner as a rework
            # (`different`) - NOT the ones refused (changed row, approved plan). The last of them is what a new answer is compared with.
            intents = [r for r in before if r.get("id") == qid and plan_intent(r)]
            prior = intents[-1] if intents else None
            # an answer in the person's own words, given again: the code cannot tell whether the words changed (FR-12), so it
            # reworks - the error goes toward carrying the person's words out (FR-8), never toward dropping them (HF3-10, F7)
            again_in_words = prior is not None and answer == "" and prior.get("answer") == ""
            if prior is not None and (prior.get("answer") != answer or again_in_words):
                was = str(prior.get("answer") or "")
                old = _answer_words(was)
                if again_in_words:
                    lines.append(f"{qid}: you answered in your own words again; the test planner reworks the parts that followed "
                                 "your earlier words.")
                else:
                    lines.append(f"{qid}: your answer is now {_answer_words(answer)}, but the test plan was written for {old}; "
                                 f"the test planner reworks the parts that followed {old}.")
                # every row ANY answer the plan was asked to follow moved or handed to the strategist (HF3-10, F2/F4)
                moved_before = dict.fromkeys(rid for r in intents for field in ("rows", "rework_rows")
                                             if isinstance(r.get(field), list) for rid in r[field] if isinstance(rid, str))
                rework += [{"owner": "strategist", "where": rid, "question": qid, "answer": answer, "record_at": at, "was": was}
                           for rid in moved_before]
                rework += [dict(w, was=was) for w in _case_rework(cases, q, key, answer, at)]
                records.append(_late_record(q, [], not_applied=NOT_APPLIED_DIFFERENT, rework_rows=list(moved_before)))
            elif prior is not None:
                records.append(_late_record(q, []))          # asked again on a changed row, answered the same: the branch is gone
            else:
                moved, moved_lines, row_rework = _apply_to_rows(rows, qid, key, answer, at, label, md_changes)
                plan_changed = plan_changed or bool(moved)
                lines += moved_lines
                rework += row_rework + _case_rework(cases, q, key, answer, at)
                records.append(_late_record(q, moved, rework_rows=[w["where"] for w in row_rework]))
    if plan_changed:
        from event_store import atomic_json
        if isinstance(document, dict):
            document["rows"] = rows
        else:
            document = rows
        atomic_json(path, document)
        _rerender_plan_cells(root, md_changes)
    now_ts = QR._now()
    for record in records:
        try:
            QR._append(root, dict(record, where=where, by=by, at=now_ts))
            out["applied"].append(record)
        except (OSError, QR.Refused) as exc:
            lines.append(f"{record['id']}: your answer could not be noted as applied ({type(exc).__name__}); it is tried again "
                         "at the next stop")
    out["lines"].extend(lines)
    out["rework"].extend(rework)


def _unmet_preconditions(root, items: list) -> list:
    """The items of a case that the rehearsal's own classifier does NOT read as met: it is
    `gate_preflight.Rehearsal._check_one_precondition` run again, with no network (an `http` item is not probed
    here, so it reads `error` and stays), so the card and this derivation can never disagree about what `met`
    means (FR-10). `met` (an env variable the runner reads, an account the stand records) and `seeded` (the case
    creates it) leave; `unmet`, `uncheckable` (prose `none`, a login wall) and `error` stay - an item nobody
    proved met is not one the person's word may leave out of the block (FR-41: the error direction is toward
    keeping what was declared). If the classifier itself cannot be built, every item stays."""
    try:
        import gate_preflight
        rehearsal = gate_preflight.Rehearsal(Path(root), "A")
        ctx = {"responses": {}, "timeout": 0.0, "values": {}, "files": [], "how": "", "base": "",
               "dead": "not probed when the answer is applied"}
        try:
            ctx["files"], ctx["how"] = rehearsal._loaded_env_files()
            ctx["values"] = rehearsal._env_names(ctx["files"])
        except Exception as exc:
            ctx["env_error"] = f"the runner's env files could not be read ({type(exc).__name__}: {exc})"
        ctx["base"] = rehearsal._api_base_url(ctx["values"])
    except Exception:
        return list(items)
    kept = []
    for item in items:
        try:
            state = rehearsal._check_one_precondition(item, ctx)[0]
        except Exception:
            state = "error"
        if state not in ("met", "seeded"):
            kept.append(item)
    return kept


def _stand_remedy(full: str, case, line: str, root=None) -> tuple:
    """(remedy, partitions) of a case the person accepted as blocked at gate A (O7); `(None, [])` when what the
    stand lacks cannot be derived, and then NOTHING is blocked for the case (t-279 F4, FR-41).

    The card promised "S5 reports exactly these as not executed"; that holds only when the manifest row
    carries a remedy (`acceptance.blocked_instances`: no remedy, no block). Derived from the case's OWN
    precondition items - what the stand lacks is what the designer declared the case needs - and only from
    the items that are not met (`_unmet_preconditions`, whatever their check): an item the stand holds
    (PC-1 `HOME` is set) is never blocked with the one it lacks (PC-2), which used to put the partitions of a
    met item into the block. `kind` is that of the FIRST such item through
    `contract.REMEDY_KIND_OF_PRECONDITION` (feature_flag->flag, data->data, account->credential,
    env->credential, service->service), `where` = `<case> preconditions <PC ids>`, `change` = the items'
    `what`, joined; `partitions` = the union of theirs (the TC_014 card names 2 of 4), and none when any
    such item names none - the whole case is blocked. A case that DECLARES preconditions and has no unmet
    one (all met, or the case creates all it needs), a kind the table does not hold, or a remedy the contract
    refuses: `(None, [])` - the kind is "not derivable", which the caller says in one line, instead of the
    guessed kind `data` with the person's own words as the change that this used to write as a fact.

    A case that declares NOTHING (a story older than the `preconditions` field, or a field that cannot be
    read) has no item to derive from either way: it keeps today's `data` kind with the person's own line as
    the change - the one fallback left, for stories in flight (builder-rules 9); it is the open question in
    the t-279 report whether it too should become "not derivable"."""
    fallback = {"kind": "data", "where": f"{full} preconditions", "change": " ".join(str(line).split())[:300]}
    try:
        import contract
        import gate_preflight
        text = Path(case["path"]).read_text(encoding="utf-8")
        items, errors = gate_preflight.parse_preconditions(gate_preflight.case_preconditions_raw(text))
        if errors or not items:
            return fallback, []
        asked = _unmet_preconditions(root, items) if root is not None else list(items)
        if not asked:
            return None, []
        kind = contract.REMEDY_KIND_OF_PRECONDITION.get(str(asked[0].get("kind") or ""))
        if not kind:
            return None, []
        remedy = {"kind": kind,
                  "where": f"{full} preconditions " + ", ".join(str(it.get("id") or "?") for it in asked),
                  "change": "; ".join(" ".join(str(it.get("what") or "").split()) for it in asked)[:400]}
        if contract.remedy_errors(remedy):
            return None, []
        if any(not it.get("partitions") for it in asked):
            return remedy, []
        return remedy, list(dict.fromkeys(str(p) for it in asked for p in it["partitions"]))
    except Exception:
        return fallback, []                   # a case that cannot be read at all: as before, never a crash


def _accept_as_blocked(root, where, by, put, lines, cases, fulls, rows, rows_by_id, applied_before, read, known,
                       words, remedies=None) -> None:
    """`<case id>: accept as blocked` -> an `unresolved` row `blocked_by_env` through manifest_put (O6, O7, O8).

    The token is read by `question_register.parse_choices` as a WHOLE line (`case_tokens`): the old reading
    took the SUBSTRING `accept as blocked` anywhere in a line and blocked every case id it named, so
    "TC_014: do not accept as blocked" blocked TC_014 and "TC_014: accept as blocked; TC_015 runs" blocked
    TC_015 too, while the card's own words ("accept them as blocked") applied nothing (FR-12, FR-9). A line
    that talks about `blocked` and is no token is told the form in one line and applies nothing; a case
    word the register cannot place (a short id of two cases, an id that is no case) and a case with two
    different words are named in one line each."""
    import question_register as QR
    done = {r.get("id") for r in applied_before if r.get("what") == "accept_as_blocked"}
    fresh = []
    in_fence = False
    for raw in QR._lines(words):
        if QR._is_fence(raw):
            in_fence = not in_fence
            continue
        if in_fence or raw.lstrip(QR.SPACES).startswith(">"):
            continue
        content = QR._content(raw)
        if content.startswith(">"):
            continue
        found = QR._TOKEN.fullmatch(content)
        is_token = bool(found) and found.group("id") not in known and bool(QR._CASE_DECISION.fullmatch(found.group("value")))
        if not is_token and re.search(r"\bblocked\b", raw, re.IGNORECASE):
            shown = " ".join(raw.split())
            shown = shown[:60] + ("…" if len(shown) > 60 else "")
            lines.append(f"{where}: \"{shown}\" is not an answer the factory reads, so nothing is blocked for it; "
                         f"to accept a case as blocked write `<full case id>: {ACCEPT_AS_BLOCKED}` on a line of its "
                         "own, with nothing else on it")
    for item in read["unresolved_short_ids"]:
        near = item["candidates"]
        lines.append(f"{where}: `{item['id']}` is "
                     + (f"{len(near)} cases ({', '.join(near[:4])}), so nothing is applied for it; write the full case id"
                        if near else "not a case of this story, so nothing is applied for it"))
    for conflict in read["conflicts"]:
        if conflict["id"] in fulls:
            lines.append(f"{where}: {conflict['id']} has two different words ({', '.join(conflict['values'])}); "
                         "nothing is applied for it")
    for token in read["case_tokens"]:
        if token["decision"] != ACCEPT_AS_BLOCKED:
            continue
        full = token["case"]
        line = f"{token['written']}: {ACCEPT_AS_BLOCKED}"
        if full in done:
            continue                          # idempotent: this card was applied before
        rid = str((cases.get(full) or {}).get("plan_row") or "")
        index = rows_by_id.get(rid)
        title = " ".join(str((cases.get(full) or {}).get("title") or "").split())
        who = f"{full} ({title})" if title else full
        if rows is None or index is None:
            lines.append(f"{where}: {who} is not in the plan (no row holds it), so nothing is blocked for it")
            continue
        disposition = str(rows[index].get("disposition") or "")
        if disposition != "automate":
            # O8: `manual-human` is a check by a person - there is nothing for S5 to block. `manual-agent` is
            # NOT that: the agent that checks it by hand will still try it on the stand as it is, so the
            # old "nothing to block" told the person their word covered a check it does not cover.
            if disposition == "manual-agent":
                lines.append(f"{where}: {who} is not run by an automated test ({_said_disposition(disposition)}), so "
                             "S5 blocks nothing for it, and the agent that checks it by hand will still try it on "
                             "the stand as it is; your word is recorded")
            else:
                lines.append(f"{where}: {who} is not run by an automated test ({_said_disposition(disposition)}), "
                             "so there is nothing to block; your word is recorded")
            fresh.append((full, rid, False, line, None, []))
            continue
        given = (remedies or {}).get(full)
        if isinstance(given, dict) and not contract.remedy_errors(given):
            remedy, partitions = dict(given), []          # a level accept blocks the whole case by the level's own remedy (F19)
        else:
            remedy, partitions = _stand_remedy(full, cases.get(full), line, root)
        if remedy is None:
            # FR-41: what the stand lacks cannot be derived (every precondition is met or created by the case,
            # or they cannot be read), so no kind is guessed and nothing is blocked; the person's word is kept.
            lines.append(f"{where}: {who}: the kind of what the stand lacks is not derivable (every precondition of "
                         "the case is met or created by the case itself, or they cannot be read), so nothing is "
                         "blocked for it and S5 runs it; your word is recorded")
            fresh.append((full, rid, False, line, None, []))
            continue
        fresh.append((full, rid, True, line, remedy, partitions))
    rows_out = [dict({"case": full, "reason": "blocked_by_env",
                      "detail": "accepted as blocked by the person at " + where + ": " + line,
                      "remedy": remedy}, **({"partitions": partitions} if partitions else {}))
                for full, _rid, run, line, remedy, partitions in fresh if run]
    if rows_out:
        code, out = _put_unresolved(root, rows_out, put)
        from manifest_put import outcome
        put_kind, move = outcome(code, Path(root).name)
        if put_kind != "committed":
            cases_out = ", ".join(r["case"] for r in rows_out)
            if put_kind == "stale":    # exit 4: the rows ARE in the journal, only the manifest's projection failed
                lines.append(f"{where}: the blocked cases are recorded in the journal but the automation manifest's "
                             f"projection is stale ({' '.join(out.split())[-160:]}); S5 will run {cases_out} "
                             f"unless `{move}` is run first")
            else:
                lines.append(f"{where}: the blocked cases could not be written to the automation manifest "
                             f"({' '.join(out.split())[-160:]}); S5 will run {cases_out} unless the automator is told")
            fresh = [item for item in fresh if not item[2]]
        else:
            for full, rid, run, _line, _remedy, partitions in fresh:
                if run:
                    lines.append(f"{where}: {full}: accepted as blocked"
                                 + (f" for {', '.join(partitions)}" if partitions else "")
                                 + " - S5 reports "
                                 + ("those partitions" if partitions else "it") + " as not executed instead of running "
                                 + ("them." if partitions else "it."))
    for full, rid, run, line, _remedy, _partitions in fresh:
        try:
            QR._append(root, {"kind": ANSWERS_APPLIED, "what": "accept_as_blocked", "id": full,
                              "answer": ACCEPT_AS_BLOCKED, "rows": [rid], "words": line, "where": where,
                              "by": by, "at": QR._now()})
        except OSError as exc:
            lines.append(f"{where}: {full}: not recorded ({type(exc).__name__})")


def missing_branch_line(finding) -> str:
    """The `where: it rests on question` line a person quotes to pass a missing-branch finding: the ONE formatter. The
    S3 exit prints it as its example, and the S4 rehearsal reads an S3 word that quotes it (t-721 3.6, K2-5)."""
    return f"{finding['where']}: it rests on {finding['question']}"


def register_fence(task_root, rows, extra_questions=()) -> dict:
    """What the plan owes the register at the S3 exit (GW1-41, G2-15). Never raises: a fence that cannot finish is
    `state: unknown` with its `why` (FR-59, AR-28), so a failure of the fence never hides the refusals the old checks found.

    `extra_questions` (RN1-2, B-6): the virtual questions of `plan_questions_view` (a row's declared `new:<n>`), taken as OPEN
    questions beside the register's own - with `rows` of that view - so a candidate defect whose row rests on a declared
    new question is planned, as it will be after `project_plan` raised it.

    `{"state": "rows" | "empty" | "unknown" | "window_one", "why": str, "missing": [{id, where}], "by_reference": [ids],
    "candidates": [candidate dicts without a planned test], "waiting": [{id, question}]}`. In window 1 of S3 (labelling) the
    role may not write the plan, so nothing is read (FR-2); window 2 always passes the fence."""
    out = {"state": "rows", "why": "", "missing": [], "by_reference": [], "candidates": [], "waiting": []}
    try:
        from exit_gate import _s3_window_one      # lazy (exit_gate imports this module); an unknown answers False = the fence runs
        if _s3_window_one(Path(task_root)):
            out.update(state="window_one", why="register fence: not read in window 1 of S3; window 2 writes the plan")
            return out
        root = Path(task_root)
        register_path = contract.artifact(root, "requirements-register.md")
        view = contract.register_fence_view(register_path)
        if view["state"] == "unknown":
            out.update(state="unknown", why=view["why"])
            return out
        if view["state"] == "empty":
            out["state"] = "empty"
            return out
        ids = view["ids"]
        md_path = contract.artifact(root, "test-plan.md")
        md_known = Path(md_path).is_file()
        md_rows = contract.parse_plan(md_path) if md_known else []
        out["missing"] = requirements_without_row(rows, md_rows, ids, md_known)
        gone = {item["id"] for item in out["missing"]}
        out["by_reference"] = [rid for rid in requirements_by_reference_only(rows, ids) if rid not in gone]
        questions: list = []
        try:
            import question_register
            questions = list(question_register.load(root).get("questions") or [])
        except Exception:     # noqa: BLE001  (questions that cannot be read: no branch counts, the error goes toward the refusal)
            questions = []
        questions = questions + list(extra_questions)
        out["candidates"] = candidates_without_row(rows, contract.candidate_defects(contract.read_text(register_path)), questions)
        if has_branch_fields(rows, (), plan_created(root)):      # a story written before branches existed is never refused for one
            out["waiting"] = requirements_waiting_without_branch(rows, questions, ids)
    except Exception as exc:       # noqa: BLE001
        return {"state": "unknown", "why": f"the register fence could not complete ({type(exc).__name__}: {exc})",
                "missing": [], "by_reference": [], "candidates": [], "waiting": []}
    return out


def fence_lines(fence: dict) -> list:
    """[(header, [lines])] of the fence's refusals, in print order. Texts are the package's, English, one physical line each."""
    blocks = []
    plan_side = [item["id"] for item in fence["missing"] if item["where"] == "plan"]
    md_side = [item["id"] for item in fence["missing"] if item["where"] == "md"]
    if plan_side:
        blocks.append((f"REJECT — {len(plan_side)} requirement(s) of the register have no plan row; each would leave the story unseen "
                       "at gate A (a question's answer would have no row to change):",
                       [f"{rid}: this requirement of the register has no row in the test plan. Expected: a row that names {rid} in "
                        f"`requirements` in work/test-plan.json and in the `R` column of test-plan.md. If it waits for a gate A question: "
                        "`disposition: unverifiable`, `question_refs: [\"Q2\"]` and `if_answered[\"Q2\"]` with a key for every reading "
                        "letter (or `*`) and `not_needed`; the reading that keeps it in scope sets a disposition that gets a case. If it "
                        "should not be checked: `disposition: skip` with the reason, and the person sees that row at gate A. A "
                        "`not_planned` entry does not stand in for a row." for rid in plan_side]))
    if md_side:
        blocks.append((f"REJECT — {len(md_side)} requirement(s) of the register are named in work/test-plan.json but not in test-plan.md:",
                       [f"{rid}: this requirement of the register is named in work/test-plan.json but not in the `R` column of "
                        "test-plan.md; the person reads and the delivery trace follows that table. Expected: the same id in the `R` "
                        "cell of the row." for rid in md_side]))
    if fence["candidates"]:
        blocks.append((f"REJECT — {len(fence['candidates'])} candidate defect(s) of the register have no planned test:",
                       [f"{c['r']}: the register marks this requirement `bug:candidate-defect`, and no row plans a test for it. "
                        f"Expected: a row naming {c['r']} with `disposition: automate` or `manual-agent`; or, while a gate A question "
                        "decides it, `unverifiable` with `question_refs` and an `if_answered` reading that sets `automate` or "
                        "`manual-agent`. When the requirements do not state the expected result: `oracle_unknown: true` and a "
                        "question; the current code is never the expected result." for c in fence["candidates"]]))
    if fence["waiting"]:
        blocks.append((f"REJECT — {len(fence['waiting'])} requirement(s) wait for a gate A question and no answer would change their row:",
                       [f"{w['id']} waits for {w['question']}, and no row of it has a non-empty branch for {w['question']}. Expected: "
                        f"`if_answered[\"{w['question']}\"]` on the row with a patch for at least one reading; or, if no answer "
                        "changes the row, a person's word: the waiver line below." for w in fence["waiting"]]))
    return blocks


def _branch_block_lines(findings: list) -> list:
    """The REJECT block of the plan's question-branch problems (RN1-2): a header, then one `- ` line per finding in its own
    message (already in FR-1 form), grouped by kind in `BRANCH_KINDS` order. [] when there is none."""
    if not findings:
        return []
    order = {kind: place for place, kind in enumerate(BRANCH_KINDS)}
    lines = [f"REJECT — {len(findings)} question-branch problem(s) of the plan rows; at gate A an answer would not move the plan as "
             "written. Repair them now, while S3 still holds the context:"]
    lines += ["- " + one_line(item["message"]) for item in sorted(findings, key=lambda item: order.get(item["kind"], len(order)))]
    return lines


def _regression_findings(task_root) -> list:
    """RG1-2: the problems of the plan's `## Recommended regression` (`regression_scope.problems`, the one checker), as lines for the
    S3 exit. No `test-plan.md` on disk: `[]` (other checks answer for the plan file). A check that cannot run is a WARN line and
    `[]`, never `UNREADABLE` and never a finding: the regression is a recommendation and never holds a story (P24)."""
    try:
        if not (Path(task_root) / "test-plan.md").is_file():
            return []
        import regression_scope   # lazy: it reaches git; an exit that never gets here pays nothing
        import runtime_paths
        project = runtime_paths.project_for_task(task_root)
        return regression_scope.problems(task_root, project, regression_scope.project_config(project))
    except Exception as exc:  # noqa: BLE001
        print(one_line(f"WARN regression check could not run: {type(exc).__name__}: {exc}"))
        return []


# --- TQ1-21: the test an `extend` / `param` / `reuse` builds on is in the project's working tree --------------------------------
# S3 twin of `s5_plan._extends_problem` / `_project_file` (AR-19): both resolve through `probe_by_code._test_path` (AR-15). This side
# answers existence only (language-agnostic, P2); the function after `::` stays S5's. Error direction: absent / unknown, never `exists`.

FIT_TARGET_REFUSED = ("absent", "folder", "outside", "unnamed")     # the states a person's word is needed for


def _path_shaped(token) -> bool:
    """Does a target token look like a file path? A separator in its file part, or an extension of the `code_extensions` data
    (`test_files.is_code_file`; AR-1). Unknown extension data: only a separator counts (a framework id such as `com.acme.cart`
    is then never refused for its dots)."""
    file_part = str(token).partition("::")[0]
    if "/" in file_part or "\\" in file_part:
        return True
    import test_files
    return test_files.is_code_file(file_part) is True


def fit_words_with_target() -> tuple:
    """The `fit_to_shapes` words of `handoffs/vocabulary.yaml` whose shape list has no `new`: the fit words that name an existing
    test (`extend`, `param` today; AR-1, the words are data). A vocabulary that cannot be read, or holds none: `ValueError` (the
    caller turns it into the unknown branch; no word known is never "no target to check")."""
    import handoff
    try:
        mapping = handoff.vocabulary().get("fit_to_shapes")
    except OSError as exc:
        raise ValueError(f"handoffs/vocabulary.yaml cannot be read ({type(exc).__name__})") from exc
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("handoffs/vocabulary.yaml has no `fit_to_shapes`")
    words = tuple(str(key) for key, shapes in mapping.items() if isinstance(shapes, list) and "new" not in [str(s) for s in shapes])
    if not words:
        raise ValueError("handoffs/vocabulary.yaml `fit_to_shapes` has no word that names an existing test")
    return words


def split_fit(fit) -> tuple:
    """`(word, target)` of a `fit` cell: the first whitespace token and the REST, stripped (a target may hold spaces). Not a string
    or blank: `("", "")`."""
    if not isinstance(fit, str) or not fit.strip():
        return "", ""
    parts = fit.strip().split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


def _clean_file(text) -> str:
    """The file part as the code reads it: `\\` is `/`, stripped, one leading `./` removed."""
    file = str(text).replace("\\", "/").strip()
    return file[2:] if file.startswith("./") else file


def _textual_problem(file):
    """`(state, why)` for a file text that is refused on the TEXT alone (no filesystem touch: nothing outside the base is ever stat'ed),
    else None. Empty or a control character: `unnamed`; absolute in either flavour (a drive, a root, UNC), a `~` first segment or any
    `..` segment: `outside`."""
    from pathlib import PurePosixPath, PureWindowsPath
    if not file:
        return "unnamed", "the file name is empty"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in file):
        return "unnamed", "the file name holds a control character"
    windows = PureWindowsPath(file)
    if PurePosixPath(file).is_absolute() or windows.drive or windows.root:
        return "outside", "an absolute path; the path is read from the project root"
    segments = file.split("/")
    if segments[0] == "~":
        return "outside", "a home-folder path; the path is read from the project root"
    if ".." in segments:
        return "outside", "a `..` segment leaves the working tree"
    return None


def _is_folder(root, cfg, file) -> bool:
    spots = [root / file]
    try:
        import probe_by_code as PB
        spots.append(root / PB._profile_cwd(cfg, file) / file)
    except Exception:  # noqa: BLE001  (a profile that cannot be read only means: not looked there)
        pass
    for spot in spots:
        try:
            if spot.is_dir():
                return True
        except (OSError, ValueError):
            pass
    return False


def base_test_file(project, cfg, target) -> dict:
    """Is the test a plan names a file of the project's working tree (the base S5 writes into)? `{state, file, selector, path, why}`;
    state is `exists | absent | folder | outside | unnamed | unknown`. `path` is the file as the code resolved it (project-relative,
    `/`, actual casing) when it exists. The textual checks run first and touch no file; the lookup is `probe_by_code._test_path` (the
    survivor S5 calls). ERROR DIRECTION: this may err toward `absent` / `unknown`, NEVER toward `exists`. Pure (FR-45)."""
    text = target if isinstance(target, str) else ""
    head, _sep, selector = text.partition("::")
    file = _clean_file(head)
    out = {"state": "", "file": file, "selector": selector.strip(), "path": "", "why": ""}
    problem = _textual_problem(file)
    if problem:
        return {**out, "state": problem[0], "why": problem[1]}
    if project is None or not Path(project).is_dir():
        return {**out, "state": "unknown", "why": "the project's working tree is not found"}
    root = Path(project)
    cfg = cfg if isinstance(cfg, dict) else {}
    try:
        import probe_by_code as PB
        try:
            found, _cwd = PB._test_path(root, cfg, {"file": file})
        except PB.Refusal as exc:
            words = str(exc)
            if words.startswith("no file"):
                return {**out, "state": "folder" if _is_folder(root, cfg, file) else "absent"}
            return {**out, "state": "unknown", "why": one_line(words)[:200]}
        resolved, base = found.resolve(), root.resolve()
        if not resolved.is_relative_to(base):
            return {**out, "state": "outside", "why": "resolves outside the working tree - a link?"}
        return {**out, "state": "exists", "path": resolved.relative_to(base).as_posix()}
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        return {**out, "state": "unknown", "why": f"the lookup failed ({type(exc).__name__}: {one_line(exc)[:120]})"}


def target_context(task_root, project=None, cfg=None, candidates=None) -> dict:
    """What the target checks of ONE plan share: the fit words (a `ValueError` out), the project (None when not found), its config,
    the bundle's candidate records and why the bundle was not read, and the per-token cache (one stat per token per call)."""
    words = fit_words_with_target()
    import runtime_paths
    if project is None:
        try:
            project = runtime_paths.project_for_task(task_root)
        except (ValueError, OSError):
            project = None
    if cfg is None:
        import hooklib
        cfg = (hooklib.read_json(Path(project) / runtime_paths.HOME / "config.json", {}, kind=dict) if project is not None else {})
    bundle_why = ""
    if candidates is None:
        import branch_accounting
        candidates, bundle_why = branch_accounting.bundle_candidate_records(task_root)
        candidates = candidates or []
    return {"words": words, "project": project, "cfg": cfg, "candidates": candidates, "bundle_why": bundle_why, "cache": {}}


def _resolve_candidate(ctx, candidate) -> dict:
    """A bundle candidate to a working-tree file: ONE try - the configured checkout of its repository when the config names one,
    else its `path` from the project root. The candidate's `selector` is the result's."""
    path = _clean_file(candidate.get("path") or "")
    selector = str(candidate.get("selector") or "").strip()
    out = {"file": path, "selector": selector, "path": "", "via": "candidate", "state": "", "why": ""}
    if not path:
        return {**out, "state": "unnamed", "why": f"candidate {candidate.get('candidate_id')} names no path"}
    problem = _textual_problem(path)
    if problem:
        return {**out, "state": problem[0], "why": problem[1]}
    project = ctx["project"]
    if project is None or not Path(project).is_dir():
        return {**out, "state": "unknown", "why": "the project's working tree is not found"}
    repo = str(candidate.get("repo") or candidate.get("repo_id") or "").strip()
    joined = path
    try:
        folder = None
        if repo:      # an EMPTY id never reaches `_checkout_path` (it would match a config entry that has no id)
            import handoff_check
            folder = handoff_check._checkout_path(repo, ctx["cfg"], Path(project))
        if folder is not None:
            try:
                rel = folder.relative_to(Path(project).resolve())
            except ValueError:
                return {**out, "state": "outside", "why": f"the checkout of {repo} is not inside the project's working tree"}
            joined = path if rel.as_posix() == "." else f"{rel.as_posix()}/{path}"
    except (OSError, ValueError, ImportError) as exc:
        return {**out, "state": "unknown", "why": f"the checkout of {repo} could not be read ({type(exc).__name__})"}
    found = base_test_file(project, ctx["cfg"], joined + (f"::{selector}" if selector else ""))
    return {**out, **found, "via": "candidate"}


def _resolve_token(ctx, token) -> dict:
    """A target token: a candidate id of the bundle (whole, stripped) is a candidate, anything else a path. One lookup per token."""
    cache = ctx["cache"]
    if token not in cache:
        candidate = next((c for c in ctx["candidates"] if str(c.get("candidate_id") or "").strip() == token), None)
        if candidate is not None:
            cache[token] = _resolve_candidate(ctx, candidate)
        elif ctx["bundle_why"] and not _path_shaped(token):    # an id of a bundle nobody can read: the machine's fault, never a REJECT (FR-46)
            cache[token] = {"file": token, "selector": "", "path": "", "via": "path", "state": "unknown", "why": ctx["bundle_why"]}
        else:
            found = {**base_test_file(ctx["project"], ctx["cfg"], token), "via": "path"}
            if ctx["bundle_why"] and found["state"] != "exists":
                found["why"] = "; ".join(part for part in (found["why"], ctx["bundle_why"] + ", so the token was read as a path") if part)
            cache[token] = found
    return dict(cache[token])


def _fit_target(ctx, row):
    if not isinstance(row, dict):
        return None
    word, target = split_fit(row.get("fit"))
    if word not in ctx["words"]:
        return None
    head = {"row": str(row.get("id") or ""), "word": word, "target": target}
    if not target:
        return {**head, "file": "", "selector": "", "path": "", "state": "unnamed", "why": "the fit names no test", "via": "path"}
    return {**head, **_resolve_token(ctx, target)}


def fit_target(task_root, row, *, project=None, cfg=None, candidates=None, ctx=None):
    """The state of the test a plan row's `fit` (`extend <test>` / `param <test>`) builds on: `{row, word, target, file, selector, path,
    state, why, via}`, or None when the row has no such fit word. Pure: reads files, writes nothing (FR-45). The ONE reader of the
    `fit` target, called by the S3 exit and by `brief_pack` (AR-13). `ctx` is a `target_context` a caller of many rows builds once."""
    if not isinstance(row, dict):
        return None
    return _fit_target(ctx or target_context(task_root, project, cfg, candidates), row)


def _reuse_targets(ctx, row) -> list:
    found = []
    obligations = row.get("coverage_obligations") if isinstance(row, dict) else None
    if not isinstance(obligations, list):
        return found
    rid = str(row.get("id") or "")
    for obligation in obligations:
        if not isinstance(obligation, dict) or obligation.get("decision") != "reuse":
            continue
        links = obligation.get("coverage_links")
        for index, link in enumerate(links if isinstance(links, list) else []):
            if not isinstance(link, dict):
                continue
            where = " ".join(part for part in (rid, str(obligation.get("obligation_id") or ""), f"coverage_links[{index}]") if part)
            candidate_id, ref = str(link.get("candidate_id") or "").strip(), str(link.get("test_ref") or "").strip()
            head = {"row": rid, "word": "reuse", "where": where}
            if candidate_id:
                found.append({**head, "target": candidate_id, **_resolve_token(ctx, candidate_id)})
            elif ref:
                if _path_shaped(ref):
                    found.append({**head, "target": ref, **_resolve_token(ctx, ref)})
                else:
                    found.append({**head, "target": ref, "file": "", "selector": "", "path": "", "state": "not_a_path", "why": "", "via": "path"})
    return found


def _target_line(where, found) -> str:
    """One refusal line (FR-1): what is wrong, what was expected, the doors."""
    word, target, state = found["word"], found["target"], found["state"]
    file = found.get("file") or target
    what = {"absent": f"no file at {file} under the project root or the run folder of its profile",
            "folder": f"{file} is a folder, not a test file",
            "outside": f"{file} is outside the project's working tree ({found.get('why')})",
            "unnamed": f"it names no test file ({found.get('why')})"}[state]
    if found.get("why") and state == "absent":
        what += f" ({found['why']})"
    if word == "reuse":
        expected = ("`test_ref: <path from the project root>::<name>` or a `candidate_id` of work/context-bundle.json; "
                    "or plan the obligation `extend`/`new`")
    else:
        expected = (f"the test as it is in the working tree, `{word} <path from the project root>[::<name>]`, or a candidate id of "
                    "work/context-bundle.json; when the test exists only in the change under test, `fit: new` with "
                    f"`fit_absent: {json.dumps(target, ensure_ascii=False)}` - the new test then writes the page objects and helpers it needs.")
    return one_line(f"{where}: `{word} {target}` - {what}. Expected: {expected}")


def _patch_findings(ctx, row, rid, take, seen):
    """The `if_answered` patches of ONE row that set a different `fit`: laid over the row, each target is taken once per (row, question,
    patched fit) - several answer keys of one entry with the same fit are one finding, another ROW's same patch is its own."""
    ifa = row.get("if_answered")
    for qid, entry in (ifa.items() if isinstance(ifa, dict) else []):
        if not isinstance(entry, dict):
            continue
        for key in entry:
            patch = resolve_patch(entry, key)
            if not patch or "fit" not in patch or patch.get("fit") == row.get("fit"):
                continue
            found = _fit_target(ctx, apply_patch(row, patch))
            mark = (rid, str(qid), str(patch.get("fit")))
            if found and mark not in seen:
                seen.add(mark)
                take(found, f"{rid} if_answered[{qid}][{key}]")


def fit_target_findings(task_root, rows) -> tuple:
    """`(refused, warn_lines, why_unread)` of the targets of the plan rows; never raises. `refused`: `{where, state, line}` for a state in
    `absent | folder | outside | unnamed`; `warn_lines` (no `WARN ` prefix): one per `unknown` and ONE aggregate for the framework-id
    `reuse` links; `why_unread` when the check itself could not run. Walks each row as written, each `if_answered` patch that sets
    `fit` (laid over the row as `plan_warnings` does), and the row's `reuse` links. No target-bearing row: `([], [], "")`."""
    try:
        if not isinstance(rows, list):
            return [], [], ""
        ctx = target_context(task_root)
        refused, warns, not_paths, seen = [], [], [], set()

        def take(found, where):
            state = found["state"]
            if state in FIT_TARGET_REFUSED:
                refused.append({"where": where, "state": state, "line": _target_line(where, found)})
            elif state == "unknown":
                warns.append(one_line(f"{where}: `{found['word']} {found['target']}` could not be checked in the project's working tree "
                                      f"({found['why']}); S4 writes its case as new and S5 checks the test again."))
            elif state == "not_a_path":
                not_paths.append(where)

        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or f"row[{index}]")
            found = _fit_target(ctx, row)
            if found:
                take(found, rid)
            _patch_findings(ctx, row, rid, take, seen)
            for found in _reuse_targets(ctx, row):
                take(found, found["where"])
        if not_paths:
            warns.append(f"{len(not_paths)} reuse link(s) name a test by a framework id, not a file ({', '.join(not_paths[:3])}): "
                         "not checked at S3; S5 joins them to the discovery inventory.")
        return refused, warns, ""
    except Exception as exc:  # noqa: BLE001
        return [], [], one_line(f"plan targets could not be checked ({type(exc).__name__}: {str(exc)[:160]})")


def fit_target_block(refused) -> list:
    """The REJECT block of the S3 exit for `fit_target_findings` `refused`: a header and one line per finding. `[]` for none."""
    if not refused:
        return []
    return ([f"REJECT — {len(refused)} plan target(s) name a test the project's working tree does not have; S4 would search for it:"]
            + ["- " + one_line(item["line"]) for item in refused])


REQUEST_ROW_FIX = '{"request": "<key>", "failures": ["500", "timeout"]}'
REQUEST_HOME_FIX = '{"request": "<key>", "failure": "500|timeout|*", "reason": "<why>"}'


def _request_form(rows, homes, kinds) -> list:
    """The form problems of the plan's `requests` (on a row) and `request_homes` (top level), one line each."""
    out = []
    for i, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict) or row.get("requests") is None:
            continue
        rid = str(row.get("id") or f"rows[{i}]")
        items = row["requests"]
        if not isinstance(items, list):
            out.append(f"{rid}: requests is not a list - fix: [{REQUEST_ROW_FIX}]")
            continue
        for j, item in enumerate(items):
            what = None
            if not isinstance(item, dict):
                what = "is not an object"
            elif not isinstance(item.get("request"), str) or not item["request"].strip():
                what = "has no `request` (a non-empty string)"
            elif not isinstance(item.get("failures"), list) or not item["failures"] or not all(isinstance(f, str) for f in item["failures"]):
                what = "has no `failures` (a non-empty list of strings)"
            elif any(f not in kinds for f in item["failures"]):
                what = f"names a failure outside {', '.join(kinds)}"
            if what:
                out.append(f"{rid}: requests[{j}] {what} - fix: {REQUEST_ROW_FIX}")
        reqs = row.get("requirements")
        if items and not (isinstance(reqs, list) and any(isinstance(r, str) and r.strip() for r in reqs)):
            out.append(f"{rid}: has `requests` and no `requirements` - fix: name in `requirements` the register R whose flow sends the request "
                       "(the red violates that R); a request that serves no R of the story goes to top-level `request_homes` with that reason")
    for k, home in enumerate(homes if isinstance(homes, list) else []):
        what = None
        if not isinstance(home, dict):
            what = "is not an object"
        elif not isinstance(home.get("request"), str) or not home["request"].strip():
            what = "has no `request` (a non-empty string)"
        elif home.get("failure") not in list(kinds) + ["*"]:
            what = f"names a failure outside {', '.join(kinds)} or `*`"
        elif not isinstance(home.get("reason"), str) or not home["reason"].strip():
            what = "has no `reason`"
        if what:
            out.append(f"request_homes[{k}] {what} - fix: {REQUEST_HOME_FIX}")
    if homes is not None and not isinstance(homes, list):
        out.append(f"request_homes is not a list - fix: [{REQUEST_HOME_FIX}]")
    return out


def _request_findings(task_root, doc, unknown=None) -> list:
    """RN1-6: the S3 exit owes every request of `work/flow-requests.json` (`user_path_failures.read_requests`, the one reader) a failure of
    each kind of `perturbations.json` (500, timeout): on a row's `requests` (`{"request", "failures"}`) or in top-level `request_homes`
    (`{"request", "failure": kind|*, "reason"}`). A request is named by its key and compared by `(method, glob)`, so two spellings of one
    endpoint are one request. A row may name a request the list lacks (the list is a floor, AR-2): it is not counted and a WARN line says so.
    The file ABSENT (a story planned before it existed): `[]`, silent. The file unreadable, the table unreadable or anything raising: a WARN
    line and `unknown` gets the reason - the caller prints `UNREADABLE`, never `OK` (AR-28); an unreadable file is first recomputed from the code."""
    try:
        import user_path_failures as UPF
        requests, why = UPF.read_requests(task_root)
        if requests is None and not why:
            return []
        kinds, _oracle, problem = UPF.failure_axis()
        if problem:
            raise ValueError(problem)
        if requests is None:                                  # the file is a cache of a deterministic computation: judge the computation
            requests = UPF.flow_requests(task_root)["requests"]
        rows = doc.get("rows") if isinstance(doc, dict) else doc
        homes = doc.get("request_homes") if isinstance(doc, dict) else None
        lines = _request_form(rows, homes, kinds)
        listed = [r for r in requests if isinstance(r, dict) and isinstance(r.get("url_template"), str)]
        table = UPF.load_request_table()[0]
        ident = {UPF.request_identity(r, table): r for r in listed}
        covered, unlisted = set(), []
        for row in rows if isinstance(rows, list) else []:
            for item in (row.get("requests") if isinstance(row, dict) and isinstance(row.get("requests"), list) else []):
                if isinstance(item, dict) and isinstance(item.get("request"), str) and isinstance(item.get("failures"), list):
                    key = UPF.request_identity(item["request"], table)
                    covered.update((key, f) for f in item["failures"] if f in kinds)
                    if key not in ident:
                        unlisted.append(f"{row.get('id')}: {item['request'].strip()}")
        for home in homes if isinstance(homes, list) else []:
            if isinstance(home, dict) and isinstance(home.get("request"), str) and isinstance(home.get("reason"), str) and home["reason"].strip():
                key = UPF.request_identity(home["request"], table)
                covered.update((key, f) for f in kinds if home.get("failure") in (f, "*"))
        for key, entry in ident.items():
            left = [f for f in kinds if (key, f) not in covered]
            if left:
                name = UPF.request_key(entry)
                lines.append(f"{name} ({entry.get('path')}:{entry.get('line')}): no plan row fails it with {', '.join(left)} - fix: add "
                             f"{{\"request\": \"{name}\", \"failures\": {json.dumps(left)}}} to `requests` of the row that checks it, or "
                             f"{{\"request\": \"{name}\", \"failure\": \"{'|'.join(left)}|*\", \"reason\": \"<why>\"}} to top-level `request_homes`")
        if unlisted:
            print(one_line("WARN row(s) name a request that is no request of work/flow-requests.json, so nothing of the list is counted "
                           "perturbed by it: " + "; ".join(unlisted[:8])))
        import branch_accounting as BA
        shown = BA.limit("refusal_units_shown")
        if len(lines) > shown:
            lines = lines[:shown] + [f"{len(lines) - shown} more problems ({len(lines)} in all); fix these first, the check runs again"]
        return lines
    except Exception as exc:  # noqa: BLE001
        reason = f"the request closure could not run: {type(exc).__name__}: {exc}"
        print(one_line(f"WARN {reason}"))
        if unknown is not None:
            unknown.append(reason)
        return []


def detector_main(root=None):
    """Zero-argument entry point for the S3 exit gate. Nothing to check without a story or a plan (exit 0); a check
    that could not run - `detector_story` raised, or anything unhandled in the body - is `UNREADABLE: ...`, exit 3
    (RH1-5, FR-59): never a silent pass."""
    try:
        return _detector_body(root)
    except Exception as exc:
        print(unreadable_line(f"planning_contract could not complete ({type(exc).__name__}: {exc})"))
        return EXIT_UNREADABLE


def _detector_body(root):
    task_root = detector_story(root)
    if task_root is None:
        return 0
    plan = story_plan_path(task_root)
    if plan is None:
        print(f"planning_contract: {task_root.name} has no structured test plan yet — nothing to check")
        return 0
    try:
        data = json.loads(plan.read_text(encoding="utf-8"))
    except Exception as exc:
        print("REJECT — 1 problem(s): the structured test plan cannot be read:")
        print("- " + one_line(f"{plan.name} is not readable JSON ({exc}); Gate A reads this file, so it "
                              "cannot stay broken"))
        return 1
    rows = data.get("rows") if isinstance(data, dict) else data
    mode, version = story_contract_mode(task_root)
    # RN1-2 (F-1, B-5): the revision mark is CODE's. The exit judges the plan as if it were stamped (`stamp_revision`, the
    # controller's own predicate); the real stamp is `project_plan`, at S3 completion. A detector writes nothing (FR-45): the
    # stamp and the `new:<n>` renames below live on copies. Invariant: the rows judged here equal, in the mark, the rows gate A reads.
    stamped = stamp_revision(rows, mode)
    errors = gate_plan_errors(stamped, mode, version)
    import grounding_table   # G1-5, lazy (GT imports this module): the findings of the S3 exit that are the ROLE's, nothing of the driver's or the conductor's
    errors = list(errors) + grounding_table.role_exit_lines(task_root, stamped if isinstance(stamped, list) else None)
    # Only here, not in `gate_plan_errors`: the register is on disk at the S3 exit, while
    # `gate-inputs` validates a plan the controller holds — and a story already past S3 on an
    # older build must not be refused at gate A over a field it was never asked for.
    conflicts = contradiction_errors(stamped, story_register_text(task_root))
    view = plan_questions_view(stamped)
    branch, why_unread = s3_branch_refusals(task_root, stamped, view)
    missing = [item for item in branch if item["kind"] in S3_EXIT_KINDS]
    # GW1-41: the register fence runs AFTER the old checks and replaces none of them; it never raises (`state: unknown`), so a
    # failure of the fence cannot make an old refusal unreachable. Unknown never hides a known refusal and a known refusal is
    # never printed as OK: with any REJECT the `UNREADABLE:` line is NOT printed (the exit gate reads an unreadable detector
    # as the one record and would hide the refusals); with none, only `UNREADABLE:` and its exit code, no `OK:`.
    # B-6: it reads the view (a declared `new:<n>` is an open question there), so the door works for a candidate defect too.
    fence = register_fence(task_root, view[0], view[1])
    fence_blocks = fence_lines(fence)
    regression = _regression_findings(task_root)   # RG1-2: the plan's `## Recommended regression`, checked by `regression_scope`
    # TQ1-21: the test an `extend` / `param` / `reuse` builds on is a file of the working tree. After the old checks, replaces none; it
    # never raises (`target_unread`), and an unknown base is a WARN, never a refusal (FR-59: S4 writes the case as new).
    targets, target_warns, target_unread = fit_target_findings(task_root, view[0])
    # RN1-6: the request closure runs AFTER every older check and replaces none; it judges the rows gate A reads (the stamped ones),
    # while the document still carries the top-level `request_homes`. An unknown closure is `request_unknown`, never an OK (AR-28).
    request_unknown: list = []
    requests_found = _request_findings(task_root, dict(data, rows=stamped) if isinstance(data, dict) else stamped, request_unknown)
    for warning in plan_warnings(rows):
        print("WARN " + warning)
    for line in target_warns:
        print("WARN " + one_line(line))
    for finding in (item for item in branch if item["kind"] in S3_WARN_KINDS):
        print("WARN " + one_line(finding["message"]))
    if fence["by_reference"]:
        print("WARN " + one_line(f"plan rows name {named_ids(fence['by_reference'], 8, where='the plan')} only by a reference; "
                                 "write them in `requirements`."))
    if fence["state"] == "window_one":
        print(fence["why"])
    if not errors and not conflicts and not missing and not fence_blocks and not regression and not targets and not requests_found:
        # AR-28: an unknown request closure is never `OK:`; with any REJECT the `UNREADABLE:` line is not printed
        unread = "; ".join(why for why in (why_unread, target_unread, request_unknown[0] if request_unknown else "") if why)
        if unread or fence["state"] == "unknown":
            print(unreadable_line(unread or f"{fence['why']}"))
            return EXIT_UNREADABLE
        if fence["state"] == "empty":
            print("register lists no requirement: nothing to fence")
        count = len(rows) if isinstance(rows, list) else 0
        print(f"OK: {plan.name} ({count} rows) satisfies what Gate A's gate-inputs will require")
        return 0
    if errors:
        print(f"REJECT — {len(errors)} plan problem(s) Gate A's `controller.py --operation "
              "gate-inputs` will refuse; repair them now, while S3 still holds the context:")
        for error in errors:
            print("- " + one_line(error))
    if conflicts:
        print(f"REJECT — {len(conflicts)} contradiction(s) the register recorded and the plan "
              "does not carry; the reading is the owner's to choose, not yours to settle:")
        for conflict in conflicts:
            print("- " + one_line(conflict))
    for line in _branch_block_lines(missing):
        print(line)
    for header, lines in fence_blocks:
        print(header)
        for line in lines:
            print("- " + one_line(line))
    if regression:
        print(f"REJECT — {len(regression)} problem(s) in the plan's `## Recommended regression`:")
        for line in regression:
            print("- " + one_line(line))
    for line in fit_target_block(targets):
        print(line)
    if requests_found:
        print(f"REJECT — {len(requests_found)} problem(s) in the plan's flow requests (`requests`, `request_homes`):")
        for line in requests_found:
            print("- " + one_line(line))
    # O11: one line counts every kind. It is a TAIL line now (the reader hands the role every finding
    # line above, whole; it no longer cuts a tail of three lines), a summary and not a finding. Never printed
    # on the OK path.
    print(f"S3 exit: {len(errors)} error(s), {len(conflicts)} conflict(s), "
          f"{len(missing)} question-branch problem(s), "
          f"{len(fence['missing'])} requirement(s) without a row, {len(fence['candidates'])} candidate(s) without a test row, "
          f"{len(fence['waiting'])} requirement(s) waiting with no branch, {len(regression)} regression problem(s), "
          f"{len(targets)} plan target problem(s), {len(requests_found)} request problem(s)")
    waiver = ("A person's word passes any of these: `"
              + door("waiver.py --task <TICKET> --stage S3 --block \"<part of the line>\"") + "` " + WHOLE_PART + ".")
    lacking = [item for item in missing if item["kind"] == "missing_branch"]
    if lacking:
        # C7 (t-227b) -> t-721 3.6: the S4 rehearsal (`gate_preflight.check_question_branches`) now reads the S3
        # word of the same finding too, so ONE record passes both stages (it used to be recorded twice, with
        # `--stage S3` and with `--stage S4`). The example line is `missing_branch_line`, which the reader also reads.
        example = missing_branch_line(lacking[0])
        waiver += (f" For a missing branch quote the line (`{example}`): the same word also passes the "
                   "question-branch check at the case stage (S4).")
    print(waiver)
    return 1


def validate_case_actions(actions):
    errors = []
    seen = set()
    for action in actions:
        sid = action.get("scenario_id")
        if not sid or sid in seen:
            errors.append("case actions require unique scenario IDs")
        seen.add(sid)
        for field in ("execution_mode", "case_action", "rationale", "search_scope",
                      "search_snapshot_revision", "search_completeness", "automation_action"):
            if not action.get(field):
                errors.append(f"{sid}: missing {field}")
        if action.get("execution_mode") not in {"automated", "agent-manual", "human-manual"}:
            errors.append(f"{sid}: unknown execution mode")
        disposition = action.get("case_action")
        if disposition not in {"reuse", "update", "create", "unresolved"}:
            errors.append(f"{sid}: unknown case action")
        if disposition in {"reuse", "update"} and not action.get("existing_case_refs"):
            errors.append(f"{sid}: existing case ID/version required")
        if disposition == "create" and action.get("search_completeness") != "complete":
            errors.append(f"{sid}: incomplete search must not create a remote case")
        if disposition in {"create", "update"} and not action.get("proposed_case_version"):
            errors.append(f"{sid}: proposed case version required")
        if action.get("execution_mode") != "automated" and action.get("automation_action") != "not_applicable":
            errors.append(f"{sid}: manual action must not fabricate automated implementation")
    return errors


def publication_manifest(actions, decision, remote_versions):
    """Create a reviewable write manifest, never send external requests itself."""
    from event_store import content_hash
    errors = validate_case_actions(actions)
    digest = content_hash(actions)
    if decision.get("action") != "publish_cases" or decision.get("status") != "approved":
        errors.append("specific publish_cases authorization required")
    if decision.get("content_hash") != digest or not decision.get("destination"):
        errors.append("publication decision must bind exact case content and destination")
    if not decision.get("authorization_source"):
        errors.append("publication authorization source required")
    requests = []
    for a in actions:
        if a.get("case_action") == "unresolved":
            continue
        for ref in a.get("existing_case_refs", []):
            if remote_versions.get(ref["id"]) != ref.get("revision"):
                errors.append(f"{a['scenario_id']}: remote case changed; do not overwrite human edits")
        requests.append({"scenario_id": a["scenario_id"], "action": a["case_action"],
                         "existing_case_refs": a.get("existing_case_refs", []),
                         "case_version": a.get("proposed_case_version"),
                         "fields": a.get("publication_fields", {}),
                         "fields_hash": content_hash(a.get("publication_fields", {})),
                         "idempotency_key": content_hash({"destination": decision.get("destination"),
                                                          "channel": decision.get("channel", decision.get("destination")),
                                                          "scenario": a["scenario_id"],
                                                          "version": a.get("proposed_case_version"),
                                                          "action": a["case_action"],
                                                          "existing_case_refs": a.get("existing_case_refs", []),
                                                          "fields": a.get("publication_fields", {})})})
    if errors:
        raise ValueError("; ".join(errors))
    return {"content_hash": digest, "destination": decision["destination"],
            "channel": decision.get("channel", decision["destination"]), "requests": requests}


def main():
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(__doc__)
    # No INPUT is the S3 exit gate calling this as a detector: the gate runs every detector as
    # a bare `python <script>` from the project root, so the plan has to be found, not passed.
    ap.add_argument("input", nargs="?", type=Path)
    ap.add_argument("--kind", choices=("plan", "case-actions", "publication"), default="plan")
    ap.add_argument("--root", type=Path, help="project root; detector mode only, for tests")
    a = ap.parse_args()
    if a.input is None:
        raise SystemExit(detector_main(a.root))
    # `read_text()` used to run unguarded here. On TP2-2553 the call was made with the
    # story's work directory instead of the plan file, and `PermissionError: [Errno 13]` came
    # back as a traceback in the orchestrator's face — for a check the S3 write hook had
    # already performed on that very file. One line naming the right call is the whole answer.
    if not a.input.is_file():
        what = "a directory" if a.input.is_dir() else "not a file"
        print(f"planning_contract.py: {a.input} is {what}, not a plan file; call it as "
              "planning_contract.py qa-factory/artifacts/<TICKET>/work/test-plan.json (or with "
              "no argument inside the story, where the S3 hook already validated the plan)",
              file=sys.stderr)
        raise SystemExit(2)
    data = json.loads(a.input.read_text(encoding="utf-8"))
    if a.kind == "publication":
        result = publication_manifest(data["actions"], data["decision"], data["remote_versions"])
    else:
        # `work/test-plan.json` is written as `{"rows": [...]}` — the shape the detector path,
        # `validate_artifacts.py` and `gate_brief.py` all unwrap. Only this explicit entry point
        # did not, so s3.md's own command answered "plan must be an array of behavior rows"
        # about a valid plan (TP1-15045).
        if a.kind == "plan" and isinstance(data, dict):
            data = data.get("rows") or []
        errors = validate_plan(data) if a.kind == "plan" else validate_case_actions(data)
        result = {"valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(1 if result.get("errors") else 0)


if __name__ == "__main__":
    main()
