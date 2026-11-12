---
id: TC-004
title: A datasource edit after a reindex keeps the new Last indexed
area: datasource
priority: P2
status: Draft
channel: auto
reuse_decision: new
updated: 2026-10-26
task: TP1-14857
covers: [R-4]
defect_class: seam
basis: "requirement:R-4"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-4"}, {"then": 2, "source": "requirement", "ref": "R-4"}]
plan_row: TS-4
reuse_reason: grep update_code_datasource users in testproject1_test_harness/tests/assistant/datasource and integrations found edits without reading the stamp; no test reads the stamp after an edit
preconditions: [{"id": "PC-1", "kind": "data", "what": "a git repository reachable through the GITLAB_PROJECT integration for a code datasource", "partitions": ["P-edit"], "check": {"env": "GITLAB_PROJECT"}}, {"id": "PC-2", "kind": "service", "what": "the deployed backend build contains MR 4566 (commit ed7d0291f911)", "partitions": ["P-edit"], "check": {"none": "build identity of the stand is known only to a person or the deploy pipeline"}}]
---
Requirements: R-4
Plan row: TS-4

Obligations: OB-4-1

## Given
- A run-unique code datasource (`tc004-<random>`), COMPLETED, created and deleted by the case (P-edit). It has been fully reindexed once by the case; stamp S1 read by an independent GET after COMPLETED; S1 differs from the pre-reindex baseline.

## When
1. Edit the datasource with a new run-unique description through the update call with `skip_reindex=true, full_reindex=false` (no reindex triggered; this writes the whole IndexInfo record).
2. Wait until the datasource is COMPLETED, then read the details (S2) by raw GET.

## Then
1. S2 `last_reindex_triggered_at` equals S1 (a full update does not write an older in-memory value back).
2. S2 description equals the new description (the edit really took effect, so Then 1 is not satisfied by a no-op edit).

## Self-probe notes
- Discrimination: a write-back of a pre-stamp object would restore the older value and fail Then 1; Then 2 closes the "edit ignored" masking path.
- S1 is read before the edit through a separate GET, not declaration.
- The oracle is AC-3 (reopen/refresh does not restore an outdated timestamp).

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-4-1 stamp survives full update | R-4 | details API before/after edit | Then 1, 2 | edit with reindex flag not covered |
