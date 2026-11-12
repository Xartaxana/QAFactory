## Retro numbers — LOCAL-1

<!-- computed by scripts/retro_numbers.py; do not recompute by hand -->

**Story price: $35.36 — not cross-checked; INCOMPLETE.** It comes from one record, the transcripts priced at the catalogue's list rates: nothing could be compared against a second record (nothing was compared: the driver's journal names no session of this task; 0 priced from one record). 1 session is still being written and was not compared. roles with no recorded usage: qa-automator. The figure is a floor, not a total. Tokens recorded in the cost files of these sessions: 144,988,164. Rates: the catalogue's list prices, revision provider-docs-2026-10-16-r1.

No orchestrator share is published while the figure is a floor.

**Price by agent.** Each row is that agent's share of the story's price, and the price column adds up to the story's price above, exactly: nothing is counted twice and nothing is left out. The two records it rests on are beside it, as they stand (the data-fetching calls are the scout's).

| Agent | Sessions | Transcripts at catalogue rates | The CLI's own charge | Price |
|---|---|---|---|---|
| orchestrator | 1 | $12.95 | unknown | $12.95 |
| qa-factory:qa-automator | 1 | $9.34 | unknown | $9.34 |
| qa-factory:qa-code-critic | 1 | $3.88 | unknown | $3.88 |
| qa-factory:qa-test-strategist | 1 | $2.46 | unknown | $2.46 |
| qa-factory:qa-case-designer | 1 | $1.65 | unknown | $1.65 |
| qa-factory:qa-failure-analyst | 1 | $0.97 | unknown | $0.97 |
| qa-factory:qa-runner | 1 | $0.97 | unknown | $0.97 |
| qa-factory:qa-requirements-tester | 1 | $0.91 | unknown | $0.91 |
| qa-factory:qa-scout | 1 | $0.83 | unknown | $0.83 |
| qa-factory:qa-case-critic | 1 | $0.74 | unknown | $0.74 |
| qa-factory:qa-doc-scribe | 1 | $0.46 | unknown | $0.46 |
| qa-factory:qa-bug-reporter | 1 | $0.20 | unknown | $0.20 |
| **Story** | 1 | $35.36 | $0.00 | $35.36 |

**The rules cost $1.11** — 11,131,349 cache-read tokens over 815 requests at $0.1/Mtok, the cache-read rate of claude-sonnet-5-5. By layer: slices $0.65, charter $0.23, brief $0.13, common $0.10. The heaviest is `slices` — a byte added there is billed on every turn of every dispatch of every story. (4 bytes per token, the model's cache-read rate, every request of every dispatch re-reading the whole prompt.)

**Friction with the factory's own code**

Friction: unknown — this story has no driver journal

| Stage | Dispatches | Requests | Tokens | Cost | Machine time |
|---|---|---|---|---|---|
| S1 | 1 | 32 | 2,200,573 | $0.83 | 30m 45s |
| S2 | 1 | 23 | 2,174,693 | $0.91 | 9m 3s |
| S3 | 3 | 57 | 5,123,589 | $2.46 | 53m 56s |
| S4 | 5 | 63 | 3,959,675 | $2.39 | 23m 16s |
| S5 | 23 | 542 | 43,434,437 | $13.21 (incomplete) | 4h 15m |
| S6 | 2 | 39 | 1,971,719 | $0.97 | 4h 20m |
| S7 | 1 | 30 | 2,509,477 | $0.97 | 34m 10s |
| S8 | 3 | 29 | 1,366,972 | $0.65 | 36m 56s |
| orchestrator | 1 | 386 | 82,247,029 | $12.95 | 3h 48m |

| Role | Dispatches | Requests | Tokens | Cost |
|---|---|---|---|---|
| qa-automator | 9 | 379 | 34,901,421 | $9.34 (incomplete) |
| qa-bug-reporter | 1 | 9 | 370,065 | $0.20 |
| qa-case-critic | 2 | 21 | 1,234,979 | $0.74 |
| qa-case-designer | 3 | 42 | 2,724,696 | $1.65 |
| qa-code-critic | 14 | 163 | 8,533,016 | $3.88 |
| qa-doc-scribe | 2 | 20 | 996,907 | $0.46 |
| qa-failure-analyst | 1 | 30 | 2,509,477 | $0.97 |
| qa-requirements-tester | 1 | 23 | 2,174,693 | $0.91 |
| qa-runner | 2 | 39 | 1,971,719 | $0.97 |
| qa-scout | 1 | 32 | 2,200,573 | $0.83 |
| qa-test-strategist | 3 | 57 | 5,123,589 | $2.46 |

**Three most expensive dispatches:** qa-automator S5 round 2 — $2.26, 80 requests, 8,388,368 tokens; qa-automator S5 round 8 — $2.22, 82 requests, 9,917,490 tokens; qa-test-strategist S3 round 1 — $1.82, 28 requests, 3,617,163 tokens
**Rework:** 28 repair round(s) (S3/qa-test-strategist round 2, S4/qa-case-designer round 2, S4/qa-case-critic round 2, S3/qa-test-strategist round 3, S4/qa-case-designer round 3, S5/qa-automator round 2, S5/qa-code-critic round 2, S5/qa-code-critic round 3, S5/qa-automator round 3, S5/qa-code-critic round 4, S5/qa-automator round 4, S5/qa-code-critic round 5, S5/qa-automator round 5, S5/qa-code-critic round 6, S5/qa-code-critic round 7, S5/qa-automator round 6, S5/qa-code-critic round 8, S5/qa-automator round 7, S5/qa-code-critic round 9, S5/qa-automator round 8, S5/qa-code-critic round 10, S5/qa-code-critic round 11, S5/qa-code-critic round 12, S5/qa-automator round 9, S5/qa-code-critic round 13, S5/qa-code-critic round 14, S6/qa-runner round 2, S8/qa-doc-scribe round 2) costing $15.05.
**Rejects:** 0 · **gate blocks:** 41 (the norm is zero) · **compacts:** 1.
**Halts:** 0, waiting 0m 0s · **human wait in session:** 2h 46m.
**Time to the first test:** 3h 19m — the stretch before anything ran.
**Size:** forecast `L` -> fact `L` — no re-estimation during the story.
**Estimate vs actual:** size forecast `L`, 26 requirements, 26 plan rows, 24 cases pinned, 38 run(s) of which 0 redundant.
**Forecast from precedents:** Too few L stories on the function count to forecast from (0 of 3).
**Test-execution jobs:** 67 (unscoped: 67) · 150 test executions, of which 0 re-ran an already-green, unchanged test (0.0%).
**Test runs:** 43 tests, 150 runs in 67 launches, plus 6 sensitivity probes (not counted as runs): first run 43, after a red run 100, planned stage run 2, unknown cause 5.
- 1 job executed nothing and is not counted.
- launches with an unknown cause: e6c2457a319bdf3ac0e4-reparse-a17a5e06e2d4, 4818d0a3e31035ac44c9-reparse-2a9f952c324a, d97d2f04d5be9dc15b05-reparse-59731cbb32f3, db96171cb1a2ca0e4f68-reparse-b091ef9f6e9d, df7f03cbb1698d353ef2.

**Resumes of role sessions:** unknown — the story has no driver journal (driver-runs.jsonl) (state/driver-runs.jsonl).
