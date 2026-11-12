# Dashboard restoration: metric coverage for 0.7.0

Status: implemented coverage contract, 2026-09-19. `test_dashboard_restore.py` checks all 47 IDs in the production renderer. This is not a host-parity certification.

Baseline: graphical renderer at `c9c956b4^`, compared with all **47** entries in [the current catalogue](metrics/catalogue.json): 14 Testing, 10 Automation, 8 Factory and 15 Cost. Keep original graphics and layout; correct obsolete source/formula semantics through the existing contract, without restoring retired metrics-agent or scheduled-run mechanisms.

`Demo` below means an illustrative value or chart is present in the proposed mock, not that a real host source has been verified. `Unavailable` means the supported metric keeps its place with the exact missing input. The original design preview has 42 demo metrics and 5 unavailable states. The production-renderer fixture displays only the values supported by its synthetic artifact files; missing historical cohorts remain explicit. Secondary details are expandable; the catalogue must not replace the original graphical overview.

| ID | Metric | Dashboard location | Mock state |
|---|---|---|---|
| T01 | Behavior verified | Testing / Behavior coverage and proof | Demo |
| T02 | Critical behavior verified | Testing / Behavior coverage and proof; P0/P1 detail | Demo |
| T03 | Test outcomes | Testing / traffic light; feature → story → level → check; source-status detail | Demo |
| T04 | Test pyramid | Testing / original pyramid; level counts and shares | Demo |
| T05 | Manual proof completeness | Testing / Behavior coverage and proof; human lane separate | Demo |
| T06 | Open obligations and regression | Testing / obligation bars and evidence details | Demo |
| T07 | Bug snapshot | Testing / severity × status, exported population | Demo |
| T08 | Area defect weight | Testing / top-area weighted ranking | Demo |
| T09 | Bug age | Testing / open-defect age | Demo |
| T10 | Bug flow | Testing / created and closed trend cards | Demo |
| T11 | Rejected-bug cohort rate | Testing / rejected-bug trend; cohort-as-of label | Demo |
| T12 | Reopen rate | Testing / Bug flow and trends | Unavailable: complete Fixed → Reopened history |
| T13 | Time to first fix | Testing / Bug flow and trends | Unavailable: complete first-fix timestamps |
| T14 | Repeated status cycles | Testing / Bug flow and trends | Unavailable: complete reopen history |
| A01 | First-attempt pass rate | Testing / Run dynamics trend + sample detail | Demo |
| A02 | Current pass rate | Testing / Run dynamics trend + selected denominator | Demo |
| A03 | Flaky evidence rate | Testing / Run dynamics trend + unchanged fingerprint/repeated sample | Demo |
| A04 | Retry rescue | Testing / Run dynamics detail | Demo |
| A05 | Unexplained failure rate | Testing / Run dynamics trend + red-lock detail | Demo |
| A06 | Automation risk coverage | Testing / Run dynamics trend, separate from T02 | Demo |
| A07 | Run duration and volume | Testing / duration trend; sum/median/jobs; new/updated/reused | Demo |
| A08 | Test health | Testing / Run dynamics detail | Demo |
| A09 | Duplicate execution | Testing / Run dynamics detail | Demo |
| A10 | Reused evidence | Testing / Run dynamics detail | Demo |
| F01 | Findings and DD | Factory / original donut, ages, deferred panel and findings | Demo |
| F02 | Rejects by role | Factory / "rejected handoffs" health card with its reasons (only when any exist) and the rate trend | Demo |
| F03 | Blocked/unsafe handoffs | Factory / the `gate_block` and `unsafe_completion` health cards (gate_block: events, unique findings, still open) and their trends | Demo |
| F04 | Long dispatches | Factory / long-dispatch card and request detail | Demo |
| F05 | Retries | Factory / "retries" health card: n of N dispatches (p %) with the split by cause | Demo |
| F06 | Blockers and lifecycle | Factory / "dispatches ended incomplete" health card with its reasons, lifecycle table and Next actions | Demo |
| F07 | Projection/evidence health | Factory / one "manifest bookkeeping" line under the health cards, linking to the findings about the factory | Demo |
| F08 | Orchestrator shares | Factory / separate token-share and cost-share trends | Demo |
| C01 | Tokens | Cost / cards, task, role, model, UTC day, composition | Demo |
| C02 | Estimated USD | Cost / cards and same groupings as C01 | Demo |
| C03 | Reconciliation | Cost / By day total and formula details | Demo |
| C04 | Human wait | Cost / Time, requests and rework | Demo |
| C05 | Activity time | Cost / capped active card and capped-wall detail | Demo |
| C06 | Requests/tools/rework | Cost / role requests, Top tools and explicit rework | Demo |
| C07 | Time to first test | Cost / timing details by story | Demo |
| C08 | Tokenomics band hit | Cost / original estimate donut | Demo |
| C09 | Band vs actual | Cost / original dumbbells by size and story precedents | Demo |
| C10 | Cost drift | Cost / estimate accuracy card | Demo |
| C11 | MMRE and PRED(25) | Cost / two upper-band benchmark cards | Demo |
| C12 | Estimate revisions | Cost / revision matrix | Demo |
| C13 | Divergence drivers | Cost / recorded-driver bars | Demo |
| C14 | Automation time benefit | Cost / Automation benefit and factory ROI | Unavailable: approved manual baseline and verified effort |
| C15 | Monetary ROI | Cost / Automation benefit and factory ROI | Unavailable: counterfactual, labor and infrastructure costs |

## Trends and rejection semantics

- Restore graphical trends for first/current pass, flaky evidence, risk coverage, execution time, unexplained failures, created/closed/rejected bugs, factory rejects, gate blocks, unsafe completions, and separate orchestrator token/cost shares. Preserve bug-reopen and first-fix trend locations with missing-history states until eligible observations exist. Include daily usage and estimated cost.
- Record series window, source, sample and exclusions. The mock uses six saved execution snapshots for 14–19 September; daily usage has a separate, explicitly labeled 18–19 September window. Snapshot rates are not summed. Event cards show window totals; their sparklines show daily counts. Duration card shows six-job total with individual-job duration trend.
- F02 counts distinct rejected handoffs, grouped by role and reason. Mock: 4 rejected / (16 accepted + 4 rejected) = 20%; role rows reconcile to those totals. Deduplicate by handoff identity. Repeated rejection of the same handoff is not an extra unique rejected handoff. Incomplete journal coverage yields a known count and partial/unknown rate.
- T11 counts rejected bug dispositions in a created-bug cohort. It is neither a role rejection nor a gate block. Duplicate bug dispositions remain separate.
- F03 gate-block and unsafe-completion events stay distinct; a gate block's identity is the finding it names, so re-blocking one finding after a waiver is one finding, not two. F05 uses explicit parent_retry links; it does not derive repair counts from rejects. Its value is the split by cause (`contract.RETRY_REASONS`), read from the dispatch's own `retry_reason` or classified from its parent when the story predates 0.7.15. The mock has 4 rejected handoffs, 2 gate blocks and 2 repair dispatches; these need not match.
- No F metric is drawn twice. The Factory tab has no "Quality and outcomes" widget block: F02, F03, F05, F06 and F07 each live in one "Factory health" card or line, with their trends and the full catalogue below them.
- A repaired code fingerprint is not a same-fingerprint retry rescue. No reruns, external bug-history fetches or model calls may be triggered solely to populate charts.

## Production acceptance

1. Every catalogue ID must map to a visible widget or an accessible detail in this inventory. A removed source is not authorization to remove a supported metric. No unexplained omissions when new catalogue entries are added.
2. Use common isolated event fixtures to verify each numerator, denominator, population, status and provenance; example labels and values in a visual mock do not prove the production reducer.
3. Replay handoff journals with accepted/rejected events, duplicate imports, multiple roles/reasons and missing windows. Verify F02, F03 and F05 remain independent and all role totals reconcile.
4. Exercise at least three historical dates for each eligible trend, including archived historical tasks. Missing observations create explicit gaps, never fabricated zeroes or misleading interpolation. Zero is valid only with complete evidence.
5. Test supported metrics with complete data and missing-data states. Reopen/first-fix/ROI must become real graphical widgets once their required inputs exist; unavailable is not permanent removal.
6. Check every tab and expanded detail under light and dark host themes, including hostile inherited table/text CSS. Normal text contrast must remain at least 4.5:1. Preserve the original palette for semantic charts; adjust muted text where required for readability. Verify 320px, 390px, 736px and desktop widths.
7. Compare restored screenshots to the old dashboard using matched fixtures. The release requires actual host evidence and the full compatibility acceptance in the repair plan, not merely a complete mock.
8. T03 coverage requires individual named case rows in every level, including all-green automation, agent and human checks. Expand non-green feature/story/level groups by default; collapse all-green groups without omitting their rows. Validate all 60 mock cases: 50 passed, 2 failed, 2 blocked and 6 not_run; story counts 32/18/10. Each row has its own ID, name, exact status and evidence or reason. A group summary is never a substitute for its case list.
9. Metric-value coverage does not establish warning coverage. Restore shared active/awaiting-verification warnings above all tabs, with event-driven rules, evidence, windows, sample limits and persisted lifecycle. The mock shows an explicitly illustrative F02 rise from 5% to 20%; the rule is a proposal, not implemented monitoring. See the warning acceptance section in the repair plan.
10. Hot cache share is a real, implemented built-in rule (`hot-cache-v1` in `metric_signals.py`, same terms as `legacy-estimate-v1`): one signal per task label (stories and Doctor/Onboarding/Environment-maintenance/Unclassified), valued at the lowest share among the label's own share and its qualifying sessions, not a project-wide average; the cold sessions are listed inside the signal (max 10 shown, then `+K more`), shares are shown with one decimal, and old per-session signals are dropped on refresh. Sessions/labels under `MIN_HOT_CACHE_TOKENS` (200k tokens) do not count, so a small session cannot trigger it. Known limit: a session that touched several labels is counted whole under each of them (backlog B-195). Threshold is `metrics.hot_cache_min_percent` in `config.json`, default 90. It surfaces through the shared `signals_html` banner, not a separate branch.
