<!-- generated from plugin:references/vocabularies.md for qa-failure-analyst by scripts/contract_slices.py; edit the source, never this file -->
# Closed vocabularies

Every value below is verbatim, as `scripts/contract.py` holds it. Anything outside these
lists is an invented status the validator rejects on write.

## `execution_status`

**`execution_status`** (run report) — `passed` · `failed` · `env_blocked` ·
`not_executed` · `broken_run` · `timeout`. Computed from the run's own evidence, never
typed by a role.

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
