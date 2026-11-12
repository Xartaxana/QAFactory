---
task: QA-1
created: 2026-09-11
rows_total: 3
candidates: 6
planned: 3
---

## Plan

| TS | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | R-1 | boundary @ apply_coupon cap | money | P0 | diff:src/app.py:12 | requirement:R-1 | `automate` - coverage gap on the API contract | new | api | boundary-value analysis |
| TS-2 | R-2 | state @ cart error banner | degraded | P2 | diff:src/ui/cart.js:44 | requirement:R-2 | `automate` - the error banner is visible after a rejected coupon | new | e2e-ui | ui check |
| TS-3 | R-3 | error-path @ expired coupon | blocked-flow | P1 | current-code:src/app.py:30 | history:the previous release refused expired coupons | `automate` - regression risk | new | api | error guessing |

## Recommended regression

- `poetry run pytest tests/test_cart.py` - covers the cart total path
