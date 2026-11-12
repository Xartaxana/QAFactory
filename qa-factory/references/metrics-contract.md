# Metric contract

The four metric groups are [testing](metrics/testing.md),
[automation](metrics/automation.md), [factory](metrics/factory.md), and
[cost](metrics/cost.md). The renderer loads `metrics/catalogue.json` for its
Formulas expansion. Contract tests keep these descriptions and identifiers aligned.

Every value carries a formula version, source references, observation timestamp,
sample size and status: available, no_data, partial, unavailable, stale,
not_applicable or demo. Missing inputs never imply zero, success or a monetary saving.
A complete empty denominator means no_data; an unknown denominator means unavailable.
Partial numerators with a complete denominator are explicitly lower bounds.

A baseline is compared only on an equal formula version; a point of another version is an
incompatible baseline (no trend signal, no trend point), never a silently mixed one. Version 2
marks the metrics that read a usd figure: the price of a story now comes from the story's own
rate base (P18, 30.09), and the history priced with the 1.5x override is not comparable with it.
C02 (the subtotal itself), C06 (`rework_usd`), C08, C10 and C11 (a task's complete cost against
the USD band), C09 (the band and the median cost), C15 (the actual model cost in its
denominator) and F08 (`cost_percent`) are version 2; every other metric, C01 and C03 included,
stays 1. A new metric starts at 1 and moves only by its own entry in `metrics_projection.py`.

Window metrics use the last 30 UTC calendar days including today unless configured
otherwise; snapshots describe current accepted evidence. Archived tasks are excluded
from active snapshots but retained in historical costs and execution trends.
Red probes are proof, not product-test failures. Reused receipts are not new executions.
Framework-native parameter instances retain repository and profile identity.

Sources: P accepted plan and coverage; R immutable execution blocks and reducer;
B recorded bugs and explicit status history; F canonical registries; E controller
and journal events; U deduplicated usage; X S9 estimates; H inspected test health.
T1 plan/gate change; T2 run/import/invalidation/triage; T3 bug snapshot;
T4 registry/readiness; T5 controller event; T6 usage capture; T7 S9 persistence.
All refreshes are code-only, local and event-driven. No metrics agent or timer runs.

After triage or an approved external bug update, preserve any structured tracker history
already obtained using `bug_snapshot.py --root <project> --input <snapshot.json>`.
Do not fetch extra history merely to populate charts. The validated local snapshot has
`schema_version: 1`, `scope` (the actual exported population), `as_of` (UTC timestamp),
`evidence_refs`, and `bugs`. Each bug has a canonical tracker-qualified `id`, current
`status`, `severity`, optional `area`, `priority`, `created_at`, `history_complete_since`,
and `transitions` with `from`, `to`, `at`, `evidence_ref`. Missing history remains unknown.
Status names use the local contract; adapters must explicitly map tracker statuses.
The snapshot replaces earlier exported data; it does not assert project-wide completeness.
Local drafts remain separate unless their canonical ID exactly matches a snapshot item.

Historical exports are labeled and never silently merged into current rates.
The tokenomics bands retain their snapshot source/date. Estimate demos appear only
before the first real estimate record and never enter totals or alerts.

## Cost-file fields (`state/cost/<session_id>.json`, written by `cost_capture.py`)

`by_task[task]` includes role (subagent) usage folded into the task that dispatched the
role — the money a story cost includes the roles it ran, not just the main chain. Task
attribution (`task_at`: last artifact-write marker, persists while a story is halted) and
activity attribution (`activity_binding`: explicit open/close interval) answer different
questions and can disagree while a story is halted waiting on a human — story cost reads
from `by_task`, never from `by_activity`. `orchestrator` stays the main chain only, so a
share (orchestrator vs roles) is computable from `orchestrator.cost` against a task's total.

- `has_factory_activity` (bool) — true when `by_activity` has at least one entry whose
  `type` is `doctor`, `onboarding` or `story`; false for a session whose cwd merely sat
  inside an onboarded project (factory development, run analysis) with no such activity.
  Capture still runs for these sessions; only this flag distinguishes them.
- `incomplete_agents` (list of agent names, e.g. `qa-factory:qa-case-designer`) — every
  dispatch that was found (a `subagents/agent-*.jsonl` transcript, or a `subagent_stop`
  journal record with no matching transcript) but ended with zero recorded usage. Empty
  when every dispatch priced. A consumer must treat a non-empty list as "this session's
  cost is a lower bound", not as a free role.
- `incomplete_where` (list of objects `{agent, activities, missing}`) — where each journal-only gap of
  `incomplete_agents` fell: the role name, the activities its journal lines fall in (no repeats) and how many
  dispatches are missing. A gap that has a file keeps its place in `agents[]` and is not written here. Empty
  when no gap is journal-only; absent in a file written before it existed (a reader then falls back to the
  `agents[]` files of the same role, then to the session's story activity).
- `capture_logic` (string) — the stamp of the capture logic that wrote the file. A file whose stamp is not the
  reader's current one is recomputed by the recapture pass when its transcript is a file; a file with no stamp
  is the oldest logic.
- `usage_final` (object `{rule, reason, as_of}`, or null) — present only when `usage_completeness` is
  `complete` by a recapture that found the session ended: `rule` is `settled` (every file of the session closed)
  or `timed_out` (a turn left open, or a last line left unreadable, for the open limit of the project's `cost`
  block). Null or absent for a session finalised in any other way. A reader must not treat a missing object
  as an error.
- `priced_subtotal_usd` — the dollar amount of usage that DOES have a rate, summed even
  when `total_cost_usd` (or a `by_task[task].cost`) is `null` because some OTHER model in
  the same scope has no rate (a model `references/model-rates.json` does not list yet — a
  price is never invented; add it to the catalogue or to `cost.rate_overrides`). Present at session level and per task (`by_task[task].priced_subtotal_usd`); 0.0
  when nothing in scope is priced. `total_cost_usd` stays `null` whenever any priced
  category is missing — it is the honest "would be wrong if I guessed" signal, and
  `priced_subtotal_usd` is the honest "this much is certain" signal next to it.
- Rate precedence (one price list): `cost.rate_overrides` for a named model first, then the
  bundled exact-id catalogue (`references/model-rates.json`), and only for a model neither
  knows the legacy `cost.model_prices` family table (its provenance says
  `legacy_project_override`); a model nobody knows stays unpriced. A catalogue-known model is
  never priced by a family key. A cost file keeps the money pinned at capture; a reader that
  wants one price for every file calls `cost_capture.revalue_document(doc, cfg, catalogue)`,
  which re-prices the stored request usage in memory (never rewriting the file) and marks
  `repriced_at_read` (`catalogue_revision`, `rates`: catalogue / override / legacy / mixed,
  `unpriced_requests` when any request stays unpriced). On a collapsed file (no factory
  activity) the `by_task` / `by_activity` split is `null` with `reprice_note`, except a single
  key, which is the whole session.
