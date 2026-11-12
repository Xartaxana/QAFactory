<!-- generated from plugin:references/vocabularies.md for qa-retro-analyst by scripts/contract_slices.py; edit the source, never this file -->
# Closed vocabularies

Every value below is verbatim, as `scripts/contract.py` holds it. Anything outside these
lists is an invented status the validator rejects on write.

## Triage verdict and FLAKY mechanism

**Triage verdict** — `APP_BUG` · `TEST_BUG` · `TEST_BUG:collection` · `ENV_ISSUE` ·
`FLAKY` · `APP_CHANGED` · `CASE_DEFECT` · `ASSERT_STRICTER` · `RUNNER_MISREAD_EVIDENCE` · `NO_DEFECT`.

**FLAKY mechanism** — `isolation` · `race` · `timing` · `shared_state` · `teardown` ·
`environment` · `unknown`.

## Bug confirmation

**`confirmation`** (a `bug-drafts/*.json` draft and the `bugs/BUG-n.md` it becomes) — who has
seen the defect. A red test is a draft until someone reproduces it.

- `unconfirmed` — the default: nobody outside the run has seen it. Still filed when the person
  chooses it at gate B, and it counts toward nothing.
- `reproduced_by_factory` — the analyst saw it fail again (a rerun on fresh data, or its own
  script) and the code checked the receipt; no person has confirmed it. Derived by code from the
  draft's `reproduction`, never written by a role. It counts toward nothing and changes no verdict.
- `confirmed_by_person` — said so at gate B, in words the decision records. A bug filed before
  this field existed carries none and reads as this.
- `confirmed_by_rerun` — a second run reproduced it on another stand (a different `environment`
  in the run receipt). The same stand twice is not a second reading.

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
