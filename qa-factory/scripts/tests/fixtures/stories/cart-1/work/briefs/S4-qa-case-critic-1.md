# Brief - S4-qa-case-critic-1 - qa-case-critic at S4, CART-1

Scope: CART-1_TC_005, CART-1_TC_006, CART-1_TC_008, CART-1_TC_009. Environment: local; size XXL; source current-code.

## What earlier roles produced

- S0 done: preflight green, env=local
- S1 done: qa-scout S1 grounding · CART-1 · concerns · qa-factory/artifacts/CART-1/work/context-manifest.json
- S2 done: qa-requirements-tester S2 CART-1 · concerns · qa-factory/artifacts/CART-1/understanding.md
- S3 done: qa-test-strategist S3 CART-1 · concerns · qa-factory/artifacts/CART-1/test-plan.md
- S4-qa-case-designer-1 (accepted; story scope): no digest

## Read these files

- qa-factory/artifacts/CART-1/test-plan.md (5.8 KB)
- qa-factory/artifacts/CART-1/work/test-plan.json: do not read whole - `Grep -n` the TS ids of your cases in it, then Read the range; the S1 observables of those rows are in qa-factory/artifacts/CART-1/work/context-manifest.json, Read it with offset/limit (the conductor can cut either slice for you on request)
- qa-factory/artifacts/CART-1/work/requirements-register.md (7.2 KB)
- qa-factory/artifacts/CART-1/understanding.md (2.2 KB)
- qa-factory/artifacts/CART-1/work/context-manifest.json (17.5 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_005/cv_e4ffb26106421321c1a6.md (2.2 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_006/cv_1046d3cf7f7a7093f601.md (3.1 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_008/cv_ce42982f1616cbc645f9.md (2.6 KB)
- qa-factory/artifacts/CART-1/state/case-versions/CART-1_TC_009/cv_a9ed3ec0883c46ec8f19.md (2.7 KB)

## Commands

A role with no shell reads on Claude Code with Read, Grep and Glob and writes with Write and Edit. On Codex Desktop there is no Read, Grep, Glob, Write or Edit tool. Read or search a file with tools.exec_command running ONE plain command. One plain read command passes: `rg -n '<pattern>' <path>` or `Get-Content <path>`. A quoted pattern may hold | ; & ( ) inside ASCII quotes; $ < > a backtick, a newline and a typographic quote are refused even quoted; there is no pipe, no chaining and no redirect outside quotes, and never rg --pre. Any other shell command is refused. Edit a file you may write with tools.apply_patch: an Update File hunk with real context lines (the host refuses an empty hunk). Create a NEW file with tools.apply_patch and an *** Add File: <path> hunk (the guard reads it as Write and applies the same write rules). Connector and app tools (tools.mcp__codex_app__*, open_in_codex) are not file access. The scripts of the plugin are run for you by the orchestrator and the exit gate; the plugin's scripts are not read.
- your findings file is read by code at the exit gate (the roll-call); you run nothing

## The rules code will apply to your handoff

critic_rollcall.py computes your verdict from your own findings file at the exit gate, so the file has to carry the trail. A `## Roll-call` table with one row per case in scope, and give it a column headed `reviewed` holding yes or no - with that column the code reads the field and stops reading your prose. A `Verdict:` line from approve|approve_with_fixes|approve_with_concerns|partial|reject. If any row is not reviewed, an approving verdict is refused: the verdict that roll-call computes is `partial`, your digest must say '<n> of <m> reviewed' in those words, and an `Unreviewed for Gate A:` line must name every unreviewed case - the gate decides on what was reviewed, so it has to be told what was not. A concern of the last round that comes with an exact replacement is applied by code rather than by another design round: put those in a fenced JSON array under `## Fixes without a new round`, each object carrying case_id, locator, find, replace and reviewed_version. `approve_with_fixes` without that block is refused, and so is that block beside any other verdict.

## The person's words that concern you

- standing: ticket is the person's text (qa-factory/tickets/CART-1.md), not read from Jira; CART-1 is a local placeholder key (supersedes ADD-TO-CART)
- standing: host_hooks unknown; vcs_api unknown; no lock file the factory reads
- answer: sources: go on without Jira; stand local (carried over from ADD-TO-CART)

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you.
