# Brief - S6-qa-runner-2 - qa-runner at S6, CART-1

Scope: CART-1_TC_011, CART-1_TC_012. Environment: local; size XXL; source current-code.
Purpose: manual

## What earlier roles produced

- the digests of earlier roles: qa-factory/artifacts/CART-1/work/briefs/S6-qa-runner-2-digests.md

## Read these files

- work/automation-manifest.json: do not read whole - `manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary`
- qa-factory/artifacts/CART-1/state/story-case-links.json (13.9 KB)
- qa-factory/artifacts/CART-1/work/context-manifest.json (17.5 KB)
- qa-factory/artifacts/CART-1/work/s5-notes.md (932 B)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_011/cv_de13157c14b004fc1bbd.md (2.5 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_012/cv_8ad20339348408e4f727.md (2.2 KB)

## The stand

- API: http://localhost:3000
- Frontend: not configured (environment.frontend.url_key or environments[].frontend.url)
- Accounts: --as default; --as "admin", --as "user" (names only)
- Env keys: EMAIL_USER, EMAIL_PASS, USER_EMAIL, USER_PASSWORD, TEST_SECRET
- Case actors: CART-1_TC_011: PC-1 stand_account "user"
- Case actors: CART-1_TC_012: PC-1 stand_account "user"
- Page objects (repo map): none matched (qa-factory/artifacts/CART-1/work/briefs/repo-map-665b7f9b20.md)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- run_suite.py --mine <case id>[,<case id>] [--dispatch S6-qa-runner-2] [--node-id <file::func>] - the ordinary run of your open dispatch, the whole window in one pytest call; answer: a JSON summary {exit_code, execution_status, totals{passed,failures,errors,skipped}, failed[], error_head, summary_path} - the raw log stays in evidence/runs/<key>/ and is never read; status `reused`/`already_run` means nothing ran: read the summary
- run_suite.py --request <work/requests/x.json> - a run that is not the ordinary one (`--template request` prints the skeleton, runs nothing); same answer shape
- run_suite.py --schedule <schedule.json> - several typed requests at or above the parallel threshold
- run_suite.py --detail <test substring> --request <request.json> (or --task CART-1 --label <label>) - message and traceback of ONE failed test from the junitxml, no re-run
- run_suite.py --recover <KEY> --task CART-1 - inspect one interrupted durable job; never relaunches it
- env_probe.py --env <name> - the stand before a block; a failed line is the `env_blocked[]` row's witness
- stand_health.py --probe --env <name> - is the stand answering (exit 0 healthy); the door when a run says the stand's version cannot be observed: `environment` in your digest, not your test
- manual_evidence.py prepare|validate|write-block --task-root <task root> --input <file> - the manual-agent block
- finalize_task.py <task root> - reduces every run block into work/run-report.json (positional argument, no flag)
- manifest_view.py --task CART-1 --window "<ids>" | --case <case id> | --summary - the manifest slice, never the file
- manual_capture.py ui --task-root <task root> --case <C> --steps-file <S> [--as <account>] [--attempt aN] - the browser capture of one case
- manual_capture.py http --task-root <task root> --case <C> --method <M> --url <U> [--body-file <F>] [--as <account>] [--attempt aN] - one API call of one case
- manual_evidence.py build --task-root <task root> --case <C> --result pass|fail|inconclusive --actual "<what you saw>" --masked [--attempt aN] [--limitation "<words>"] - the record of one case from its captures

## The rules code will apply to your handoff

work/run-report.json is read field by field. `witness` at least 30 characters naming the run_suite summary that EXISTS on disk (evidence/<label>-<ts>.json) with the exit code and the totals line - a retelling is not a witness. `head` non-empty: evidence not bound to a sha goes stale the moment the branch moves. `env_preflight` pass|blocked, and blocked means `execution_status` is env_blocked - one field, one source. `execution_status` from passed|failed|env_blocked|not_executed|broken_run|timeout. `totals` an object. Every `results[]` row names ONE case, even when one test covers several, with a status from passed|failed|error|skipped|not_run, and a skip carries its reason; `manual_checks[].result` is pass|fail|inconclusive. Empty is not clean: a zero run with env_preflight pass and no env_blocked, manual_checks or manual_skipped is refused - return blocked with a reason instead. And every case S5 automated, plus every manual-agent row of the plan, has to appear in some lane of this report: results, manual_checks, skipped, impossible, env_blocked, manual_skipped or manual_human. Where a case went is your call; saying nothing about it is not.

## The person's words that concern you

- 32 recorded decision(s): qa-factory/artifacts/CART-1/work/briefs/S6-qa-runner-2-decisions.md

## Repository map of the window

- full map: qa-factory/artifacts/CART-1/work/briefs/repo-map-665b7f9b20.md

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
