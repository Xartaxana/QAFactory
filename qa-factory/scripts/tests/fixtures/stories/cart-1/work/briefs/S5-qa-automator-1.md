# Brief - S5-qa-automator-1 - qa-automator at S5, CART-1

Scope: CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004, CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008, CART-1_TC_009, CART-1_TC_010. Environment: local; size XXL; source current-code.
Branch check: recorded checkout `main`@5cd21eb10194 (recorded at S0 in state/test-repo-base.json); the implementation commit a25b0801669b (context-manifest, repository MyBooks) is not this HEAD: HEAD must carry its change - `git merge-base --is-ancestor a25b0801669b97d76f96f5a981fdc9ad4525d63d HEAD` exit 0 proves it at once; when it does not (a squash, a rebase, or a commit this repository does not know), prove it by content against that entry's own checkout; halt only when the change is absent. Compare commits, never branch names; never create or switch a branch.
Purpose: s5_plan
Your work is the plan, not the code: fill work/s5-plan.json (one row of your digest per case). Cases with the same setup and action are one parameterized test (test-code-patterns.md «Executable shape»); a test kept apart says why in `apart_reason`. `s5_plan.py --check` is the exit check; its hints are advice, not repairs
Case id form: CART-1_TC_001 (config.case_id_form; {ticket}_TC_{nnn})

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-1-digests.md

## Read these files

- qa-factory/artifacts/CART-1/work/s5-plan.json (9419 B) - the plan you write: the skeleton is there; you fill tests, remainders, fixtures, refactor
- qa-factory/artifacts/CART-1/state/story-case-links.json (13.9 KB)
- qa-factory/artifacts/CART-1/test-plan.md (27.5 KB)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- run_suite.py --mine <case id>[,<case id>] [--purpose repair_verify] [--dispatch S5-qa-automator-1] [--node-id <file::func>] - the ordinary run of your open dispatch, the whole window in one pytest call; answer: a JSON summary {exit_code, execution_status, totals{passed,failures,errors,skipped}, failed[], error_head, summary_path} - the raw log stays in evidence/runs/<key>/ and is never read; status `reused`/`already_run` means nothing ran: read the summary
- run_suite.py --request <work/requests/x.json> - a run that is not the ordinary one (`--template request` prints the skeleton, runs nothing); same answer shape
- run_suite.py --detail <test substring> --request <request.json> (or --task CART-1 --label <label>) - message and traceback of ONE failed test from the junitxml, no re-run
- manifest_from_tests.py --task CART-1 --dispatch S5-qa-automator-1 --file <test file> [--file ...] [--dry-run] [--json] - reads `@pytest.mark.qa(case="<case id>", then=[1, 2], partition="tc003-zero-matches", obligations=["TS-3-O1"])` on your test functions (a parametrize id is the partition when none is given) and `@pytest.mark.qa_unresolved(case="<case id>", reason="impossible", detail="...")` at module or function level, builds the manifest fragment (instances, covers, partitions, obligation_ids, case_version_links, then_bindings) and calls manifest_put.py once; answer: what it wrote
- manifest_put.py --task CART-1 --fragment <file.json> - the hand-written fragment door; merges by case and instance, never Write the manifest
- s5_precheck.py --task-root <task root> --dispatch S5-qa-automator-1 [--json] - the check the stage runs on your handoff; answer: findings by family manifest|bindings|oracle|run_mapping|smell|environment, plus hints[] that never fail
- manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary - the manifest slice, never the file
- stand_health.py --probe --env <name> - is the stand answering (exit 0 healthy); the door when a run says the stand's version cannot be observed: `environment` in your digest, not your test
- s5_plan.py --task CART-1 --check - the exit check of the plan dispatch: names EVERY gap of work/s5-plan.json at once (`REJECT - N finding(s)` and exit 1, or `OK`); run it before your digest
- s5_plan.py --task CART-1 --window <N> [--out <file>] - the plan's slice for window N, as the controller will cut the windows (read-only)

## The rules code will apply to your handoff

s5_precheck.py will check, so write to it: every Then of every case in scope is bound in `then_bindings[]` {case, then, instance_id, assertion_ref "file:line"}, and the names it demands (backticked, quoted, snake_case) appear in that assertion. A status code or literal a Then fixes is asserted as written and NEVER changed after a red run: that test is handed over RED, `unresolved[] reason: contradicts_requirement`. A value you invented may change after a red run only with an `expectation_changes[]` row through manifest_put.py: `then_refs` [{case, then}] it still proves, `what_changed`, `reason`; a test deleted or renamed after a red run owes the same row. A `blocked_by_env` row has `remedy` {kind, where, change, restart}, names only, never blaming a fixture the Then does not require. Smells refused: env credentials in an assert, `None == None`, `sleep`, a duplicated helper. One `tests[]` entry per INSTANCE (`func[param]`); `covers` lists cases. A `deferred_by_decision:*` row carries `disputes` nothing|derivation|case_expectation - a field, not wording; `derivation` = not derivable at all; `case_expectation` = you disagree with the approved case, no route out of S5 after gate A.

## The person's words that concern you

- 12 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-1-decisions.md

## Repository map of the window

- full map: qa-factory/artifacts/CART-1/work/briefs/repo-map-8a03fe9fa4.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
