---
id: TC-008
title: Stored Last indexed after a scheduled reindex under queue pressure
area: datasource
priority: P2
status: Draft
channel: manual-agent
reuse_decision: new
updated: 2026-10-26
task: TP1-14857
covers: [R-13]
defect_class: concurrency
basis: "requirement:R-13"
then_oracles: [{"then": 1, "source": "unknown", "ref": "Q3"}]
question_thens: [{"question": "Q3", "then": 1, "readings": {"a": "the stored stamp after a queued scheduled run is the scheduled trigger time, never an older value", "b": "scheduled flows are out of scope; nothing is asserted"}, "not_needed": ""}]
plan_row: TS-8
reuse_reason: grep for scheduler and queue tests in testproject1_test_harness/tests/scheduler found no stamp or queue-pressure assertion
preconditions: [{"id": "PC-1", "kind": "env", "what": "a datasource can be put on a short cron schedule and the concurrency slots talkative by the case", "partitions": ["P-cron-queue"], "check": {"none": "scheduler timing and slot count are known to a person; the agent searches first"}}]
---
Requirements: R-13
Plan row: TS-8

Obligations: OB-8-1

evidence_policy: api (timeline of raw GETs with timestamps; completion condition: scheduled run finished or bounded timeout)

## Given
- Run-unique code datasource `tc008-<random>` COMPLETED with stamp B0, a short cron schedule set by the case (P-cron-queue), and settlement run-unique datasources so the scheduled run is queued. All deleted at the end.

## When
1. Let the schedule fire while all slots are busy.
2. Read the stamp, status, update_date repeatedly (raw GET) until the scheduled run finishes or the timeout passes.

## Then
1. The recorded stamp timeline is compared with B0 and with the scheduled trigger time; the expected value is open and follows owner question OQ-6; no verdict is issued (an older value after set_queued/clear_queued is recorded as evidence for the owner).

## Self-probe notes
- Probe: the scheduler is outside the MR scope; cron timing and installing are not deterministic, so a missing scheduled run is `inconclusive`.
- No expected literal; a trigger-time stamp is not a defect.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-8-1 scheduled write-back | open (OQ-6) | details API timeline | Then 1 | expected value; a -> manual-agent defect check, b -> skip |
