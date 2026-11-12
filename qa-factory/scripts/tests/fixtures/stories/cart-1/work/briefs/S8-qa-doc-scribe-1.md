# Brief - S8-qa-doc-scribe-1 - qa-doc-scribe at S8, CART-1

Scope: CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004, CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008, CART-1_TC_009, CART-1_TC_010, CART-1_TC_011, CART-1_TC_012. Environment: local; size XXL; source current-code.

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S8-qa-doc-scribe-1-digests.md

## Read these files

- qa-factory/artifacts/CART-1/work/ledger.json: not written yet — that is the path it will have, and nothing else is it
- qa-factory/artifacts/CART-1/work/triage.json (3.5 KB)
- qa-factory/artifacts/CART-1/work/run-report.json (132.4 KB) - slice it: `Grep -n` first, then Read with offset/limit
- qa-factory/artifacts/CART-1/test-plan.md (27.5 KB)
- qa-factory/artifacts/CART-1/work/bug-drafts/ (0 files)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- ledger.py <task root> - the checks ledger, by code, first
- traceability.py --task CART-1 --write | --render | --check - the R/TC roll-call; `--render` prints the appendix the report pastes, `--check` exits 1 on a requirement or case with no row
- report_facts.py --task CART-1 --write | --check - renders the code-owned blocks of test-report.md; `--check` must exit 0 before your handoff
- check_coverage.py --write - regenerates the coverage map
- check_delivery.py <task root> [--json] - the delivery verdict, by code
- delivery_summary.py --task-root <task root> [--open-items] - the factual delivery projection
- manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary - the manifest slice, never the file

## The rules code will apply to your handoff

test-report.md is read by code, not skimmed. Begin it from the template and run `report_facts.py --task <T> --write`: it renders the code-owned blocks (the verdict, Proven, Product bugs, Open questions, Skipped by the plan, Not proven, Decided at gate A, Size, Where to look; Decided at gate B after the gate) and you never type a number they carry. The `delivery_ready:` line is the block's (check_delivery.py feeds it): yes, after_checks or no. Eleven sections in this order: Proven, Product bugs, Left with you, Open questions, Not proven, Decided at gate A, Decided at gate B, Factory defects, Size, Where to look, Appendix - the verdict above the first. A green test the critic could not verify is in Left with you, not under Proven. Left with you has one item per case in `ledger.json` `left_items`, each with its R-n, case id, `To check:` and `Needed:` or `How:`; its last two blocks are code's. The Appendix is `traceability.py --render` pasted, a row for every R and every case. `report_facts.py --task <T> --check` must exit 0 before you finish. Your prose outside the blocks stays under 6,144 bytes. check_coverage.py re-runs at the exit gate: regenerate the coverage map first.

## The person's words that concern you

- 34 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S8-qa-doc-scribe-1-decisions.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
