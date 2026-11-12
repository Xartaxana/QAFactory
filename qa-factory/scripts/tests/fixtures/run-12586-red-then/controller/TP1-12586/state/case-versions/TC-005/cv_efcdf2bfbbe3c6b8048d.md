---
id: TC-005
title: A user-scope integration PUT with a new project_name moves it, and a failing move leaves it untouched
area: integrations
priority: P1
status: Draft
channel: auto
reuse_decision: new
updated: 2026-10-28
task: TP1-12586
covers: [R-15, R-11]
defect_class: data-loss
basis: "requirement:R-15"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-15"}, {"then": 2, "source": "requirement", "ref": "R-15"}, {"then": 3, "source": "requirement", "ref": "R-11"}, {"then": 4, "source": "requirement", "ref": "R-11"}, {"then": 5, "source": "requirement", "ref": "R-11"}]
plan_row: TS-5
reuse_reason: "new - grep user_settings PUT with project_name in tests/integrations/user: none (T4 is project scope)"
preconditions: [{"id": "PC-1", "kind": "data", "what": "two projects the user administers, user-scope integrations created by the case", "partitions": ["P-user-move", "P-user-collision"], "check": {"case_seeds": "target project holding an integration with alias X; user-scope integration with alias Y"}}]
---
Requirements: R-15, R-11
Plan row: TS-5

Obligations: OB-6, OB-7. Q5 a: the behavior is intended.

## Given
- A user-scope integration I1 (alias Y). A target project the user administers (permitted, so the oracle for permission is not needed here).
- Partition P-user-collision: the target project already holds an integration with alias X.

## When
1. P-user-move: PUT I1 (user-scope route) with project_name = target and a new alias that does not collide; read it back.
2. P-user-collision: PUT a second user-scope integration I2 with a changed field (alias renamed) AND project_name = target, where the target already holds an integration with the same alias and type (forces the move to fail).
3. GET I2 and list the target project.

## Then
1. P-user-move: the PUT answers 2xx.
2. I1 is listed in the target project and no longer in the user-scope list.
3. P-user-collision: the PUT is rejected with a 4xx.
4. I2's changed field keeps its old value (neither half landed).
5. I2 is still where it was and the target holds no extra record for it.

## Self-probe notes
- Discriminating input for atomicity: a field change plus a move that is forced to fail by data (alias collision); a non-atomic save would persist the field change (Then 4).
- Reads via GET and lists, independent of the PUT. The collision is built from data, no mock.
- Unresolved: whether the collision is a real conflict on this API is a premise of the fixture; if the stand accepts it, the case reports the fixture as not forcing failure rather than passing.

## Obligation coverage
| obligation/part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|
| OB-6 user-scope move | R-15 | API PUT + lists | 1, 2 | permission on target not covered (see TC-014) |
| OB-7 atomic on failure | R-11 | API GET + lists | 3, 4, 5 | commit semantics in the seam is developer-owned (TS-13) |
