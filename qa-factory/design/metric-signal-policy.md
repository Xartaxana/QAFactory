# Metric history and warning policy

`factory_dashboard.py` projects the 47 metrics and immediately evaluates warning rules.
Controller mutations, cost capture, bug imports, project decisions, validated artifact writes
and doctor invoke the same renderer/refresh path. No metrics agent or background schedule is
needed. Opening the HTML file does not run checks. The header states the last evaluation;
date-dependent changes are evaluated on the next factory event.

`state/metrics-history.json` retains one snapshot per UTC date. Re-rendering replaces that
day's point. Charts show consecutive complete observations; gaps break the series. History
starts with observed data, not a fabricated backfill.

The existing estimate calibration rule is built in as `legacy-estimate-v1`: three latest,
completed, fully priced precedents of the same size all above or all below the cost band.
Incomplete precedents cannot resolve an existing signal. Three in-range observations
confirm recovery. Other trend thresholds require explicit project policy; there is no
universal reject-rate threshold silently copied from the demo.

A second built-in rule, `hot-cache-v1`, warns when the hot cache share —
`cache_read / (cache_read + cache_write_5m + cache_write_1h + input)` — drops below
`metrics.hot_cache_min_percent` in `config.json` (default 90). It raises at most one signal
per task label as `dashboard_cost_groups.group()` rolls tasks up: every story, and also
Doctor, Onboarding, Environment-maintenance and Unclassified (id
`hot-cache-v1:story-<label>`). The signal's value is the lowest share among the label's own
share and each of its qualifying sessions, never a single project-wide average, so one cold
session cannot hide inside a healthy mean. A session is judged under a label by the requests
it has under THAT label, its pair, not by the whole session: a 1,000,000-token session with
1,000 Doctor tokens at 100% hot cache and the rest under story X at 50% gives the pair
(Doctor, session) 1,000 tokens, below the minimum, so Doctor raises nothing on it, and story X
is judged on its own 50%. A share counts only from a pair or label of at
least `metric_signals.MIN_HOT_CACHE_TOKENS` (200,000 tokens; the minimum applies to the pair's
tokens, 199,999 is not evaluated and 200,000 is), and the label's own share only
when its token composition is complete; with no qualifying share the label is left
`not_evaluated` rather than raising an alarm over a handful of requests. A session with no
request ledger (an old cost file, or a collapsed one whose requests were folded into `carry:`
rows) has no per-label split to take, so it keeps the whole-session rule: its whole composition
and token count stand under every label it lands in. A ledger that is only partly collapsed
(some `carry:` rows among real requests) is treated as such a whole session too, never half
by each rule, and the signal's `note` says which sessions were judged whole. The cold sessions
are listed inside the signal (at most 10 shown, lowest share first, then `+K more`), and
every share is shown with one decimal (the threshold test uses the unrounded value). Signals
of the earlier per-session form (`hot-cache-v1:session-<id>`) are dropped on refresh, since
the per-label signal lists the same sessions. A session the driver's journal names
(`artifacts/<task>/state/driver-runs.jsonl`) belongs whole to that journal's task: the
dashboard computes that binding once and hands it to `metric_signals.refresh(..., task_of=...)`,
the same one every other section that groups by task reads, so the sessions of a driver run
(which the capture files under "(no task)": a driver session opens no factory activity) are
listed under their story and never under Unclassified. A session a cost file tags to a task whose
journal does not name it has its own label `<task> - not launched by the driver`, so its
signal never rides on the story's id. With no journal under the root the grouping is exactly the
old one. An older `hot-cache-v1:story-Unclassified` signal is resolved, with the reason
`sessions moved to <task ids>` (every task named), when EVERY session it lists is present in the
refresh (has a cost file now), no longer sits under Unclassified, and was evaluated under its
new label. A listed session that the journal binds to a task but that has no cost file is a
missing observation and resolves nothing; a signal listing no sessions, or only sessions that no
longer exist, is left as it was, and so is one whose other sessions are still unbound. It goes through
the same `evaluate()`/lifecycle machinery as `legacy-estimate-v1` — a synthetic per-scope
metric fed into the shared rule engine — so it surfaces through the one `signals_html`
banner instead of a separate ad-hoc branch, and carries the same active/verifying/resolved
recovery states.

Illustrative configuration only — choose the policy with the project owner:

```json
{
  "metrics": {
    "signal_policy": {
      "version": "project-agreed-v1",
      "rules": [{
        "id": "rejected-handoffs",
        "metric": "F02",
        "field": "rate",
        "mode": "trend",
        "direction": "above",
        "threshold": 10,
        "recovery_threshold": 2,
        "min_sample": 20,
        "recovery_samples": 2,
        "owner": "orchestrator",
        "title": "Rejected handoffs increased",
        "next_action": "Review role/reason breakdown and linked handoffs"
      }]
    }
  }
}
```

For percentage metrics, trend thresholds are percentage-point differences. `absolute`
compares the current value; `trend` requires complete, non-overlapping windows of comparable
duration, scope and formula version. Rolling windows that overlap cannot trigger a trend
comparison. Missing history, partial metrics or insufficient samples produce `not_evaluated`.

`state/metric-signals.json` records stable identity, policy version, values, sample sizes,
source revision, time, evidence, owner, next action and `active / verifying / resolved`.
Repeating an observation or changing unrelated source files does not confirm recovery.
Removing a policy keeps unresolved warnings visible as not evaluated.

After an explicit human decision, record its reference:

```text
python scripts/metric_signals.py --root <project> --ack <signal-id> --decision-ref <recorded-human-decision>
```

This moves the signal to verifying; it never declares recovery. Worsening reactivates the
warning; fresh healthy observations meeting the recovery policy resolve it. The shared
header links to metric evidence on the appropriate tab and opens its details. Injection
and session restoration deliver the outstanding receipt to the orchestrator, which explains
actionable changes in the next user-facing result. Actual host delivery needs live hook
receipts; the local evaluator does not itself send notifications or messages.
