# LOCAL-1 — retro

## What went wrong, and what to do about it

1. **The factory is pytest-centric; this TypeScript/Playwright project paid for it in rework.** 28 repair rounds cost $15.05 (`rework`), 41 gate blocks against a norm of zero. 14 qa-code-critic dispatches and 9 qa-automator dispatches in S5 alone. Change: give the factory a TypeScript manifest builder and mutation probe (backlog, local-calibration), so blocks stop being handed to the person one by one.
2. **No mutation probe ran on any TypeScript test (the person's waiver).** 0 green tests count as proven in the report; the 43 tests ran 150 times in 67 launches (0 re-ran an unchanged green test). Change: a probe for `.ts` specs; until then green stays "not verified by mutation".
3. **The price Then was pinned to an API field that does not carry a price.** The case designer tied it to `GET /api/cart`, which has no price: 11 CASE_DEFECT rows, delivery verdict `no`. Change: a case's oracle field is checked against the response shape at S4 (backlog); eleven instances await the owner (OB-28).
4. **The first test ran 3h 19m into the story** (`time_to_first_test`), and S6 took 4h 20m machine time for 2 dispatches (39 requests). Human wait in session was 2h 46m. Change: the manual capture tool could not sign in (TC_022, TC_023 left as a stand gap, OB-27), so a login probe belongs in S0, not at S6.
5. **The price of the story is a floor, not a total.** $35.36, `INCOMPLETE` (qa-automator has no recorded usage; no driver journal, so no cross-check and no orchestrator share). Nothing here says the orchestrator exceeded its limit of 35.0%; it is unknown.

## Time

| Stage | Seconds (retro-numbers.json `stage_times`) |
|---|---|
| S0 | 5 |
| S1 | 1845 |
| S2 | 543 |
| S3 | 3236 |
| S4 | 1396 |
| S5 | 15326 |
| S6 | 15637 |
| S7 | 2050 |
| S8 | 2216 |

Machine time per stage, human wait: 2h 46m in session; halts 0, waiting 0m 0s. Time to the first test: 3h 19m.

## Cost (copied from retro-numbers.md, INCOMPLETE)

**Story price: $35.36 — not cross-checked; INCOMPLETE.** One record only (transcripts priced at the catalogue's list rates); the CLI's own charge is `unknown` for every row because the story has no driver journal. Roles with no recorded usage: qa-automator. The figure is a floor, not a total. No orchestrator share is published while it is a floor.

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

**The rules cost $1.11** — 11,131,349 cache-read tokens over 815 requests at $0.1/Mtok. By layer: slices $0.65, charter $0.23, brief $0.13, common $0.10. The heaviest is `slices`.

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

## Marathons and what they spent turns on

- **qa-automator S5 round 2 (window 1)** — $2.26, 80 requests, 8,388,368 tokens. Tools: Bash 72, Write 11, Read 5, SubagentHandback 5, Grep 1, Edit 1. Almost all turns were shell commands: running the suite and the factory's checks against a hand-built TypeScript manifest, not reading or editing code.
- **qa-automator S5 round 8 (window 8)** — $2.22, 82 requests, 9,917,490 tokens. Tools: Bash 58, Write 14, Read 11, Edit 9, SubagentHandback 3, Grep 3. Again mostly shell: reruns and manifest/binding checks after edits.
- **qa-test-strategist S3 round 1** — $1.82, 28 requests, 3,617,163 tokens. Tools: Edit 77 (tool calls), Grep 11, Read 8, Glob 5, Write 3, SubagentHandback 2. It built the plan by many small edits to `test-plan.md` instead of one write; the following two repair rounds (S3 rounds 2 and 3) came from the plan check.
- **Orchestrator** — 386 requests, 82,247,029 tokens. Tools: Bash 32661, Read 14469, Edit 9426, Write 6299, Grep 4395, SubagentHandback 3517; Agent 39, AskUserQuestion 3.

## Rejects, rework, runs

Rejects: 0. Gate blocks: 41 (the norm is zero). Compacts: 1. Rework: 28 repair rounds, $15.05; the list is in `retro-numbers.md`. Test runs: 43 tests, 150 runs in 67 launches, plus 6 sensitivity probes: first run 43, after a red run 100, planned stage run 2, unknown cause 5. Redundant runs: 0 of 150 (0.0%). 1 job executed nothing and is not counted.

## Gate-A disposition overrides

`test-plan.md` has no `overridden: true` row: no disposition rule was overridden, nothing to calibrate.

## Estimate vs actual

Size forecast `L` -> fact `L`, no re-estimation during the story. 26 requirements, 26 plan rows, 24 cases pinned, 38 run(s) of which 0 redundant. Forecast from precedents: too few L stories on the function count to forecast from (0 of 3). Ledger record: written by `estimate_record.py` as the last step.

## What recurred (routed, see below)

- Factory tools assume pytest: manifest fragments for TypeScript by hand, `selector_args` with a single `--grep`, run-report instance-id spelling, `manifest_from_tests.py` failing on loop-generated titles, a window merge that wiped `then_bindings` of earlier windows, `obligation_hash` missing on manifest refs until window closure, `manual_capture.login.http` unable to sign in.
- A case oracle pinned to a field the API does not carry (price in `GET /api/cart`): 11 CASE_DEFECT rows.
- Gate-A answers about a requirement oracle (Q7: price at the moment of adding stays; Q9 answered `b` at the gate, later re-worded in the person's text as re-authentication): the intent is stated by the person, the code under test contradicts the first (TC_020 red on price only).

## The human's answer to the retro question

"Skip" — declined to answer.
