# Artifact contract — the execution artifacts

What an execution leaves behind: the run and the triage.
Companion to `artifact-contract.md` (vocabularies, markdown artifacts) and `artifact-contract-json.md` (state files). Types: `str`, `int`, `bool`, `[]` list, `{}` object, `?` optional.

<!-- roles: qa-runner, qa-failure-analyst, qa-doc-scribe -->
## `run-report.json`

Manual v2 rows are immutable block inputs: `{schema_version:2, case, result, evidence_policy,
evidence_refs:[{path,content_hash,phase}], before_change?}`; input refs carry `content_hash`;
exported rows add `sha256`. Phases are `pre_action|post_action|supporting` (the old
`before|after` still read). Paths are task-relative and hash verified. UI evidence has
pre_action and post_action; API/CLI evidence has a post_action state; `inconclusive` needs a
limitation. Public reports consume the verified export, never browse `work/evidence/`.

**Writer** `qa-runner` at S6 from `run_suite.py` summaries plus its own `manual-agent`
execution. **Readers** failure analyst, `ledger.py`, `check_delivery.py`, the dashboard.

`execution_status` str from the closed list · `env_preflight` str (`pass|blocked`;
`blocked` implies `execution_status: env_blocked`) · `stage` str
(`feature`; regression is recommended to the user, never executed here) · `head` str/{}
(the source SHA the evidence is bound to) · `totals` {}
(`passed`, `failed`, `skipped`, `passed_on_retry`) · `results` [] of `{test_id, case?,
status: passed|failed|error|skipped|not_run, reason, evidence}` · `manual_checks` [] of
`{case, result: pass|fail|inconclusive, evidence}` · `manual_skipped` []? · `env_blocked`
[]? · `impossible` [] of `{case, reason}`? · `witness` str.

`results[]` is **reduced by `finalize_task.py <task_root>`** from the immutable run blocks —
never pasted or typed. Each block holds one row per selected
instance (name, status, for a skip the `<skipped message>`); the reducer
joins them into the whole-story report. A row you cannot find in a block did not happen.
Both spellings (`{test, result}`, `{test_id, status}`) are read; write `test_id`/`status`.
Only **passed** rows may be capped (`results_note` counts those left off); every
failed, errored or skipped test is listed by name.

**Checked** `execution_status` from the closed vocabulary; a zero-total run with
`env_preflight: pass` and no blocked/manual entries is rejected ("empty is not clean"); a
report without `head` is rejected; `manual_checks[].result` from its closed list; every
`results[]` row has a name, one case id at most, and a status from the closed list, a
`skipped` row has a `reason`, and the number of non-passed rows equals `totals`' failures +
errors + skipped. Every case S5 automated and every `manual-agent` plan row has a lane.

<!-- roles: qa-test-strategist -->
### The proof stamp

This section is read by nobody's slice: code writes the stamp, and no run role acts on it (the runner's own craft line names `about`).
Code writes `sides_met: {<side>: <reality>}` and/or `sides_unknown: "<why>"` on a run block and a manual block from the story's
`pipeline.json` (the story's `pipeline.sides` record, or the default side when there is none): a block has no such key on a story with no
`pipeline.sides` record, no non-real side and no `sides_unknown`. A `pipeline.json` that is present but unreadable, or a `pipeline.sides`
that is not a side record, stamps `sides_unknown` and no `sides_met`. An imported run block keeps the stamp it was given at import.
`finalize_task.py` carries it onto every `results[]` and `current_manual_checks[]` row. A walked manual row may carry the record-level
`about: [<side>]`, each a side of the story (not the observation-level `about` of a card).

<!-- roles: qa-runner, qa-doc-scribe -->
### The two halves of S6

S6 runs in two halves, so at the automation runner's handoff a `manual-agent` row with no lane yet is one note line ("n manual-agent rows wait for the manual
half"), not a refusal; a manual block is asked only for its own `manual_case_ids` (the other rows are the same kind of
note, "wait for a later block or the close"); the stage close, with no running dispatch, refuses every row with no lane.

<!-- roles: qa-failure-analyst, qa-doc-scribe -->
## `triage.json`

**Writer** `qa-failure-analyst`, S7. **Readers** `ledger.py`, `check_delivery.py`,
`qa-bug-reporter`, the dashboard, `bug_records.py`, `handoff_check.py`, `traceability.py`.

Shape `{"triage": [row, ...]}` (`artifact_producer.py prepare --kind triage` writes the skeleton). Per failure: `test` str · `verdict` str from the closed list · `evidence` str (non-empty —
a verdict without proof is invalid) · `mechanism` str (FLAKY only, closed list) ·
`reruns` int (FLAKY only, ≥ 3 isolated executions counted across every role via `runs[]`) · `detail` str? (one sentence: why this verdict, in the task's terms; the report quotes it) · `fix_rounds` int? · `fix_result` str?
(`fixed | not_fixed`). `ENV_ISSUE` rows carry the dismissal formula
(`our_signal`/`env_fix`/`unverified`). `control` object? (action run WITHOUT the change; checked if present): `result`
(`effect_without_change | no_effect_without_change | impossible`) · `action` · `without` · `observed` · `evidence`
(an `evidence/` file) · `why` (if impossible) · `given_gap`? (filled). `ASSERT_STRICTER` (no repair or
draft; a person decides) needs `control` with `result: effect_without_change`. `contradiction` object (the verdict
`RUNNER_MISREAD_EVIDENCE` only, a manual check: a row with its `case`, no `test`, no `reorder`): `then` (its number) ·
`runner_said` (the runner's own words) · `evidence` (a text file the runner's attempt captured, task-relative, under the
case's `work/evidence/manual/<case>/a<n>/`) · `quote` (at most 300 characters from that file, as it holds them). An observation row: `instance_id` `<case>#obs<n>`, `attempt_id`, verdict `APP_BUG` | `NO_DEFECT` (+ quoting `reason`).

Optional, for the Thens a red stops (red-Then triage): `blocked_thens` [] of `{then, blocking_check, detail}` - a Then
that cannot answer while the defect of case `blocking_check` stands (the verdict stays) · `blocking_check` str - this
row's red is that case's defect (no second draft) · `diagnostic` `{evidence, thens?, observed}` - the ONE run without the
red assert (`evidence/diagnostic-<label>.json`, `red_sandbox.py --diagnostic`) · `reorder` bool - independent Thens sit
after the red and the author moves the asserts (S7 repair `reorder`; needs a non-empty `blocked_thens`). `carried_attempts`
and `carried_by` are written by code after a reorder round, never by the role; so is
`fix_result: fixed` on a `reorder` row (`s7_reorder.py mark-fixed`): the critic approved the reorder, and nothing else reads it as a FLAKY outcome.

**Checked** verdict from the closed list; non-empty evidence; a `FLAKY` verdict without
`reruns >= 3`, without a `mechanism` from the list, or without a `fix_result` is rejected.
`fix_result` other than `fixed` puts the test in the ledger as `not_verified_flaky` and
makes `delivery_ready` false.

<!-- roles: qa-failure-analyst -->
### Surprise rows

A `<case>#sur-<id>` row (the recorder's id, `a2-ui-S3`) or the `<case>#sur-overflow` row (uncited lines past 30; they are in the
record's `surprises[]`) has `attempt_id` and a verdict `APP_BUG` | `NO_DEFECT`, as an `#obs` row; a `NO_DEFECT` quote stands in that
surprise's own line. A line cited by `"surprise": "<id>"` is judged in its observation.

<!-- roles: qa-failure-analyst -->
### FLAKY — a test defect

A `FLAKY` verdict needs **≥3 isolated executions** across every role's `runs[]` and a mechanism from
the closed list; the fix targets the mechanism, never a retry annotation.

<!-- roles: qa-failure-analyst -->
## `bug-drafts/*.json`

**Writer** `qa-failure-analyst`, S7, `APP_BUG` only. **Readers** gate B, `qa-bug-reporter` S8,
`traceability.py`, the dashboard. A draft is a candidate the person answers: `bugs/BUG-n.md`
exists only after a gate B decision names this file.

```json
{"title": "…", "impact": "degraded", "violates": "requirement:R-4", "case": "TC-004",
 "triage_ref": {"instance_id": "test_removed_node[chromium]", "attempt_id": "a3"},
 "manual_steps": ["open the diff of revision 4 against 3"],
 "red_test": {"path": "tests/test_diff.py::test_removed_node", "command": "pytest tests/test_diff.py::test_removed_node"},
 "confirmation": "unconfirmed"}
```

Required: `title` · `impact` (a class from the scale) · `violates` (the plan row's oracle
grammar) · `case` · `triage_ref`, naming a `triage.json` row whose verdict is `APP_BUG` ·
`manual_steps` [], what a PERSON does in the product to see the defect, never the test's
assertion line · `red_test {path, command}` (the failing test that shows the defect and re-checks the fix) **or**
`red_test_none: <why>` (e.g. `manual check only`) - one of the two, never neither, never both; the red test travels with the bug ·
`confirmation` — `unconfirmed` (nobody outside the run has seen it; it counts
toward nothing) until `confirmed_by_person` at gate B or `confirmed_by_rerun` on another stand; the code derives `reproduced_by_factory` from `reproduction`, below.
Optional `reproduction`: `[{kind, evidence, observed, attempt_id}]`, `kind` `fresh_data_rerun`, `own_script` or `walk`; `evidence`
a non-empty file under `evidence/`; a `fresh_data_rerun` names the `attempt_id` of a later attempt that failed again; a `walk` names `evidence/place-answer-<id>.json`, the record `place_answers.py write` made for this draft's `bug` answer.
Optional: `plan_row`, `expected`, `actual`, `possible_duplicate`, `cases` - the cases the draft covers: its own
and every case whose `triage.json` row names it through `blocking_check` (the blocker's draft is the only draft).
Also optional: `defect_location` (`file:line`), `requirements` (`["R-n"]`, all it breaks), `extends_open_bug` (`{"key","summary"}`: the open source bug that is `match`; shown only when the key is verified), `distinct_defect` (`"<why>"`: shares a place, another defect).
**One cause, several ways it shows:** `mechanism` `{statement, status: confirmed|unverified|unknown, basis: [{id, kind: code_line {path, line, quote} | run {case, capture, quote, start_state} | person {dispatch, quote}}], claims: [{says, confirmed_by: [basis ids]}], why}` - `why` says what is missing when `status` is not `confirmed`; a claim with no `confirmed_by` reads "not verified"; unknown: `{status: "unknown", why}`, `basis: []`. `manifestations`: `[{action, start_state, seen, requirement, case, triage_row | probe {case, capture, quote}, evidence, red_test | red_test_none, from_draft}]`, the first is the draft's own row; 2+ only when `status` is `confirmed` and its basis stands. `person` stands only when `dispatch` is the S7 rework of the person's words for these cases and `quote` (12+ characters) is in them. A code-reading draft is absorbed as `from_draft` + `evidence` (`path:line`), no row, no probe. `possibly_same_cause`: `[{draft, why}]` - separate drafts you suspect share a cause you could not confirm (not `possible_duplicate`: that names a tracker issue). Without these keys: one manifestation, cause not stated. `siblings` is legacy: nothing reads it.
**Second form, `evidence: "code-reading"`** (no `triage_ref`, `case`): `{"title", "impact", "violates", "oracle": {"question"|"requirement": "Q7"|"R-24", "quote": "<verbatim>"}, "fact": {"id", "path", "line"} | {"path", "line", "quote"}, "check_state": "not_executed"|"unverifiable", "manual_steps": [...]}`. Requirement oracle: its row says `code_says: contradicts: <that id>`; code place: whole line.

**Checked** at the gate B rehearsal, before the list is shown: no `triage_ref`, a
verdict other than `APP_BUG`, a case the roll-call leaves unreviewed, or no `manual_steps` —
each a `factory_fixable` finding S7 repairs, each passed by a person's word (`waiver.py`).

<!-- roles: qa-doc-scribe -->
## `bugs/BUG-n.md` — the filing header (HF8-21)

**Writer** `qa-bug-reporter`, S8, after gate B. **Readers** `bug_records.py` (`filing_of`: the file, and whether the tracker has
it, derived by code), the report, `validate_artifacts.py`. A bug filed from a draft of this run carries `source_draft`, `cases` and
`requirements` in its frontmatter; no case is `cases: []` with `no_case_reason`. A bug with no `source_draft` is an older one and is
read as before. The reporter's hand-off form is `s8-bug-reporter-to-scribe`: `scope` (one row per draft the person answered
about, or the one row `gate_b` / `nothing_chosen`), `filed`, `not_filed`, `quarantined`; it never says whether a tracker has the bug.
A draft with 2+ `manifestations` is one bug: `cases`, `requirements` are the unions, `red_test` the primary's, and the body adds `## Cause` and `## Manifestations` (a line each: case, action, start, seen, red test command or why none).
