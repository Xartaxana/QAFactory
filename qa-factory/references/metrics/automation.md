# Automation metrics

Definitions used by the renderer. Common semantics: [metric contract](../metrics-contract.md).

## A01 First-attempt pass rate

100 * instances whose first conclusive behavioral attempt in each task+fingerprint passes / instances with a first conclusive pass/fail attempt; window by attempt timestamp

Source and update: R; T2.

Missing data: Execution errors/unknown results shown separately; incomplete attempt history -> unavailable or explicitly partial cohort

## A02 Current pass rate

100 * current passing instances / all approved selected automated instances, snapshot

Source and update: P,R; T1,T2.

Missing data: Pending/stale/skipped stay in denominator; not a quality certification

## A03 Flaky evidence rate

100 * unique task+instance+fingerprint with both pass and fail conclusive attempts / such identities with >=1 conclusive attempt in window. Require unchanged code/test/runtime/data-seed contract and allowed repeated-attempt provenance

Source and update: R; T2.

Missing data: No automatic reruns to populate rate. Show repeated-sample count; unverified equivalent inputs cannot establish flaky

## A04 Retry rescue

Count identities with fail then pass under same fingerprint; divide by identities with failed first conclusive attempt for rescue percentage

Source and update: R; T2.

Missing data: Fix changing fingerprint is repair, not rescue. Missing ordering -> unknown

## A05 Unexplained failure rate

100 * conclusive failed attempts not associated with a valid red_lock bug / conclusive behavioral attempts; window

Source and update: R,H; T2,T4.

Missing data: Report red-locked failures separately, never hide them; unknown lock linkage yields partial attribution

## A06 Automation risk coverage

100 * P0/P1 current-task obligations with accepted sufficient automated assertion links / all P0/P1 current-task obligations. Design metric, separate from executed T02

Source and update: P; T1.

Missing data: No area-level % inferred from arbitrary area names. Missing design assessment -> partial or uncovered, never sufficient

## A07 Run duration and volume

Job count; sum of actual ended-started execution seconds; median completed job seconds; unique instances and new/updated/reused tests by accepted lifecycle action

Source and update: R,P; T1,T2.

Missing data: Imported results show imported counts; missing duration excluded with n. Sum job time may exceed elapsed wall time under parallelism; label explicitly

## A08 Test health

Unique quarantined cases, active red_lock cases, open DEBT, past explicit sla_due debt. Snapshot

Source and update: H; T4,T2.

Missing data: No synthetic SLA from removed config. Missing full store inventory means known counts, not suite-wide clean

## A09 Duplicate execution

Count local behavioral attempts re-executing already-current passing instance/fingerprint with no invalidation and purpose initial/repair_verify; share of local behavioral attempts

Source and update: R,E; T2,T5.

Missing data: Allowed flaky_diagnostic/diagnostic and red proofs excluded and shown separately; this metric observes duplicates, never authorizes them

## A10 Reused evidence

Unique selected instances satisfied by imported or earlier fresh receipt without a new local launch / all selected automated instances, snapshot

Source and update: R,P; T1,T2.

Missing data: Reused receipt does not count as new run or extra saved hours automatically
