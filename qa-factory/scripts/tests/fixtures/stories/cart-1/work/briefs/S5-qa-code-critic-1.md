# Brief - S5-qa-code-critic-1 - qa-code-critic at S5, CART-1

Scope: CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004, CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008, CART-1_TC_009, CART-1_TC_010. Environment: local; size XXL; source current-code.
Purpose: s5_plan
Your work is the plan review, not the code: judge work/s5-plan.json against the cases and fill your review form (verdict, remarks PR-n); `s5_plan.py --check` is what code already found, do not re-report it
The live checks the predicate requires could not be listed: work/automation-manifest.json is not there.

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S5-qa-code-critic-1-digests.md

## Read these files

- qa-factory/artifacts/CART-1/work/s5-plan.json (17269 B) - the plan you review
- qa-factory/artifacts/CART-1/work/handoffs/S5-qa-code-critic-1.yaml - your review form (`start` writes it right after this brief; `finish` stamps the plan you read)
- <path-2>/ai-packages/qa-factory/references/code-review-rubric.md (9.0 KB) - read its section «On the plan» (`Grep -n` it)
- qa-factory/artifacts/CART-1/state/story-case-links.json (13.9 KB)
- qa-factory/artifacts/CART-1/test-plan.md (27.5 KB)
- qa-factory/artifacts/CART-1/work/context-bundle.lines.md (14.4 KB) - the bundle, one line per fact, source and candidate; the JSON (work/context-bundle.json) is the record for any field the view does not show
- qa-factory/artifacts/CART-1/work/s5-notes.md: not written yet — that is the path it will have, and nothing else is it
- work/automation-manifest.json: do not read whole - `manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary`

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- probe_by_code.py --task CART-1 --dispatch S5-qa-code-critic-1 --test "<file>::<test name>" --instance <IID> [--mutation invert|expected] [--oracle <file>::<function>] [--at <line>] [--release-copy <file>] [--json] - the default probe for every new/changed test; intended_failure writes the live receipt. <test name> is [Class::]<func>[<param>] for pytest, the method or title in any other language with an `assertion_probes` entry (invert only; --at <line> picks the assertion, or the declaration when a name repeats). It mutates the first assert of that test, runs that one test through run_suite.py --request, restores the file byte-for-byte, writes work/probes/<IID>.json {verdict intended_failure|no_failure|wrong_location|incomplete, expected/actual location and reason, failure_kind, mutation_kind, evidence_ref}; you never mutate a test yourself; `incomplete`, and a refusal that names a factory data gap or a killed probe's unresolved copy, is `tooling` (say so in your digest), never a verdict on the test; `--release-copy <file>` alone drops that copy, only after the test's author has settled the file; a repeat on the same bytes is answered already_probed and nothing runs
- red_sandbox.py --probe --request <mutations.json> --task-root <task root> --repo <root> [--dispatch S5-qa-code-critic-1] - only when you doubt the check looks at the product (a stub, mock or fixture answers it), in place of probe_by_code for that instance; say why in the findings; two mutations of one file go in one request only as ONE combined replacement (B-314); incomplete|not_executed is `tooling`, never a verdict on the test
- run_suite.py --detail <test substring> --request <request.json> (or --task CART-1 --label <label>) - message and traceback of ONE failed test from the junitxml, no re-run
- manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary - the manifest slice, never the file
- stand_health.py --probe --env <name> - is the stand answering (exit 0 healthy); the door when a run says the stand's version cannot be observed: `environment` in your digest, not your test
- s5_precheck.py --task-root <task root> --dispatch S5-qa-code-critic-1 --json - read-only: what code already checked; do not re-report it
- s5_plan.py --task CART-1 --check - what code already found in the plan; do not re-report it
- s5_plan.py --task CART-1 --window <N> [--out <file>] - the plan's slice for window N, as the controller will cut the windows (read-only)

## The rules code will apply to your handoff

Static review first over the files named above, whole window; then one probe per new or changed instance through probe_by_code.py (the check is live), or red_sandbox.py --probe (catches a broken product) in its place, only when you doubt the check looks at the product, with the reason in your findings; a repeat on the same bytes is answered `already_probed` and nothing runs; reuse the author's green receipt, never run a duplicate green. A `mechanical` finding is worded, not fixed. Findings go to work/test-code/critic-findings*.md with `cause:` on each. A test that changed after its red run is listed in your brief (full list: `s5_precheck.py --json`, `expectation_changes`): give each row ONE verdict through manifest_put.py, a patch with its function, `red_attempt` and `green_attempt` plus `critic_verdict` legitimate_correction|fitted_to_code|could_not_judge and `critic_note`. `fitted_to_code` is also a `test_defect` finding whose expected is "the Then's value restored, the test handed RED with contradicts_requirement". A change you cannot judge is `could_not_judge` with a note, never silence.

## The person's words that concern you

- 12 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S5-qa-code-critic-1-decisions.md

## Repository map of the window

- full map: qa-factory/artifacts/CART-1/work/briefs/repo-map-8a03fe9fa4.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
