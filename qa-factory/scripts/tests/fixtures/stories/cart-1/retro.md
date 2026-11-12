# Retro - CART-1

## What went wrong and what to change

1. **Rework was the biggest spend in S5.** 11 repair rounds cost $7.08 of a $19.33 floor (retro-numbers.json `rework`). Four S5 automator rounds ran 47-66 requests each. Change: the TypeScript tooling gaps (FB-4, FB-6) need fixing upstream, so the rounds stop being spent on workarounds.
2. **15 gate blocks, where the norm is zero.** Each is the factory's checks refusing a step in a Playwright TypeScript project the tooling was built around pytest for. Change: FB-6 covers manifest reading, slice replacement and `run_suite --mine`.
3. **Time to the first test was 1h 7m**, and S5 took 8h 57m of machine time. Human wait in session was 5h 1m. Nothing halted (0 halts, 0 rejects).
4. **The price is a floor, not a total.** $19.33 is INCOMPLETE and not cross-checked: one record, no driver journal, 10 roles with no recorded usage. No orchestrator share is published. Do not quote it as the cost of the story.
5. **Gate B delivered with known gaps.** R-9, R-13 and R-16 have no case, and TC_009 is open. No MR, no bugs filed. Within these boundaries nothing further was found; these are not covered.

## Time

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

**Time to the first test:** 1h 7m. **Halts:** 0, waiting 0m 0s. **Human wait in session:** 5h 1m.

## Cost

**Story price: $19.33, not cross-checked; INCOMPLETE.** It comes from one record, the transcripts priced at list rates. The driver's journal names no session of this task, so the CLI's own charge is unknown. 1 session is still being written. Roles with no recorded usage: qa-automator, qa-case-critic, qa-case-designer, qa-code-critic, qa-doc-scribe, qa-failure-analyst, qa-requirements-tester, qa-runner, qa-scout, qa-test-strategist. The figure is a floor. Tokens recorded: 81,043,803. No orchestrator share is published while the figure is a floor.

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

**The rules cost $0.64**: 6,390,985 cache-read tokens over 475 requests. By layer: slices $0.38, charter $0.13, brief $0.07, common $0.06. The heaviest is `slices`.

## Marathons and what they spent turns on

Three most expensive dispatches (from `retro-numbers.json`):
- qa-automator S5 round 2: $1.47, 66 requests. Tools: Bash 54, Write 14, Read 6. Mostly running commands (suite and tooling attempts), with Write for test code.
- qa-automator S5 round 4: $1.31, 66 requests. Tools: Bash 54, Read 11, Write 7, Edit 5. Same shape: Bash-heavy iteration against the tooling.
- qa-automator S5 round 3: $1.09, 47 requests. Tools: Bash 42, Read 7, Write 6, Edit 3.

The dominant cost in all three is Bash, not authoring. This matches the TypeScript tooling friction above. S6 round 2 (qa-runner, 44 requests) was Bash 41, spent on the runtime-probe block and its workaround (FB-7).

**Rework:** 11 repair rounds (S4 designer and critic round 2; S5 automator and code-critic rounds 2-5; S6 runner round 2), $7.08. **Rejects:** 0. **Gate blocks:** 15. **Compacts:** 0.
**Test-execution jobs:** 15 (unscoped: 15), 80 test executions, 0 re-ran an already-green, unchanged test (0.0%).

## Gate-A disposition overrides

`test-plan.md` has no `overridden: true` rows. No disposition rule was overridden.

## Estimate vs actual

Size forecast `XXL` -> fact `XXL`, no re-estimation during the story. 16 requirements, 12 plan rows, 12 cases pinned, 10 runs of which 0 redundant.

## What happened to the process

- The story was first keyed ADD-TO-CART and re-keyed to CART-1, because the Jira key form rejects keys that are not ABC-123 (FB-8).
- The Playwright TypeScript project met a pytest-oriented factory (FB-4, FB-6).
- The S6 manual runner was blocked by the container-only runtime probe. It was fixed by a catch-all probe entry plus a stand-identity confirmation (FB-7).

## The human's answer

Question: "One question for the retro: what did you dislike in this session, what should change?"
Answer: declined to answer (the person said to continue with what exists). Recorded as FB-5.

## Routed out of the story

- Factory backlog: FB-5 (human feedback), FB-6 (TypeScript tooling), FB-7 (S6 probe), FB-8 (key form); FB-4 was already recorded.
- Obligations: none added. The uncovered R-9, R-13, R-16 and open TC_009 are already carried in `test-report.md`.
- Strategy documents: no fold. Nothing was learned that a strategy document owns beyond the tooling findings, which belong to the factory backlog.
