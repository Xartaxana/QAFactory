---
id: TC-014
title: Outcome of moving a user-scope integration into a project the user does not administer is recorded
area: integrations
priority: P1
status: Draft
channel: manual-agent
reuse_decision: new
updated: 2026-10-28
task: TP1-12586
covers: [R-15]
defect_class: permission
basis: "requirement:R-15"
then_oracles: [{"then": 1, "source": "unknown", "ref": "raise"}, {"then": 2, "source": "requirement", "ref": "R-15"}, {"then": 3, "source": "requirement", "ref": "R-15"}]
raise_questions: [{"then": 1, "question": "May a user move their own user-scope integration into a project where they have no admin role, and what must the system answer?", "source_says": [{"quote": "Changing the project of an existing project-scope integration requires admin permission on the target project", "where": "requirements-register R-13 (project scope only)"}], "severity": "major", "owner_role": "po_ba", "before": {"value": "unknown", "where": "user_settings.py before the change"}, "now": {"value": "no target permission check in update_user_setting", "where": "diff:src/testproject1/rest_api/routers/user_settings.py:247"}}]
question_thens: [{"question": "raise", "then": 1, "readings": {"a": "If U has no admin role on the target: the PUT is rejected with 4xx and the integration stays in its origin", "b": "If a user-scope move needs no target permission: the PUT answers 2xx and the integration is in the target"}, "not_needed": ""}]
plan_row: TS-14
reuse_reason: "new - grep user-scope PUT with project_name in tests: none"
preconditions: [{"id": "PC-1", "kind": "account", "what": "a user with no role in the target project, and a control user admin of the target", "partitions": ["P-norole", "P-admin-control"], "check": {"none": "the stand holds one role; a person says whether a second account exists"}}]
---
Requirements: R-15
Plan row: TS-14

Obligations: OB-17. Evidence policy: api. Required phases: before and after state of the integration and of the target project list, request and response, status. Completion condition: the PUT has answered and both reads are done. No-write proof is persistent before/after state only; it does not prove that no write was attempted. Missing evidence is inconclusive. The oracle is unresolved: the agent records the outcome and the owner judges it in the report; no pass or fail is asserted on the status in Then 1.

## Given
- A user-scope integration owned by user U with no role in the target project; a control user who administers the target.

## When
1. U sends the user-scope PUT with project_name = target.
2. Record the response, then read the integration and the target list.
3. P-admin-control: the admin of the target repeats the same on their own integration.

## Then
1. P-norole: the outcome (status, message) is recorded; the expected value is a question for the owner, no literal is asserted.
2. The state after the call is recorded and is self-consistent: either the integration is in the target (2xx) or still in the origin with fields unchanged (4xx), never in both or neither.
3. P-admin-control: the move succeeds and the integration is in the target.

## Self-probe notes
- Then 1 is `unknown` with a raised question; Thens 2 and 3 are consistency and control checks that do not depend on the answer.
- State is read through GET and lists, independent of the response.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-17 permission on user-scope move | unresolved | API response + state | 1, 2, 3 | oracle for Then 1 unknown |
