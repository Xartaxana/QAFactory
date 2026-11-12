# Original dashboard design requirements

Companion to [the repair plan](dashboard-cost-repair-plan.md).

## Owner requirements and design baseline

Restore the existing dashboard, rather than redesigning it. The baseline is `factory_dashboard.py` at `c9c956b4^`, cross-checked against the last committed project dashboard. Preserve its exact dark palette (`#101216`, `#14171c`, blue `#2297F6`, green `#2dd4a0`, amber `#FDB022`, red `#F9303C`, purple `#C084FC`), pill tabs, card borders, typography, donuts, pyramid geometry, obligation bars, age bars, cost tables and estimate dumbbells.

Stories remain separate: **feature -> story -> level -> check** in Testing, and one cumulative row per story in Cost. An aggregate Story amount may supplement those rows but must never replace them. The preview contains three stories, two features, several sessions per story, an all-green story, a story with failures, and a blocked story.

Default disclosure applies consistently to features, stories and levels: expand groups containing any non-green case (failed, blocked, not run, skipped, stale, error or ambiguous); collapse groups whose cases are all green. Manual expansion must always reveal the actual individual cases, including all passed cases. Never replace case rows with prose such as “Both checks have accepted evidence” or “8 accepted results.” Every row shows stable case ID, full name, individual source status, and evidence/result or a specific waiting/blocking reason; pending human cases include owner and trigger. Keep API and Component as separate levels. Missing evidence is not a green result. The mock must show all 60 named cases and reconcile their statuses to level/story/feature totals.

Keep supported widgets in their original positions and style. Remove only unsupported mechanisms or unsupported claims, with a widget-by-widget decision recorded below. Token composition and Next actions may fill spaces released by those removals. Do not introduce a new shell, new theme, or a general catalogue-table layout.

**By activity, removed.** It duplicated By task's money, un-rolled per
invocation, with rows nobody could identify (no date, session or stage). The two tables'
totals also disagreed by the cost of every story halt: task attribution (`task_at`, last
artifact-write marker) persists while a story is stopped waiting on a human; activity
attribution (`activity_binding`) is an explicit open/close interval and drops that wait
time to Unclassified. By task, sourced from `by_task`, is the correct "what did this story
cost" answer; see `references/metrics-contract.md`. Token composition is now one
third-width card — donut, legend with color/category/tokens/percent, and a hot-cache-share
headline — instead of two full-width cards of bare numbers.

Obligations mean unfinished checks, not discovered defects or automatic retests. Replace ambiguous `Obligations by type` / `open` / `ripe` presentation with **Remaining checks** / **Waiting for condition** / **Ready to perform**. Read readiness from an explicit recorded trigger/state; a missing environment or fixture remains waiting. A prepared first execution is ready only when its actual prerequisites are met. Show case/obligation identity, owner, reason and trigger in details. Do not infer readiness just from obligation type or age.

Consistency decisions: (1) fixed legacy chart colors coexist with higher-contrast muted text; (2) every non-green group expands, including pending human checks, not just failed stories; (3) all 47 supported metrics remain accessible but absent sources produce honest empty states; (4) illustrative alert thresholds and Terra prices never become production defaults; (5) event-driven evaluation replaces the removed scheduled analyst, preserving visible warnings; (6) package version 0.7.0 describes the new adapter and UI, while doctor must separately report whether this installed host has actually exercised each mechanism; a manifest version is never proof of parity. No changes to application code, tracker publication or existing approvals are required by this implementation.

The implementation must achieve behavioral parity with Claude Code for all factory mechanisms, not merely make the skills discoverable in Codex. See [the compatibility audit](codex-compatibility-audit.md) for reproduced gaps and the distinction between local tests and actual host integration.
