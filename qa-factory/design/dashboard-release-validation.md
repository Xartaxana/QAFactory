# QA Factory 0.7.0 validation matrix

Companion to [the repair plan](dashboard-cost-repair-plan.md).

## 6. Validate and deliver (P1)

- Adapter and attribution fixtures: cumulative/delta semantics, cache inclusion, missing model/rate, repeats, interrupted streams, continuation, nested activities, child usage and late final-response usage.
- Reconciliation fixtures: complete, partial, unclassified and external-consumer datasets; grouping invariance and repeat-import idempotence.
- End-to-end: doctor, multi-turn onboarding and at least three distinct stories on verified Codex and Claude hosts; assert hook receipts, injection, gate behavior, marker files, usage import, readiness and dashboard totals agree. Include two simultaneous story contexts and multi-session continuation of one story.
- UI: complete, partial pricing, unsupported telemetry, empty and stale data; desktop and mobile; tabs, expandable details and keyboard navigation.
- Case disclosures: assert default open state from actual child statuses at feature/story/level depth; manually expand a green story and every green level and verify complete named case rows. Check agent evidence and each human-case trigger separately, distinct blocked versus not_run statuses, and row-to-aggregate reconciliation. Use full names on narrow screens, with contained horizontal table scrolling if needed.
- Metric coverage: all 47 catalogue IDs mapped and checked; historical trends and factory rejects are mandatory. Verify each role/reason subtotal, accepted+rejected denominator, event deduplication and incomplete-journal state. Contrast checks include expanded table rows under both host themes, preventing dark text on dark surfaces.
- Regression: existing metric-contract, usage/activity, controller, execution, publication, hook and dashboard/event tests. Compare original and restored screenshots using the same fixtures. Every visual difference must map to an approved removal, evidence correction or targeted replacement; no unrelated redesign.

## Implementation validation record (2026-09-19)

- `selftest.py --tests`: **74/74 test modules passed**, including native host transport, historical recovery replay, activity boundaries, dashboard, controller, execution and publication gates.
- `install_smoke.py`: **passed**, including literal Windows launcher commands, empty/data dashboards, injection, validator, audit and package hygiene. This is explicitly an isolated source smoke.
- `selftest.py --roots --lang --limits --wiring`: **5/5 passed**. The Windows sandbox initially denied temporary fixture directories; the rerun with normal temporary-directory access passed.
- Final focused rerun: **9 native-host tests and 4 dashboard tests passed**, including native warning output, historical import replay and gaps/incompatible cohorts in charts. The 60 named cases reconcile to 50 passed, 2 failed, 2 blocked and 6 not run; three stories remain separate.
- Chromium: tabs, shared warnings, metric navigation, all expanded details and widths 1160/736/390/320 passed. Text contrast passed in light/dark browser preferences (4.5:1 normal text, 3:1 large text).
- Reviewed historical import applied to the inspected project, preserving the previous HTML and metrics. 81 unique response records; 10,784,922 tokens; standard API reference subtotal $2.7986828. Doctor $0.369212, onboarding $0.9425888, story $0.0924484, unclassified $1.3944336. Original activity receipts are missing: reviewed command boundaries supply partial attribution, not a complete invoice or inferred prompt classification.
- **Not certified:** installed/trusted native host workflows, real child delivery, compaction/interruption and paired Claude/Codex acceptance. The neighboring task used an older cached plugin; source edits do not hot-reload it. See [native acceptance](codex-native-acceptance.md).
- Before staging, standalone `--hygiene` flagged newly authored source files because its package inventory is `git ls-files`. The install smoke's leftover check passed. Delivery includes the reviewed new package files in version control and reruns the inventory check before installation.
