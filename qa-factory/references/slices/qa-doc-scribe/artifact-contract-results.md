<!-- generated from plugin:references/artifact-contract-results.md for qa-doc-scribe by scripts/contract_slices.py; edit the source, never this file -->
# Artifact contract — what gate B and closure are built from

The documents S8–S9 produce. Where they live: `artifact-contract.md`. The values they are
checked against: `vocabularies.md`.

## `work/ledger.md`

**Writer** `scripts/ledger.py` (code, never a role), S8. **Readers** `check_delivery.py`,
`traceability.py`, the dashboard — not the person: the ledger's states are the factory's
own words; the report's appendix is the human projection. **Shape** a
`| Ref | Kind | State | Detail |` table, one row per plan row and one per test, then any
superseded environment blocks, then a `delivery_ready: yes|after_checks|no` line and, when `no`, the
reasons **grouped under their owner** (`artifact-contract-ledger.md`): product side,
environment, review, and last the factory's own defects, reported and never asked. A
decision text repeated across rows is printed once as a footnote. **Validator** any hand
edit is a reject — the file is regenerated, not authored. It lives under `work/`.

## `test-report.md`

**Writer** `qa-doc-scribe`, S8. **Readers** the human at gate B, the next story,
`check_coverage.py`. This is the **only** report (a `results-brief.md` beside it was a strict
subset); the short form belongs in the gate-B **message**.

**Shape** — written from the decision down, in this order, because the reader does not
know the factory's words (on TP1-15045 the first line read "24 reasons on the product
side", twenty of them the factory's own bookkeeping):

| # | section | content |
|---|---|---|
| 0 | `# <TASK> — test report` | one paragraph: what the change is (yours); then the verdict block, which code renders with `report_facts.py --task <TICKET> --write` (verdict, counts, `delivery_ready:` line — you type none of them); one legend line for R / TC / TS / BUG |
| 1 | `## Proven — N green tests` | by area, from the run report and the critic's verdicts: the requirement in words, the case, the test files, the critic's and level words or "review not recorded"; an unverified test is not counted (see "Left with you") |
| 2 | `## Product bugs — N` | number · severity · R · TC · one line · place in the code; after the gate, where the record went |
| 3 | `## Left with you` | one item per `left_items` case (`--check` names a missing one): what to check, whether a test exists (with its `real_or_mock` from `ledger.json`, word for word), where to run, how, which answer is needed. Two code blocks close it: `### Added after gate B` and `### Regression to run` (the plan's list; never changes the verdict) |
| 4 | `## Skipped by the plan (approved at gate A)` | code-owned: what the plan chose not to check (a `skip` row, a gate A waiver), reason verbatim |
| 4b | `## Not proven, and what it costs` | code-owned: the checks that could not execute, each with what stopped it |
| 5 | `## Decided at gate B` | only after the gate: the person's words verbatim (`gates.B`, S8/S9 `stage_overrides`), where the bugs went, the MR reason |
| 6 | `## Factory defects — nothing is wanted from you` | two paragraphs that explain any gap between this report and the machine ledger |
| 7 | `## Size` | `Forecast:` and `Fact:` on their own lines, the re-estimation if one happened; no money — that is the retro's |
| 8 | `## Where to look` | only `understanding.md`, `test-plan.md`, `retro.md` and the appendix, sections by name |
| 9 | `## Appendix — traceability` | `traceability.py --render`, verbatim: one row per requirement × case (× Then group), sorted by R then TC |

**Traceability** (`work/traceability.json`, written by `traceability.py --write`, checked by
`--check`): a row is `{requirement, what, case, then[], tests[{instance_id, file}], level,
shape, result, bug?, basis}` with `result` from the closed list `pass · bug · wait ·
blocked · not run · unreachable · deferred · not planned` (`contract.TRACE_RESULTS`),
`level` from `contract.TRACE_LEVELS`, `shape` from `contract.TRACE_SHAPES`. Every register
R and every plan TC is present; a manifest row marked `SUPERSEDED DUPLICATE`, a run row
with no manifest instance and an `unresolved[]` row marked `STALE` never enter.

**Validator** sections in order; the `delivery_ready` line equals the word of `ledger.json`;
every register R and every plan TC in the appendix, which equals `--render` byte for byte; each
"Left with you" item names an R and a TC and carries "To check:" and "Needed:" or "How:";
no `work/` path, no `cv_…`/`ti_…` hash, no bare decision id without its words, no "look here
first", no machine-summary markers in the body; "Decided at gate B" quotes the recorded
words; the size cap on the hand-written prose (the appendix is machine text, excluded).
A stage the report names while `pipeline.json` has it `pending` or `halted` is NOTED to the author, never refused: the validator reads the id, not the wording.

`work/delivery-summary.json` stays the shared factual projection for the dashboard, the gate
B message and any authorized MR description; its rendered fragment lives in
`work/delivery-summary.md`, not in the report.
