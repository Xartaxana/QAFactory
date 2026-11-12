<!-- generated from plugin:references/vocabularies.md for qa-requirements-tester by scripts/contract_slices.py; edit the source, never this file -->
# Closed vocabularies

Every value below is verbatim, as `scripts/contract.py` holds it. Anything outside these
lists is an invented status the validator rejects on write.

## Observable source

**Observable source** — `diff` (this story's implementation) · `current-code` (existing
behaviour on the default branch) · `expected-contract` (requirement, ticket, owner
answer, spec). Every observable names one.

## Oracle basis

**Oracle basis** — `requirement:<R-n>` · `external:<ref>` · `history:<ref>`. A
new-behaviour row (`fit: new`, or `pending_implementation`) may use only `requirement:` or
`external:`; `history:` or an observable with `source: current-code` there is rejected —
current code never becomes the oracle for new behaviour.
