# Brief - S7-qa-failure-analyst-1 - qa-failure-analyst at S7, CART-1

Scope: CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004, CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008, CART-1_TC_009, CART-1_TC_010, CART-1_TC_011, CART-1_TC_012. Environment: local; size XXL; source current-code.

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S7-qa-failure-analyst-1-digests.md

## Read these files

- qa-factory/artifacts/CART-1/work/run-report.json (132.4 KB) - slice it: `Grep -n` first, then Read with offset/limit
- work/automation-manifest.json: do not read whole - `manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary`
- qa-factory/artifacts/CART-1/work/evidence/ (211 files)
- qa-factory/artifacts/CART-1/test-plan.md (27.5 KB)
- qa-factory/strategy/faq.md (212 B)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_001/cv_4752342fab279cf316cc.md (2.3 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_002/cv_aaed235e685cdb6d3318.md (2.3 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_003/cv_0f8aaebc21c72b94456c.md (1.5 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_004/cv_59c8d14f1852702b39cb.md (2.3 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_005/cv_3767896d512c623e0b59.md (2.9 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_006/cv_3736b2c697846070acdd.md (3.3 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_007/cv_2d9d27c7521bc3c4edcf.md (1.9 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_008/cv_ce42982f1616cbc645f9.md (2.6 KB)
- ... and 4 more case files of the scope, same folder
- tests/api/cart/add-rejections.spec.ts (1.1 KB) - the test file of the window
- tests/api/cart/add-stock-limit.spec.ts (1.2 KB) - the test file of the window
- tests/api/cart/add-accumulate.spec.ts (639 B) - the test file of the window
- tests/api/cart/add-boundaries.spec.ts (2.4 KB) - the test file of the window
- tests/api/cart/cart-isolation.spec.ts (1.1 KB) - the test file of the window
- tests/api/cart/cart-merge.spec.ts (1.9 KB) - the test file of the window

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- artifact_producer.py prepare --kind triage --task-root <task root> - the triage skeleton to fill
- artifact_producer.py validate-batch --task-root <task root> --input <batch.json> - checks the handoff as one unit; batch.json is {"artifacts": [{"kind": "triage", "path": "work/triage.json", "data": <the artifact object>}]}
- artifact_producer.py publish --kind triage --task-root <task root> --path work/triage.json --input <file> [--expected-hash <sha256>] - the publication (--expected-hash only over a file that exists)
- run_suite.py --request <work/requests/x.json> - a run that is not the ordinary one (`--template request` prints the skeleton, runs nothing); same answer shape; FLAKY (S7 only): each isolated rerun of that ONE test is its own `purpose: flaky_diagnostic` request, up to 3 per test and code bytes; the next one is refused
- run_suite.py --detail <test substring> --request <request.json> (or --task CART-1 --label <label>) - message and traceback of ONE failed test from the junitxml, no re-run
- manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary - the manifest slice, never the file
- stand_health.py --probe --env <name> - is the stand answering (exit 0 healthy); the door when a run says the stand's version cannot be observed: `environment` in your digest, not your test
- red_sandbox.py --diagnostic --request <diag.json> --task-root <task root> --repo <root> [--dispatch S7-qa-failure-analyst-1] - ONE run of a test without its red assert (rule 2c b), in a copy; writes evidence/diagnostic-<label>.json, never your file; a second run of the same test and bytes is refused
- bug_snapshot.py --root <project> --input <snapshot.json> - persists bug evidence you already hold (references/metrics-contract.md); fetches nothing

## The rules code will apply to your handoff

work/triage.json is read row by row: every row's `verdict` comes from APP_BUG|TEST_BUG|TEST_BUG:collection|ENV_ISSUE|FLAKY|APP_CHANGED|CASE_DEFECT|ASSERT_STRICTER|NOT_EXECUTED (NOT_EXECUTED is the one code writes for a manual check, not you: the check did not answer; the person finishes it), and every row's `evidence` is non-empty whatever the verdict - a verdict without proof is not a verdict. Every row also names its `instance_id` and `attempt_id`. ASSERT_STRICTER costs a `control` block: `result` effect_without_change, the `action` repeated, what it was done `without`, what was `observed`, and an `evidence` file in the task's `evidence/` folder that exists; `impossible` needs `why` and never gives ASSERT_STRICTER. FLAKY costs three more fields, and all three are checked: `reruns` >= 3 isolated executions of that ONE test, counted across every role through the manifest's runs[]; `mechanism` from isolation|race|timing|shared_state|teardown|environment|unknown, because an unnamed mechanism cannot be repaired; and `fix_result` fixed or not_fixed. An unfixed flake is not verified, and quarantining it is the person's call at gate B, never yours.

## The person's words that concern you

- 34 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S7-qa-failure-analyst-1-decisions.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
