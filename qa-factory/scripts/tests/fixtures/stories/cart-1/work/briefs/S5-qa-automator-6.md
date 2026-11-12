# Brief - S5-qa-automator-6 - qa-automator at S5, CART-1

Scope: CART-1_TC_009 - window 3 of 4, surface other. Environment: local; size XXL; source current-code.
Branch check: recorded checkout `main`@5cd21eb10194 (recorded at S0 in state/test-repo-base.json); the implementation commit a25b0801669b (context-manifest, repository MyBooks) is not this HEAD: HEAD must carry its change - `git merge-base --is-ancestor a25b0801669b97d76f96f5a981fdc9ad4525d63d HEAD` exit 0 proves it at once; when it does not (a squash, a rebase, or a commit this repository does not know), prove it by content against that entry's own checkout; halt only when the change is absent. Compare commits, never branch names; never create or switch a branch.
Read first, before anything else: work/s5-notes.md.
This is a repair dispatch - cause test_defect: tests[] row for CART-1_TC_009 is NOT in the manifest (revision 23: 16 tests, none TC_009; only the unresolved contradicts_requirement row). Re-send it via manifest_put.py and verify by reading the....
Rework of S5-qa-automator-5.
Purpose: repair_verify
Plan slice qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-6-plan.md: 1 tests planned, 2 remarks for this window.
Case id form: CART-1_TC_001 (config.case_id_form; {ticket}_TC_{nnn})

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-6-digests.md

## Read these files

- qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-6-plan.md - the plan for your cases: requirements, rows, tests, and the remarks for them (the plan review's and the case critic's concerns)
- qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-6-code.md - the code you will touch: the tests you extend, the fixtures, a neighbouring test per file, the fields of a manifest row
- qa-factory/artifacts/CART-1/state/story-case-links.json (13.9 KB)
- qa-factory/artifacts/CART-1/test-plan.md (27.5 KB)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- run_suite.py --mine <case id>[,<case id>] [--purpose repair_verify] [--dispatch S5-qa-automator-6] [--node-id <file::func>] - the ordinary run of your open dispatch, the whole window in one pytest call; answer: a JSON summary {exit_code, execution_status, totals{passed,failures,errors,skipped}, failed[], error_head, summary_path} - the raw log stays in evidence/runs/<key>/ and is never read; status `reused`/`already_run` means nothing ran: read the summary
- run_suite.py --request <work/requests/x.json> - a run that is not the ordinary one (`--template request` prints the skeleton, runs nothing); same answer shape
- run_suite.py --detail <test substring> --request <request.json> (or --task CART-1 --label <label>) - message and traceback of ONE failed test from the junitxml, no re-run
- manifest_from_tests.py --task CART-1 --dispatch S5-qa-automator-6 --file <test file> [--file ...] [--dry-run] [--json] - reads `@pytest.mark.qa(case="<case id>", then=[1, 2], partition="tc003-zero-matches", obligations=["TS-3-O1"])` on your test functions (a parametrize id is the partition when none is given) and `@pytest.mark.qa_unresolved(case="<case id>", reason="impossible", detail="...")` at module or function level, builds the manifest fragment (instances, covers, partitions, obligation_ids, case_version_links, then_bindings) and calls manifest_put.py once; answer: what it wrote
- manifest_put.py --task CART-1 --fragment <file.json> - the hand-written fragment door; merges by case and instance, never Write the manifest
- s5_precheck.py --task-root <task root> --dispatch S5-qa-automator-6 [--json] - the check the stage runs on your handoff; answer: findings by family manifest|bindings|oracle|run_mapping|smell|environment, plus hints[] that never fail
- manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary - the manifest slice, never the file
- stand_health.py --probe --env <name> - is the stand answering (exit 0 healthy); the door when a run says the stand's version cannot be observed: `environment` in your digest, not your test

## The rules code will apply to your handoff

s5_precheck.py will check, so write to it: every Then of every case in scope is bound in `then_bindings[]` {case, then, instance_id, assertion_ref "file:line"}, and the names it demands (backticked, quoted, snake_case) appear in that assertion. A status code or literal a Then fixes is asserted as written and NEVER changed after a red run: that test is handed over RED, `unresolved[] reason: contradicts_requirement`. A value you invented may change after a red run only with an `expectation_changes[]` row through manifest_put.py: `then_refs` [{case, then}] it still proves, `what_changed`, `reason`; a test deleted or renamed after a red run owes the same row. A `blocked_by_env` row has `remedy` {kind, where, change, restart}, names only, never blaming a fixture the Then does not require. Smells refused: env credentials in an assert, `None == None`, `sleep`, a duplicated helper. One `tests[]` entry per INSTANCE (`func[param]`); `covers` lists cases. A `deferred_by_decision:*` row carries `disputes` nothing|derivation|case_expectation - a field, not wording; `derivation` = not derivable at all; `case_expectation` = you disagree with the approved case, no route out of S5 after gate A.

## The person's words that concern you

- 30 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-6-decisions.md

## Repository map of the window

- full map: qa-factory/artifacts/CART-1/work/briefs/repo-map-43880b230e.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
