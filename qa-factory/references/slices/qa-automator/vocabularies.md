<!-- generated from plugin:references/vocabularies.md for qa-automator by scripts/contract_slices.py; edit the source, never this file -->
# Closed vocabularies

Every value below is verbatim, as `scripts/contract.py` holds it. Anything outside these
lists is an invented status the validator rejects on write.

## `unresolved[]` reason

**`unresolved[]` reason** (automation manifest) — `impossible` · `blocked_by_env` ·
`pending_implementation` · `blocked_by_check` · `contradicts_requirement` (the code does what the requirement
forbids: the row names the requirement id, the expected and the observed value) ·
`deferred_by_decision:<gate>`.
