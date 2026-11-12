---
id: TP1-15045_TC_014
title: Validate endpoint refuses unknown workflow, missing project access and missing WRITE ability
area: workflow-visual-diff
priority: P0
status: Draft
channel: auto
reuse_decision: new
updated: 2026-10-01
task: TP1-15045
covers: [R-16]
defect_class: permission
basis: "requirement:R-16"
plan_row: TS-14
reuse_reason: grep "/validate" in testproject1_test_harness/tests finds no permission test
preconditions: [{"id": "PC-1", "kind": "account", "what": "a non-admin user inside W's project with read-only ability (no WRITE)", "partitions": ["P-nowrite"], "check": {"env": "TC014_READONLY_USER_TOKEN"}}, {"id": "PC-2", "kind": "account", "what": "a non-admin user outside W's project", "partitions": ["P-noproject"], "check": {"env": "TC014_OUTSIDE_USER_TOKEN"}}]
---
Requirements: R-16
Plan row: TS-14

Obligation: OB-14. P-unknown runs on localhost; the role partitions need a second user (preview).

## Given

- Own workflow W (marker `TC014-<uid>`), and a before-state read of W.
- Independent expected result per partition: P-unknown 404 (R-16); P-owner 200; P-noproject and P-nowrite: refused with a 4xx and no validation payload. The exact status code for these two is oracle_unknown (no source names it; carried to Gate A as a question to the owner), so the assertion is "4xx, not 2xx, not 5xx" until answered.

## When

1. P-unknown: POST `/v1/workflows/<random uuid>/validate` as the superadmin.
2. P-noproject: POST as a user outside W's project.
3. P-nowrite: POST as a user in the project with read-only ability.
4. P-owner (control): POST as the owner with a valid body.

## Then

1. P-unknown: 404.
2. P-noproject: a 4xx refusal (exact code oracle_unknown, owner question), and the response carries no validation details of W's config (payload inspected).
3. P-nowrite: a 4xx refusal (exact code oracle_unknown, owner question), nothing validated: no validation messages in the payload.
4. P-owner: 200, so the denials are not a generally broken route.
5. W's stored config and version list are unchanged after all calls (read by GET as the owner).

## Self-probe notes

- Control partition separates "refused by permission" from "route broken".
- An unexpected 5xx after confirmed preconditions is a failed outcome for triage.
- No-leak is checked on the response payload directly.

## Obligation coverage

| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-14 unknown id | R-16 | API | Then 1 | none |
| OB-14 no project / no WRITE | R-16 | API | Then 2, 3, 5 | needs second user |
