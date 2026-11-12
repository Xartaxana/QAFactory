---
task: QA-1
created: 2026-09-11
rows_total: 3
candidates: 5
planned: 3
---

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | a coupon above the cap is refused | R-1 | boundary @ apply_coupon cap | money | P0 | diff:src/app.py:12 | requirement:R-1 | `automate` - coverage gap on the API contract, deterministic | new | api | boundary-value analysis |
| TS-2 | the order total matches the recalculation | R-2 | contract @ cart total recalculation | money | P0 | diff:src/app.py:20 | requirement:R-2 | `manual-agent` - one-off check against the live order record | — | api | state verification |
| TS-3 | focus returns after a rejected submit | R-3 | state @ coupon form focus | cosmetic | P3 | expected-contract | requirement:R-3 | `skip` - cosmetic, outside the diff, no user impact recorded | — | e2e-ui | exploratory |

## Recommended regression

- `poetry run pytest tests/test_cart.py` - covers the cart total path the change reuses
