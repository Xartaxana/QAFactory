# QA-1 — test report

<!-- Deliberately broken fixture: a hand-written ledger instead of the generated table,
     a delivery_ready that contradicts ledger.json, and a stage called complete while
     pipeline.json still has it pending. -->

## Verdict

`delivery_ready: yes` — S8 is complete and everything looks green.

Look here first: `src/app.py:12` — the cap works.

## Run this yourself

- `poetry run pytest tests/test_cart.py`

## Product problems

- Bugs to file: none.
- Nothing blocked the testing.
- Left unverified: none.

## Check coverage

| Row | State |
|---|---|
| TS-1 | passed |
| TS-2 | passed |

## Readiness within what was verified

| R | Status | Basis |
|---|---|---|
| R-1 | verified | TC-001 |
| R-2 | verified | TC-002 |
| R-3 | verified | TC-003 |

## Our tests and the factory

- Flaky: none.
- Into project docs: none.
- Still open: none.
