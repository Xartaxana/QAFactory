---
task: QA-1
created: 2026-09-11
ids: [R-1, R-2, R-3]
by_source: {story: 1, feature: 0, assumption: 0, discussion: 0, ac: 2, derived: 0}
confidence: high
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable |
|---|---|---|---|---|---|---|
| R-1 | A coupon above the cap is rejected with DISCOUNT_TOO_LARGE | ac | — | yes | AC-1 | diff:src/app.py:12 |
| R-2 | The cart total is recalculated once a coupon is applied | ac | — | yes | AC-2 | diff:src/app.py:20 |
| R-3 | The coupon field keeps focus after a rejected submit | story | — | yes | — | expected-contract |

## Contradiction matrix

| R | parent story/feature | area cases (TC-*) | area open bugs |
|---|---|---|---|
| R-1 | ok:STORY-9 | ok:TC-001 | n/a:no open bug in the coupon area |
| R-2 | ok:STORY-9 | silent | silent |
| R-3 | silent | silent | silent |

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-3 | focus stays in the field | focus moves to the error banner | where the next keystroke lands | reading A adopted |
