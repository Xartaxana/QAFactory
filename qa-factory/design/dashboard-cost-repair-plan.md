# QA Factory 0.7.0: Codex parity and original dashboard restoration

Status: implementation authorized; consistency review completed 2026-09-19. Target release: **0.7.0**. This is a significant host-support feature release. The companion mockup uses synthetic data only; implementation and native-host verification are tracked separately.

Follow-up status (2026-09-19): the installed 0.7.0 pilot exposed unresolved P0 failures. The [Codex scout reliability and pricing plan](codex-scout-reliability-plan.md) is mandatory remaining scope, with [incident evidence](codex-scout-incident-2026-09-19.md). Implementation records below do not establish operational parity. Repairs are implemented in 0.7.1; live acceptance remains separate.

## Owner requirements and consistency decisions

The [complete design contract](dashboard-design-contract.md) preserves the old theme/widgets, separate stories, full named test rows and default disclosure, readable contrast, obligation semantics, truthful missing data and removal of unsupported mechanisms only. No requirement is dropped by splitting this plan into focused references.

## Verified problems

- Commit `c9c956b4` replaced substantial parts of the graphical dashboard with catalogue tables. The installed renderer matches the repository renderer.
- The inspected Codex run has no `qa-factory/state/cost/` or `state/activities/` evidence. Cost metrics are unavailable, not zero.
- The session invoked activity capture without a session identity. `activity_capture.py` silently returns when no identity is supplied; its fallback uses `CLAUDE_SESSION_ID` only. It also requires an explicit invocation identity to classify a start.
- Readiness describes a shipped Claude transcript adapter and no verified adapter for other hosts. A host-neutral usage producer is required before claiming Codex cost support.

## Host integration, activities and pricing

The complete P0 requirements and acceptance criteria are in [Codex integration and cost acceptance](codex-repair-acceptance.md). They remain mandatory scope.

## 4. Restore the original presentation with selective removals (P1)

Reuse original renderer components and CSS, rather than re-creating similar components. Retain Testing / Cost / Factory navigation and the current deterministic metric projection. Keep formulas, source, sample, freshness and exclusions expandable without replacing the graphical overview.

The [47-metric coverage inventory](dashboard-metric-coverage.md) is required acceptance scope. The first preview omitted supported trend and reject widgets; a graphical overview alone is not complete restoration. Map every T/A/F/C identifier to a widget or accessible detail and keep precise missing-source states. Restore execution/bug trends, role/reason rejects with rates, long dispatches, explicit repair chains, lifecycle/evidence health, separate orchestrator token and cost trends, timing/rework and estimate-accuracy views. Do not confuse rejected bugs, rejected handoffs, gate blocks and repair iterations.

- Testing: original traffic-light donut, actual pyramid widget, obligations bars, feature/story/level disclosures and supported bug snapshots. Keep manual and pending lanes; auto-expand red/blocked stories and collapse completed green stories. Never merge distinct stories into one detail panel.
- Cost: original colored summary cards and By task / By agent / By model / By day / Top tools sections. Show each story separately across all its sessions, with doctor, onboarding and unclassified rows outside story subtotals. Preserve estimate donuts, bands, precedents, revisions and recorded-driver views when data supports them; add Token composition in freed space.
- Factory: original findings/decisions donut, age chart, deferred-decision panel, findings table and health cards. Replace the retired Cadences widget with Next actions; add mechanism receipt details under health.
- Missing data: use an actionable empty state with the specific missing source. Distinguish unavailable, no data, partial and stale. Do not fill the page with repeated unavailable catalogue rows.
- Preserve the existing dark appearance, geometry and semantic colors. Responsive adjustments must not turn the pyramid into a bar-list redesign. Maintain keyboard access and readable narrow-screen layouts.

| Original block | Decision for 0.7.0 | Data/behavior condition |
|---|---|---|
| Traffic light, pyramid, obligations | Keep original components | Current accepted evidence, correct denominators |
| Feature/story/level/check hierarchy | Keep and test with many stories | Task identity survives multi-session runs and archive filtering |
| Severity/status, area ranking, age, reopen/transition views | Keep original layouts | Structured bug snapshot/history; partial scope labelled |
| Cost cards and task/agent/model/day/tool tables | Keep | Recorded usage and explicit attribution; unknown USD stays unknown |
| Estimate hit/bands/precedents/revisions/drivers | Keep | Existing contract eligibility; provisional tasks excluded where required |
| Findings, deferred decisions, age and health | Keep | Canonical registries and event receipts |
| Scheduled Cadences, maintenance schedule, daily/weekly metrics-agent claims | Remove | Not supported by the current event-driven factory |
| Hardening and baseline-delta assertions | Remove obsolete labels; retain supported execution evidence | Never imply removed hardening runs occurred |
| Hand-authored metrics-board trends | Replace source, retain visual widget if evidence supports it | Compute from actual events; otherwise precise empty state |
| Inferred discussion ping-pong | Remove inference | Show only explicit structured status transitions |
| ROI/time savings | Conditional original widget, not an unconditional removal | Approved baseline and labor/infra inputs required; otherwise compact unavailable state |
| Token composition / Next actions | Add in released positions | Usage categories / canonical blockers and decisions |

The preview's mock amounts and model label are illustrative and do not establish a real tariff. Demo data must live in isolated preview fixtures and never enter production projections, totals or alerts.

## Metric warnings

The complete signal rules, lifecycle, refresh and delivery requirements are in [dashboard signal acceptance](dashboard-signal-acceptance.md). They remain mandatory scope.

## 5. Recover historical evidence, then regenerate (P1)

For the inspected run, inventory actual surviving host evidence before attempting recovery. Explicit tool-call timestamps and invocation IDs may support recovered activity boundaries; record the recovery method and confidence. Do not infer activities from prompt prose. Attribute only at the granularity the usage source supports; retain the rest as unclassified or unavailable.

Import verified evidence idempotently and regenerate the dashboard. Preserve existing artifacts and the previous dashboard for comparison. Do not overwrite the project's configuration or strategy to repair presentation. Do not promise exact historical USD if usage or tariff evidence is missing.

## Validation

Run the [complete acceptance matrix](dashboard-release-validation.md), including all 47 metrics, individual cases, contrast, event replay, host lifecycle and upgrade tests.

## 7. Release 0.7.0 (required)

Set the implementation version to 0.7.0 now; publish only after native parity acceptance. Bump the QA Factory release from 0.6.0 to **0.7.0** in all four current host manifests: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.plugin/plugin.json`, and `.kimi-plugin/plugin.json`. Inventory any new package metadata and marketplace references and keep the QA Factory release identity consistent. This package currently has no `package.json` or OpenCode server version. Do not apply an unrelated five-manifest rule of another marketplace to this package.

Add the 0.7.0 changelog entry describing native Codex support, enforced event adaptation, activity/cost support, restored dashboard and compatibility limits. Update INSTALL/UPGRADE/README with supported and actually tested host versions, hook review/trust instructions, cache refresh and migration steps. Preserve project configuration, story state, historical evidence and approvals. Test upgrading a copied 0.6.0 project on both hosts and the version shown by doctor and dashboard. The version identifies the new implementation; it does not certify a running host or publish a release.

## Delivery order and completion criteria

Deliver host installation/event normalization and enforcement first, then role injection/lifecycle, usage and pricing, original-dashboard restoration, historical recovery, cross-host acceptance and the 0.7.0 release. The renderer can be developed against isolated fixtures while adapters are established, but cannot be presented as real telemetry support before validation.

Done means all critical factory mechanisms behave at least as well on Codex as on Claude Code, with observed host evidence; doctor/onboarding and each story have attributable usage; USD has defensible pricing and labels; the original dashboard is preserved except for explicitly approved unsupported blocks; and release 0.7.0 passes installation and migration checks on both hosts.

## Implementation record (2026-09-19)

- Implemented native event normalization, atomic multi-path guard checks, role injection and export, native input/output encoding, dispatch identity binding, repair lookup and observed hook receipts. Interactive shell writes are explicitly blocked where per-command inspection cannot be guaranteed.
- Added response-scoped Codex usage, disjoint activity continuation/final-response closure, individual story/doctor/onboarding grouping, exact model lookup and Terra standard API reference pricing with the 272k context boundary. The observed 0.155.0-alpha.2.6 transcript is evidence of the usage format, not proof of plugin hook activation.
- Restored original graphics, colors, full case rows and all-non-green disclosure; all 47 definitions remain expandable. Added history, rule evaluation, persistent warning states and event-driven header warnings. New thresholds require an explicit versioned policy; the original three-precedent estimate rule is built in.
- Updated all four manifests and all three skills to 0.7.0. Installation/migration instructions preserve existing task state.
- Validation: real renderer fixture contains 60 named cases, three stories and eight sessions; individual statuses and group totals reconcile. Native transport, signal lifecycle, usage and full regression results are recorded in the compatibility audit.
- Historical recovery applied: 81 recorded responses imported idempotently into the inspected project, with reviewed tool-call boundaries and explicit recovery provenance. Previous HTML/metrics were preserved; missing intervals remain unclassified. No project configuration or strategy was replaced.
- Remaining release gate: actual installed/trusted Codex and Claude host workflows, compaction/interruption and child delivery must produce observed receipts. Source tests cannot certify these. Historical imports preserve missing activity boundaries; no prompt-based attribution.
