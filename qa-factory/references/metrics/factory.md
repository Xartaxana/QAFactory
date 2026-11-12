# Factory metrics

Definitions used by the renderer. Common semantics: [metric contract](../metrics-contract.md).

## F01 Findings and DD

Counts by open/closed state and FB scope; open-item age days and weeks=days/7; due flags only explicit typed triggers

Source and update: F; T4,date.

Missing data: Missing/corrupt canonical registry -> unavailable, not 'no findings'; disclosed legacy fallback only when canonical absent

## F02 Rejects by role

Count unique rejected handoffs, group by role/reason; rejection rate = rejected handoffs / accepted+rejected handoffs within window

Source and update: E; T5.

Missing data: Incomplete journal coverage -> known count/partial rate; retry dispatch alone is not rejection

## F03 Blocked/unsafe handoffs

Separate counts of gate_block and unsafe_completion events

Source and update: E; T5.

Missing data: Neither absence of journal nor unknown event mapping yields zero. Rewrite obsolete tooltip promising break-glass success; do not change acceptance mechanics

## F04 Long dispatches

Number of role dispatches with >80 recorded model requests; show actual counts and max; orchestrator sessions listed separately

Source and update: U,E; T5,T6.

Missing data: Threshold is informational, not turns.soft and not hard budget. Partial usage shows 'at least'; no quadratic-cost certainty in tooltip

## F05 Retries

Controller dispatches with parent_retry as a share of all dispatches, split by the cause the parent recorded when it stopped (retry_reason)

Source and update: E; T5.

Missing data: No unstructured journal inference. A dispatch with no recorded cause is classified from its parent, never dropped

## F06 Blockers and lifecycle

Count/list active blocked/paused/halted tasks, stage, next action and exact reason; current revision

Source and update: E; T5.

Missing data: Controller is authority; do not infer success from artifact presence

## F07 Projection/evidence health

Count stale projections and missing proof/version links identified by existing validator; show revision and diagnostic

Source and update: E,P,R; T1,T2,T5.

Missing data: Renderer failure is distinct from product failure; no repair rerun

## F08 Orchestrator shares

Token share=100*orchestrator tokens/all tokens; cost share=100*orchestrator valued USD/all valued USD; distinct labels/trends

Source and update: U; T6.

Missing data: Cost share only with complete comparable valuation; token share can remain available with unknown prices

## F09 Orchestrator share over the limit

Stories whose orchestrator cost share exceeds retro.orchestrator_share_max (default 0.35), each with its share, the limit and the per-stage split of the orchestrator's own priced requests placed by that story's stage clock

Source and update: U,P; T6.

Missing data: A story with no orchestrator receipts, or one whose spend is a floor, is missing and never a zero share; a stage whose clock runs backwards places nothing and leaves those requests unattributed
