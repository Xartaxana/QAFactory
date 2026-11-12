---
task: QA-1
created: 2026-09-11
ids: [R-1, R-2, R-3, R-4]
by_source: {story: 2, feature: 0, assumption: 0, discussion: 0, ac: 2, derived: 0}
confidence: high
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable |
|---|---|---|---|---|---|---|
| R-1 | A coupon above the cap is rejected with DISCOUNT_TOO_LARGE | ac | — | yes | AC-1 | diff:src/app.py:12 |
| R-2 | The rejection is shown to the shopper without losing the cart | ac | — | yes | AC-2 | diff:src/ui/cart.js:44 |
| R-3 | An expired coupon is refused with COUPON_EXPIRED | story | — | yes | — | expected-contract |
| R-4 | A coupon may be removed and the total restored | story | — | yes | — | none |

## Contradiction matrix

| R | parent story/feature | area cases (TC-*) | area open bugs |
|---|---|---|---|
| R-1 | ok:STORY-9 | ok:TC-001 | silent |
| R-2 | silent | silent | silent |
| R-3 | silent | silent | silent |
| R-4 | silent | silent | silent |
