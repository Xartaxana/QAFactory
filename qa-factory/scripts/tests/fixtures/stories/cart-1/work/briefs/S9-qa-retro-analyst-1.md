# Brief - S9-qa-retro-analyst-1 - qa-retro-analyst at S9, CART-1

Scope: CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004, CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008, CART-1_TC_009, CART-1_TC_010, CART-1_TC_011, CART-1_TC_012. Environment: local; size XXL; source current-code.

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S9-qa-retro-analyst-1-digests.md

## Read these files

- qa-factory/artifacts/CART-1/pipeline.json (18.2 KB)
- qa-factory/records/journal.jsonl (78.6 KB) - slice it: `Grep -n` first, then Read with offset/limit
- qa-factory/state/cost/ (4 files)
- qa-factory/artifacts/CART-1/work/retro-numbers.md (5.0 KB)
- qa-factory/artifacts/CART-1/work/retro-numbers.json (26.4 KB)
- qa-factory/artifacts/CART-1/work/context-manifest.json (17.5 KB)
- qa-factory/strategy/test-strategy.md (3.1 KB)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- retro_numbers.py --task CART-1 - already run; every number is in work/retro-numbers.md and .json
- estimate_record.py --task CART-1 --facts <file> - the idempotent S9 estimate record
- project_decisions.py --root <project> add-finding - a finding for qa-factory/factory-backlog.md

## The rules code will apply to your handoff

Every number in retro.md comes from work/retro-numbers.md and .json, already computed by retro_numbers.py: do not re-add and do not re-price. The story's spend is the sessions the driver's own journal names - a roll-up over every session that merely mentions the ticket once published $1,911 against the $128 actually charged. Two records of the same money exist on purpose: the journal is what the CLI charged and is authoritative, the cost files are token-priced and mark themselves `provisional`; where they disagree, print the gap and say which is which. An unknown is written as `unknown`, never rounded into a fact. The precedent line is written by `estimate_record.py --task <T> --facts <file>`: the file holds `forecast` and `actual` objects and an optional `drivers` array, and code derives the row (ts, task, forecast, actual, delta, hit, drivers) from it; every wrong key is listed in one refusal. What outlives this story goes to the project's ledgers through `project_decisions.py --root <project> add-finding`, not into retro prose.

## The person's words that concern you

- 35 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S9-qa-retro-analyst-1-decisions.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
