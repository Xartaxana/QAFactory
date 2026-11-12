<!-- generated from plugin:references/artifact-contract-run.md for qa-runner by scripts/contract_slices.py; edit the source, never this file -->
# Artifact contract — the execution artifacts

What an execution leaves behind: the run and the triage.
Companion to `artifact-contract.md` (vocabularies, markdown artifacts) and `artifact-contract-json.md` (state files). Types: `str`, `int`, `bool`, `[]` list, `{}` object, `?` optional.

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

### The two halves of S6

S6 runs in two halves, so at the automation runner's handoff a `manual-agent` row with no lane yet is one note line ("n manual-agent rows wait for the manual
half"), not a refusal; a manual block is asked only for its own `manual_case_ids` (the other rows are the same kind of
note, "wait for a later block or the close"); the stage close, with no running dispatch, refuses every row with no lane.
