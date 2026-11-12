## Retro numbers — CART-1

<!-- computed by scripts/retro_numbers.py; do not recompute by hand -->

**Story price: $19.33 — not cross-checked; INCOMPLETE.** It comes from one record, the transcripts priced at the catalogue's list rates: nothing could be compared against a second record (nothing was compared: the driver's journal names no session of this task; 0 priced from one record). 1 session is still being written and was not compared. roles with no recorded usage: qa-automator, qa-case-critic, qa-case-designer, qa-code-critic, qa-doc-scribe, qa-failure-analyst, qa-requirements-tester, qa-runner, qa-scout, qa-test-strategist. The figure is a floor, not a total. Tokens recorded in the cost files of these sessions: 81,043,803. Rates: the catalogue's list prices, revision provider-docs-2026-10-16-r1.

No orchestrator share is published while the figure is a floor.

**Price by agent.** Each row is that agent's share of the story's price, and the price column adds up to the story's price above, exactly: nothing is counted twice and nothing is left out. The two records it rests on are beside it, as they stand (the data-fetching calls are the scout's).

| Agent | Sessions | Transcripts at catalogue rates | The CLI's own charge | Price |
|---|---|---|---|---|
| orchestrator | 1 | $8.12 | unknown | $8.12 |
| qa-factory:qa-automator | 1 | $4.70 | unknown | $4.70 |
| qa-factory:qa-code-critic | 1 | $1.64 | unknown | $1.64 |
| qa-factory:qa-runner | 1 | $1.29 | unknown | $1.29 |
| qa-factory:qa-test-strategist | 1 | $0.75 | unknown | $0.75 |
| qa-factory:qa-case-designer | 1 | $0.72 | unknown | $0.72 |
| qa-factory:qa-scout | 1 | $0.61 | unknown | $0.61 |
| qa-factory:qa-requirements-tester | 1 | $0.45 | unknown | $0.45 |
| qa-factory:qa-case-critic | 1 | $0.42 | unknown | $0.42 |
| qa-factory:qa-doc-scribe | 1 | $0.32 | unknown | $0.32 |
| qa-factory:qa-failure-analyst | 1 | $0.31 | unknown | $0.31 |
| **Story** | 1 | $19.33 | $0.00 | $19.33 |

**The rules cost $0.64** — 6,390,985 cache-read tokens over 475 requests at $0.1/Mtok, the cache-read rate of claude-sonnet-5-5. By layer: slices $0.38, charter $0.13, brief $0.07, common $0.06. The heaviest is `slices` — a byte added there is billed on every turn of every dispatch of every story. (4 bytes per token, the model's cache-read rate, every request of every dispatch re-reading the whole prompt.)

**Friction with the factory's own code**

Friction: unknown — this story has no driver journal

| Stage | Dispatches | Requests | Tokens | Cost | Machine time |
|---|---|---|---|---|---|
| S1 | 1 | 22 | 1,554,112 | $0.61 (incomplete) | 5m 52s |
| S2 | 1 | 18 | 992,844 | $0.45 (incomplete) | 5m 27s |
| S3 | 1 | 12 | 952,833 | $0.75 (incomplete) | 7m 28s |
| S4 | 4 | 34 | 1,591,413 | $1.14 (incomplete) | 13m 11s |
| S5 | 10 | 286 | 23,211,702 | $6.34 (incomplete) | 8h 57m |
| S6 | 2 | 75 | 4,547,710 | $1.29 (incomplete) | 1h 18m |
| S7 | 1 | 17 | 876,836 | $0.32 (incomplete) | 3m 7s |
| S8 | 1 | 11 | 643,380 | $0.32 (incomplete) | 3m 29s |
| orchestrator | 1 | 182 | 46,672,973 | $8.12 | 1h 37m |

| Role | Dispatches | Requests | Tokens | Cost |
|---|---|---|---|---|
| qa-automator | 5 | 220 | 19,838,271 | $4.70 (incomplete) |
| qa-case-critic | 2 | 15 | 638,338 | $0.42 (incomplete) |
| qa-case-designer | 2 | 19 | 953,075 | $0.72 (incomplete) |
| qa-code-critic | 5 | 66 | 3,373,431 | $1.64 (incomplete) |
| qa-doc-scribe | 1 | 11 | 643,380 | $0.32 (incomplete) |
| qa-failure-analyst | 1 | 17 | 876,836 | $0.32 (incomplete) |
| qa-requirements-tester | 1 | 18 | 992,844 | $0.45 (incomplete) |
| qa-runner | 2 | 75 | 4,547,710 | $1.29 (incomplete) |
| qa-scout | 1 | 22 | 1,554,112 | $0.61 (incomplete) |
| qa-test-strategist | 1 | 12 | 952,833 | $0.75 (incomplete) |

**Three most expensive dispatches:** qa-automator S5 round 2 — $1.47, 66 requests, 6,610,577 tokens; qa-automator S5 round 4 — $1.31, 66 requests, 6,210,602 tokens; qa-automator S5 round 3 — $1.09, 47 requests, 4,391,466 tokens
**Rework:** 11 repair round(s) (S4/qa-case-designer round 2, S4/qa-case-critic round 2, S5/qa-automator round 2, S5/qa-code-critic round 2, S5/qa-automator round 3, S5/qa-code-critic round 3, S5/qa-automator round 4, S5/qa-code-critic round 4, S5/qa-automator round 5, S5/qa-code-critic round 5, S6/qa-runner round 2) costing $7.08.
**Rejects:** 0 · **gate blocks:** 15 (the norm is zero) · **compacts:** 0.
**Halts:** 0, waiting 0m 0s · **human wait in session:** 5h 1m.
**Time to the first test:** 1h 7m — the stretch before anything ran.
**Size:** forecast `XXL` -> fact `XXL` — no re-estimation during the story.
**Estimate vs actual:** size forecast `XXL`, 16 requirements, 12 plan rows, 12 cases pinned, 10 run(s) of which 0 redundant.
**Test-execution jobs:** 15 (unscoped: 15) · 80 test executions, of which 0 re-ran an already-green, unchanged test (0.0%).

**Resumes of role sessions:** unknown — the story has no driver journal (driver-runs.jsonl) (state/driver-runs.jsonl).
