<!-- generated from plugin:references/vocabularies.md for qa-doc-scribe by scripts/contract_slices.py; edit the source, never this file -->
# Closed vocabularies

Every value below is verbatim, as `scripts/contract.py` holds it. Anything outside these
lists is an invented status the validator rejects on write.

## Disposition

**Disposition** (plan row) — `automate` · `manual-agent` · `manual-human` · `skip` ·
`unverifiable`. Each carries a non-empty `reason`. Changed by the human at gate A →
the row also carries `overridden: true` and `overridden_by: human`.

## `unresolved[]` reason

**`unresolved[]` reason** (automation manifest) — `impossible` · `blocked_by_env` ·
`pending_implementation` · `blocked_by_check` · `contradicts_requirement` (the code does what the requirement
forbids: the row names the requirement id, the expected and the observed value) ·
`deferred_by_decision:<gate>`.

## `remedy`

**`remedy`** (on a `blocked_by_env` row of the manifest, or an `env_blocked[]` row of the run
report) — `{kind: flag|credential|data|service, where: <file:lines or the variable NAME>,
change: <what to set>, restart?}`: the change that would end the block. Names only — a
credential value in an artifact is a leak. A blocked row without one is refused.

## `execution_status`

**`execution_status`** (run report) — `passed` · `failed` · `env_blocked` ·
`not_executed` · `broken_run` · `timeout`. Computed from the run's own evidence, never
typed by a role.

## Triage verdict and FLAKY mechanism

**Triage verdict** — `APP_BUG` · `TEST_BUG` · `TEST_BUG:collection` · `ENV_ISSUE` ·
`FLAKY` · `APP_CHANGED` · `CASE_DEFECT` · `ASSERT_STRICTER` · `RUNNER_MISREAD_EVIDENCE` · `NO_DEFECT`.

**FLAKY mechanism** — `isolation` · `race` · `timing` · `shared_state` · `teardown` ·
`environment` · `unknown`.

## Checks-ledger state

**Checks-ledger state** — exactly one per plan row and one per test:
`passed_green` · `failed:<verdict>` · `not_executed:<reason>` · `skipped:<reason>` ·
`env_blocked:<owner>` · `impossible` · `pending_implementation` · `deferred_by_decision`
· `not_verified_flaky` · `review_skipped` · `subtask_in_progress` · `waived` · `review_rejected` ·
`review_unverified` · `review_unrecognised:<word>` · `not_verified:<reason>` · `partial` · `error`.
`waived` — a person waived all its requirements: not passed, blocks nothing.

## Traceability result

**Traceability result** — what the person reads for a requirement × case row, never a
ledger state: `pass` · `bug` (names `BUG-n`) · `wait` (handed to a person, or planned
manual) · `blocked` (the stand; with the cause and whether a decision is recorded) ·
`not run` · `unreachable` · `deferred` (a recorded decision) · `not planned`.
**Level** — `unit` · `component` · `api` · `integration` · `e2e-ui` · `manual-agent` ·
`manual-human`. **Shape** — `new` · `extend` · `reuse` · `parameterize` · `consolidate`.
