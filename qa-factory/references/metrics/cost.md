# Cost metrics

Definitions used by the renderer. Common semantics: [metric contract](../metrics-contract.md).

## C01 Tokens

Sum mutually exclusive normalized categories, grouped by activity/task, role, exact model, UTC request day

Source and update: U; T6.

Missing data: Partial usage explicitly marked; no synthetic usage

## C02 Estimated USD

Sum over requests/categories of tokens * applicable rate / 1e6; group as C01

Source and update: U; T6.

Missing data: Missing price -> known subtotal and missing counts; never total label. Unconfirmed default rate still computes with label

## C03 Reconciliation

Compare activity sum, role sum, model sum with same request-set total; exact tokens, USD tolerance 0.000001 before display rounding

Source and update: U; T6.

Missing data: complete equal -> matched; known unequal -> mismatch; incomplete -> unknown. Partial mismatch of provably identical complete subsets may be separately diagnosed

## C04 Human wait

Sum nonnegative time the story waited for a person: each answered question put to the person (tool call to its result, uncapped) plus each gap from completed assistant response to following human input within activity (capped, cost.human_wait_cap_s=1800; the part inside a question counted once). Stage machine time = stage wall time minus the waits inside the stage window, never below 0

Source and update: U; T6.

Missing data: No time evidence -> unavailable; a capture that did not measure question waits -> named floor and no machine time; an open question has no known length; label turn gaps capped estimate, not billable compute

## C05 Activity time

Sum min(adjacent main-chain request time gap,120s) within each uninterrupted activity segment; also capped-wall total with 1800s cap in details

Source and update: U; T6.

Missing data: Fewer than two timestamps -> no_data; never bridge across doctor/story segment boundaries; not exact machine time

## C06 Requests/tools/rework

Requests and tool calls by role/type; rework USD=sum costs attributed to dispatches explicitly linked parent_retry or repair purpose; percent over complete total. Relation to the retro (retro_numbers.dispatch_rounds): the retro counts a repair round only for a re-dispatch of the same (stage, role) scope that is NOT a continuation (retry_reason checkpoint/compaction/turn_budget/subagent_silent/no_digest_at_exit/host_error, contract.CONTINUATION_RETRY_REASONS); C06 counts every parent_retry link, so C06 rework >= the retro's repair-round cost

Source and update: U,E; T5,T6.

Missing data: Do not classify by prose name 'fix'; unknown dispatch-purpose leaves attribution partial

## C07 Time to first test

Earliest actual behavioral execution start - verified S0 start for task, seconds; exclude red probes/build/collection

Source and update: E,R; T2,T5.

Missing data: No execution yet -> pending; imported-only -> not_applicable; missing start -> unavailable

## C08 Tokenomics band hit

100 * completed, fully priced tasks whose cost in inclusive [lo,hi] / completed fully priced tasks with valid final size

Source and update: X,U; T6,T7.

Missing data: S9 complete but session cost provisional -> show provisional dot, exclude from finalized rate. No size or full price -> excluded count

## C09 Band vs actual

For each size show preserved band and median complete task USD, with n

Source and update: X,U; T6,T7.

Missing data: Display actual groups only once real X records exist; no filled-in demo rows for missing groups

## C10 Cost drift

Median((actual_usd-upper_band)/upper_band) over C08 population, %

Source and update: X,U; T6,T7.

Missing data: No eligible tasks -> no_data

## C11 MMRE and PRED(25)

MMRE=mean(abs(actual-upper_band)/actual); PRED25=100*count(error<=0.25)/n. Label upper-band benchmark, not an individualized forecast

Source and update: X,U; T6,T7.

Missing data: actual=0 excluded from these two ratios with reason; C08 still includes it

## C12 Estimate revisions

Counts of (size_initial,size_final) pairs per distinct completed task; same values counted unchanged; include final revision only

Source and update: X; T7.

Missing data: Missing size pair -> excluded count

## C13 Divergence drivers

Count completed tasks with each distinct recorded driver label, sorted descending then label. Share=tasks with driver/tasks with >=1 driver; multi-label sum can exceed 100%

Source and update: X; T7.

Missing data: Do not infer causal labels from cost. No drivers -> unavailable

## C14 Automation time benefit

Potential manual hours avoided=sum baseline_manual_minutes for distinct eligible successful routine automated executions /60. Net hours=avoided-verified automation authoring hours-maintenance hours

Source and update: optional benefit inputs,R; T2,input update.

Missing data: Exclude red probes, diagnostics, repair retries and imported duplicate receipts. No baseline/effort -> unavailable; never assume gap-based time is human effort. Label modeled benefit, not measured savings

## C15 Monetary ROI

(documented comparable counterfactual USD - complete actual total USD)/actual total USD; actual total includes model, infra and human costs without mixing hours and USD

Source and update: optional benefit inputs,U; T6,input update.

Missing data: No approved baseline or labor/infra inputs -> unavailable with exact missing fields. actual=0 -> undefined, not infinite. Never monetize found bugs using arbitrary severity weights
