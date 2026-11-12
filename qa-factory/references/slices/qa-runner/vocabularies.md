<!-- generated from plugin:references/vocabularies.md for qa-runner by scripts/contract_slices.py; edit the source, never this file -->
# Closed vocabularies

Every value below is verbatim, as `scripts/contract.py` holds it. Anything outside these
lists is an invented status the validator rejects on write.

## `execution_status`

**`execution_status`** (run report) — `passed` · `failed` · `env_blocked` ·
`not_executed` · `broken_run` · `timeout`. Computed from the run's own evidence, never
typed by a role.
