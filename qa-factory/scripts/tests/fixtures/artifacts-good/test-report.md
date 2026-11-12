# QA-1 — test report

## Verdict

`delivery_ready: yes` — every plan row and every test reached a terminal state, every
requirement reached an outcome, and the one test carries a critic verdict.

Look here first: `src/app.py:12` — the cap is a hard refusal, not a clamp, so a mistyped
510 is rejected rather than silently trimmed.

## Run this yourself

- `poetry run pytest tests/test_cart.py` — covers the cart total path the change reuses

## Product problems

- Bugs to file: none.
- Nothing blocked the testing: the local stand answered the health check before the run.
- Left unverified: TS-3 (focus after a rejected submit), skipped as cosmetic at gate A —
  cosmetic impact only, no user-visible data or flow at risk.

## Check coverage

| Ref | Kind | State | Detail |
|---|---|---|---|
| TS-1 | plan_row | `passed_green` | TC-001 |
| TS-2 | plan_row | `passed_green` | TC-002 |
| TS-3 | plan_row | `skipped:cosmetic, outside the diff, no user impact recorded` |  |
| TC-001 | test | `passed_green` | tests/test_coupon.py::TC-001 |

## Readiness within what was verified

| R | Status | Basis |
|---|---|---|
| R-1 | verified | TC-001 automated, green on head abc1234 |
| R-2 | verified | TC-002 executed once by the runner, order record read back |
| R-3 | deferred by decision | plan row TS-3 skipped as cosmetic, agreed at gate A |

## Our tests and the factory

- Flaky: none observed this run.
- Test self-fixes: none — no selector or data preparation had to be repaired.
- Into project docs: `project-profile.md` — the cap constant is shared with the coupon
  admin screen.
- Still open: nothing in `obligations.md` for this ticket.

## Evidence

- `work/evidence/sanity-20260911-105500.json` — exit 0, 1 passed
- `work/evidence/tc-002-order-record.txt` — order 8812, total 180.00
