# Brief - S5-qa-code-critic-6 - qa-code-critic at S5, CART-1

Scope: CART-1_TC_009 - window 3 of 4, surface other. Environment: local; size XXL; source current-code.
Read first, before anything else: work/s5-notes.md.
Plan slice qa-factory/artifacts/CART-1/work/briefs/S5-qa-code-critic-6-plan.md: 1 tests planned, 2 remarks for this window.
whether tests were changed after a red run could not be measured: a red run has no later pass for cart-quote-order.spec.@api @regression CART-1_TC_009 quote and order from cart, and the test file that would say whether the test still exists cannot be read (not a Python file, a syntax error, or no file named by the manifest)
Live checks the predicate requires - 1 instance (new or changed tests): tests/api/cart/cart-quote-order.spec.ts::@api @regression CART-1_TC_009 quote and order from cart. Each needs a receipt: run its check and record it, or leave it in work/probe-debt.json for the conductor.

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S5-qa-code-critic-6-digests.md

## Read these files

- qa-factory/artifacts/CART-1/work/briefs/S5-qa-code-critic-6-plan.md - the plan for your cases: requirements, rows, tests, and the remarks for them (the plan review's and the case critic's concerns)
- qa-factory/artifacts/CART-1/state/story-case-links.json (13.9 KB)
- qa-factory/artifacts/CART-1/test-plan.md (27.5 KB)
- qa-factory/artifacts/CART-1/work/context-bundle.lines.md (14.4 KB) - the bundle, one line per fact, source and candidate; the JSON (work/context-bundle.json) is the record for any field the view does not show
- qa-factory/artifacts/CART-1/work/s5-notes.md (932 B)
- work/automation-manifest.json: do not read whole - `manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary`
- qa-factory/artifacts/CART-1/work/test-code/ (3 files)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_009/cv_2b3ebd621560f9547704.md (3.6 KB)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- probe_by_code.py --task CART-1 --dispatch S5-qa-code-critic-6 --test "<file>::<test name>" --instance <IID> [--mutation invert|expected] [--oracle <file>::<function>] [--at <line>] [--release-copy <file>] [--json] - the default probe for every new/changed test; intended_failure writes the live receipt. <test name> is [Class::]<func>[<param>] for pytest, the method or title in any other language with an `assertion_probes` entry (invert only; --at <line> picks the assertion, or the declaration when a name repeats). It mutates the first assert of that test, runs that one test through run_suite.py --request, restores the file byte-for-byte, writes work/probes/<IID>.json {verdict intended_failure|no_failure|wrong_location|incomplete, expected/actual location and reason, failure_kind, mutation_kind, evidence_ref}; you never mutate a test yourself; `incomplete`, and a refusal that names a factory data gap or a killed probe's unresolved copy, is `tooling` (say so in your digest), never a verdict on the test; `--release-copy <file>` alone drops that copy, only after the test's author has settled the file; a repeat on the same bytes is answered already_probed and nothing runs
- red_sandbox.py --probe --request <mutations.json> --task-root <task root> --repo <root> [--dispatch S5-qa-code-critic-6] - only when you doubt the check looks at the product (a stub, mock or fixture answers it), in place of probe_by_code for that instance; say why in the findings; two mutations of one file go in one request only as ONE combined replacement (B-314); incomplete|not_executed is `tooling`, never a verdict on the test
- run_suite.py --detail <test substring> --request <request.json> (or --task CART-1 --label <label>) - message and traceback of ONE failed test from the junitxml, no re-run
- manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary - the manifest slice, never the file
- stand_health.py --probe --env <name> - is the stand answering (exit 0 healthy); the door when a run says the stand's version cannot be observed: `environment` in your digest, not your test
- s5_precheck.py --task-root <task root> --dispatch S5-qa-code-critic-6 --json - read-only: what code already checked; do not re-report it

## The rules code will apply to your handoff

Static review first over the files named above, whole window; then one probe per new or changed instance through probe_by_code.py (the check is live), or red_sandbox.py --probe (catches a broken product) in its place, only when you doubt the check looks at the product, with the reason in your findings; a repeat on the same bytes is answered `already_probed` and nothing runs; reuse the author's green receipt, never run a duplicate green. A `mechanical` finding is worded, not fixed. Findings go to work/test-code/critic-findings*.md with `cause:` on each. A test that changed after its red run is listed in your brief (full list: `s5_precheck.py --json`, `expectation_changes`): give each row ONE verdict through manifest_put.py, a patch with its function, `red_attempt` and `green_attempt` plus `critic_verdict` legitimate_correction|fitted_to_code|could_not_judge and `critic_note`. `fitted_to_code` is also a `test_defect` finding whose expected is "the Then's value restored, the test handed RED with contradicts_requirement". A change you cannot judge is `could_not_judge` with a note, never silence.

## The person's words that concern you

- 30 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S5-qa-code-critic-6-decisions.md

## Repository map of the window

- full map: qa-factory/artifacts/CART-1/work/briefs/repo-map-43880b230e.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
