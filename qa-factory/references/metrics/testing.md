# Testing metrics

Definitions used by the renderer. Common semantics: [metric contract](../metrics-contract.md).

## T01 Behavior verified

100 * current-task obligations whose reducer completion is evidenced / all approved current-task obligations, snapshot. Also counts by evidenced/failed/blocked/not_run/stale

Source and update: P,R; T1,T2.

Missing data: Before A: draft counts only, no approved ratio. Accepted gaps stay in denominator; regression excluded and counted separately

## T02 Critical behavior verified

T01 restricted to P0/P1 plan priority; show n and priority breakdown

Source and update: P,R; T1,T2.

Missing data: Unknown priority is a separate gap; it cannot be treated as noncritical

## T03 Test outcomes

Unique current instances per pass/fail/error/blocked/skipped/not_run/stale/ambiguous, per task/level/repo/owner. Preserve source statuses; no fabricated conversion of broken_run to test failure

Source and update: R; T2.

Missing data: Missing report means not_run/unknown per existing reducer, never zero failures = pass

## T04 Test pyramid

Counts and percentages of T03 instances by recorded level, with separate unknown/ambiguous and manual lanes; all outcomes included

Source and update: R,P; T1,T2.

Missing data: Unknown level remains in total and its own lane; no removal from denominator

## T05 Manual proof completeness

100 * approved manual-agent cases whose current accepted outcome includes all required evidence / approved manual-agent cases. Show failed-with-proof separately from passed-with-proof

Source and update: P,R; T1,T2.

Missing data: manual-human cases shown pending separately; missing evidence is not a pass

## T06 Open obligations and regression

Counts by kind/status and age; list recommended_regression checks explicitly 'not run by factory'

Source and update: P,F; T1,T2,T4.

Missing data: No scope registry -> unavailable; empty valid registry -> 0

## T07 Bug snapshot

Count unique bugs by severity/status; draft and published badges. Open statuses use adapter mapping, default local Open/Fixed/Reopened/Blocked/Intended, closed local Verified/Closed/Rejected/Duplicate

Source and update: B; T3.

Missing data: Unknown status in separate bucket. Inventory scope label always visible; no bugs in partial export is not project-wide zero

## T08 Area defect weight

Sum weights of unique known bugs per area, weights 8/5/3/1 unless configured. Display highest ceil(share*number_of_areas) areas sorted by weight then name; default share 0.5

Source and update: B; T3.

Missing data: Unknown severity count shown but excluded from weighted sum; missing area grouped Unknown. Label weighted count, not density

## T09 Bug age

max(0, as_of-created_at) days for each open bug; severity then descending age ordering

Source and update: B; T3,date.

Missing data: Missing/invalid date: age unavailable for that bug, row retained

## T10 Bug flow

Unique bugs created within window; unique bugs entering terminal closed state within window; separately transition counts if a bug closes more than once

Source and update: B; T3.

Missing data: Closed count requires transition evidence; current closed snapshot alone is insufficient

## T11 Rejected-bug cohort rate

100 * window-created bugs whose current disposition is Rejected / all window-created bugs. Explicit cohort-as-of label

Source and update: B; T3.

Missing data: Duplicate separate, not rejected. Missing disposition for cohort -> partial lower bound with known denominator

## T12 Reopen rate

100 * unique bugs with Fixed->Reopened transition in window / unique bugs entering Fixed or leaving Fixed to Reopened in window

Source and update: B; T3.

Missing data: Requires complete transitions over window for cohort. Otherwise unavailable, not count-based guess

## T13 Time to first fix

Median (first Fixed timestamp-created_at)/86400 for bugs whose first Fixed occurs in window; group by priority/area; n always visible

Source and update: B; T3.

Missing data: Need complete origin/first-fix evidence. Eligible excluded rows make result partial with included/eligible counts

## T14 Repeated status cycles

Count/list bugs with >=2 verified reopen transitions in available complete history; disclose history start

Source and update: B; T3.

Missing data: Legacy trusted reopen_count can be shown as imported total, not mixed with window rate. Discussion 'ping-pong' unavailable unless explicit structured dispute events exist; no LLM reading discussions for this metric
