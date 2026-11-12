<!-- generated from plugin:references/artifact-contract-plan.md for qa-test-strategist by scripts/contract_slices.py; edit the source, never this file -->
# Artifact contract — what gate A is built from

The S2–S4 documents. Where they live: `artifact-contract.md`; their values:
`vocabularies.md`.

## `test-plan.md`

**Writer** `qa-test-strategist`, S3. **Shape** frontmatter `task,
created, rows_total, candidates, planned`, the pyramid count, and a
`## Plan` table, one row per check.

| column | content |
|---|---|
| `TS` | `TS-n`, unique |
| `what we verify` | one plain line |
| `R` | register ids, `R-1, R-2` |
| `defect hypothesis` | `<class> @ <place>`, or `smoke` (at most one per R) |
| `impact class` | `data-loss · money · access · blocked-flow · degraded · cosmetic · none`; JSON key `impact_class`, never `impact` (`risk-policy.md`) |
| `priority` | derived from the impact class |
| `observable` | `<source>:<path:line>` |
| `oracle` | `requirement:R-n` · `external:<ref>` · `history:<ref>` |
| `disposition + reason` | `` `automate` — <reason> `` |
| `fit` | `extend <test>` · `param <test>` · `new` (empty off `automate`); `<test>` is `<path from the project root>[::<name>]` in the project's working tree, or a candidate id of `context-bundle.json` - the S3 exit refuses an unfound one. A test only in the change: `new`, with `fit_absent: "<test>"` |
| `level` | `unit · component · api · integration · e2e-ui`, from the execution boundary, mandatory on `automate`; unknown: a gap |
| `technique` | the technique applied |

Plus `## Recommended regression`: the EXISTING tests that defend the blast radius, never one this story writes:
`Command: <the project's own test command> <target> <target>`; one item per path `- \`<path>\` (blast:B-n[, blast:B-m]) - stand: <what it needs | no stand requirements>`
(paths from `tests_root`, on the main branch); `Developers: <component checks>`. Nothing to name:
`No regression: <reason>` alone.
**Validator** disposition and `defect hypothesis` class from their closed lists, each with its
reason (`regression` alone is no class, `regression:BUG-NNN` is; cases inherit it);
every observable with a source; the oracle rule above; no anti-pattern
row (visibility-, title-, URL- or first-record-only) on `automate`; a gate-A override: `overridden: true`.
`evidence_policy` of a `manual-agent` obligation is ONE word as text: `api | cli | no_write | static | ui`; detail goes in `completion_condition`.
`work/test-plan.json` is `{"rows": [ ... ]}` — the rows for the scripts, a
compound requirement decomposed per obligation (`coverage-design.md`). Each row names its register ids in `requirements` (`["R-9"]`); a requirement waiting for a question still gets its row. A row the `## Contradiction matrix` touches carries
`source_conflict: true` or `oracle_unknown: true`; both force `design_review_required` and
become a gate-A question.

**A row that rests on an open register question** (`question_refs` `["Q1"]` or its `reason` names
it) says what each answer does. `if_answered` is `{"Q1": {"a": <patch>, "b": <patch>, "not_needed":
<patch>, "*": <patch>}}` with a key for EVERY reading letter (or `*`) and `not_needed`; `{}`
leaves the row as written. The S3 exit refuses a row without them. A patch is row fields from `question-branch-keys.json` (`disposition`, `level`,
`fit`, `reason`, `oracle_unknown`, `test_level_rationale`, `coverage_obligations`, which replaces
the whole list). `*` and a letter merge, the letter winning; `*` never covers `not_needed`. A
patch's `reason` never names its own question id; once any row has `question_refs`, every
`oracle_unknown` row does. Two questions may not patch one field of a row.

**A question the register does not hold.** Write `"new:<n>"` (n from 1 to 99) in the row's `question_refs` and an entry in the row's
`new_questions`: `{"key": "new:<n>", "question", "source_says": [{"quote", "where"}], "readings": [{"reading", "from", "if_chosen"}, two or
more], "severity", "owner_role"}`. `if_answered` is keyed `"new:<n>"` the same way. Code raises it as the next `Q-n` at S3 close and
rewrites the ref, the branch key and the `test-plan.md` cell.

**Branches in the plan.** Every register branch (`BN-n`) and every branch read in an existing test (`candidate_branches`:
`{"id": "BN-T1", "r": "R-n", "from": "<candidate id>", "text": "..."}`) is named in a row's `branches` or excluded in
top-level `branch_homes` (`{"branch": "BN-2", "home": "excluded", "reason": "...", "decided_by": "role|person", "answer": "<question
id, when a person decided>"}`); a `skip`/`unverifiable` row excludes its named branches by `reason`. Each
`context-bundle.json` `existing_test_candidates` entry is named in `candidates_walked` (`{"candidates": ["<id>"], "took": ["BN-T1"]}`
or `{"candidates": ["<id>"], "none": "<why>"}`; `[]` for none). A `manual-agent`/`manual-human` row carries `rung_basis`
`{"kind": "measured | impossible | person_word | judgement", "ref": "<probe or question id, or environment reason>"}` (`not_measured` refused; P0 adds `reason`).
`branch_accounting.py` refuses what is missing.

**Requests.** `requests` on a row (`[{"request": "<key>", "failures": ["500"]}]`), or top-level `request_homes` (`[{"request", "failure": "500|timeout|*", "reason"}]`).

## `grounding.yaml`

`work/grounding.yaml` has ONE reader, `planning_contract.read_grounding` (a missing or empty file,
another `schema_version` or an unknown key is refused). The strategist writes `rows`,
`requirements`, `claims` and per `blast_radius` area `matters`, `why`, `regression`, `add_tests`,
`text_says`. Code writes `schema_version`, `implementation_source`, `null_outcome`, `diff`
(`repo_id`, `implementation_commit`), `hunks`, `refactoring_share`, `requirement_coverage`,
`base_slice`, `orphans`, `register_sha256`, the rest of `blast_radius` (`path_kind`). The closed words:
labels: behaviour_change, implements, infrastructure, refactoring, test_code, unclassified, unrelated; requirement states: implemented, not_implemented, outside_diff, partial, unknown. A plan row answers an entry with `grounding:K-n`, `blast:B-n` or
`refactoring:G-n` in `risk_source_refs`. `delta`, `origin`: register columns.

## Fields the plan validator checks (coverage-observation-v1)

Each row is planned on `coverage-observation-v1` and carries `schema_version: 2` too; CODE writes the `coverage_contract_revision` mark when S3 closes: do not write it
(another revision is refused: re-plan). The S3 gate refuses a row unless:

`coverage_delta` (on the row):
- `entries`: one per obligation id, no more: `obligation_id`, `disposition`
  (`reuse | strengthen | replace_redundant | gap`), `rationale`; `existing_case_refs` unless `gap`;
  `gap_reason` on a `gap`.
- `baseline_kind`: `initial | accepted`. `initial` needs `initial_scope_rationale`; `accepted` with
  more cases or instances needs `accepted_scope_expansion_ref`.
- `counts`: `logical_cases_before`, `logical_cases_after`, `executable_instances_before`,
  `executable_instances_after`, integers >= 0.
- `planned_instance_ids`: unique strings; `executable_instances_after` equals their number.

`observation_contract` (on each obligation):
- `claim_kind`: array from `state_unchanged | no_write_attempt | response_parity | no_leak |
  rendered_behavior | ordinary`.
- `oracle_ref`: an id of `requirement_refs` with its `revision`, or of
  `source_conflict_refs`.
- `surfaces`: `id` (unique), `boundary`, `status` (`planned | observed | gap`); `assertion_ref`
  unless `gap`; `gap_reason` only on a `gap`.
- A ref (`assertion_ref`, each of `controls`, `completion_ref`, the refs below) names an existing
  check of this obligation: a `planned_check_refs` entry, an `applicable_scenarios` id, a
  `coverage_links` assertion ref, `candidate_id` or `test_ref`, or a `parts[].part_id`.
- `independent_expectations`: `[]` or `{partition_ref, expected_ref, attribution_assertion_ref}`;
  `response_parity` needs two or more, partitions unique. `source_conflicts`: `[]` or ids of
  `source_conflict_refs`.
- No-write (`state_unchanged`, `no_write_attempt`): `sequence` of four `{phase, ref}` in the order
  `before_read`, `action`, `completion`, `after_read`; `positive_control_ref`, a mutating check
  outside the sequence; `reachability_assertion_ref`.
- `no_leak`: `payload_assertion_ref`, the check reading the denied payload.

```json
{"schema_version": 2, "coverage_obligations": [{"obligation_id": "OB-1", "requirement_refs": [{"ref": "R-4", "revision": "r1"}],
"planned_check_refs": ["c1", "c2"], "observation_contract": {"claim_kind": ["ordinary"],
"oracle_ref": {"ref": "R-4", "revision": "r1"}, "controls": [], "completion_ref": "c2",
"surfaces": [{"id": "S-1", "boundary": "API", "status": "planned", "assertion_ref": "c1"}],
"independent_expectations": [], "source_conflicts": []}}],
"coverage_delta": {"baseline_kind": "initial", "initial_scope_rationale": "First plan.",
"entries": [{"obligation_id": "OB-1", "disposition": "strengthen", "rationale": "Extend",
"existing_case_refs": ["CAND-1"]}], "planned_instance_ids": ["i1"], "counts": {
"logical_cases_before": 1, "logical_cases_after": 1,
"executable_instances_before": 0, "executable_instances_after": 1}}}
```
