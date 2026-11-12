---
task: T-1
created: 2026-10-20
ids: [R-1, R-2, R-3]
by_source: {story: 0, feature: 0, assumption: 0, discussion: 0, ac: 2, derived: 1}
confidence: high
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact | delta |
|---|---|---|---|---|---|---|---|---|
| R-1 | The list endpoint returns the items of the project. | ac | — | yes | AC-1 | diff:app/api.py:10 | blocked-flow | changed |
| R-2 | The list endpoint refuses a missing project. | ac | — | yes | AC-2 | diff:app/api.py:20 | degraded | new |
| R-3 | The update endpoint answers 403 when the guard fails. | derived | aspect:roles-and-permissions | yes | — | diff:app/api.py:30 | degraded | new |

<!-- source and delta words as in the template -->

## Contradiction matrix

| R | parent story/feature | comments & notes (ticket + parent) | area cases | area open bugs |
|---|---|---|---|---|
| R-1 | ok:T-0 AC1 | silent | silent | n/a:no bugs |
| R-2 | silent | silent | silent | n/a:no bugs |
| R-3 | silent | silent | silent | n/a:no bugs |

## Behaviour claims

| R | before | before_ref | now | now_ref | differs | question | origin |
|---|---|---|---|---|---|---|---|
| R-3 | 400 | diff:-app/api.py:29 | 403 | diff:app/api.py:30 | yes | Q1 | |

<!-- origin: empty = written at S2 -->

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-1 | all items | the visible items | what the user sees | question at gate A |
