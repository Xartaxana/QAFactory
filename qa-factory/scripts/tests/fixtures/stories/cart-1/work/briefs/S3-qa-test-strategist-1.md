# Brief - S3-qa-test-strategist-1 - qa-test-strategist at S3, CART-1

Scope: the story scope. Environment: local; size XXL; source current-code.
Blast radius index: none - the implementation source is current-code.

## What earlier roles produced

- S0 done: preflight green, env=local
- S1 done: qa-scout S1 grounding · CART-1 · concerns · qa-factory/artifacts/CART-1/work/context-manifest.json
- S2 done: qa-requirements-tester S2 CART-1 · concerns · qa-factory/artifacts/CART-1/understanding.md

## Read these files

- qa-factory/artifacts/CART-1/work/requirements-register.md (7.2 KB)
- qa-factory/artifacts/CART-1/work/context-bundle.lines.md (14.4 KB) - the bundle, one line per fact, source and candidate; the JSON (work/context-bundle.json) is the record for any field the view does not show
- qa-factory/strategy/test-strategy.md (3.1 KB)
- qa-factory/artifacts/CART-1/work/requirements-readiness.json (5.0 KB)
- qa-factory/artifacts/CART-1/understanding.md (2.2 KB)

## Commands

A role with no shell reads on Claude Code with Read, Grep and Glob and writes with Write and Edit. On Codex Desktop there is no Read, Grep, Glob, Write or Edit tool. Read or search a file with tools.exec_command running ONE plain command. One plain read command passes: `rg -n '<pattern>' <path>` or `Get-Content <path>`. A quoted pattern may hold | ; & ( ) inside ASCII quotes; $ < > a backtick, a newline and a typographic quote are refused even quoted; there is no pipe, no chaining and no redirect outside quotes, and never rg --pre. Any other shell command is refused. Edit a file you may write with tools.apply_patch: an Update File hunk with real context lines (the host refuses an empty hunk). Create a NEW file with tools.apply_patch and an *** Add File: <path> hunk (the guard reads it as Write and applies the same write rules). Connector and app tools (tools.mcp__codex_app__*, open_in_codex) are not file access. The scripts of the plugin are run for you by the orchestrator and the exit gate; the plugin's scripts are not read.
- the plan is checked by code when you save it and again at the exit gate; only the invalid rows come back to you
- work/test-plan.json is written whole exactly once, when it first appears: after that a Write over it is refused, because 59 whole rewrites of it cost 525,812 tokens of arguments on this story and two booleans cost $16.53. Change a row, or append one you wrote, with Edit - one row's own lines at a time. test-plan.md is your words for the human: change its lines with Edit

## The rules code will apply to your handoff

planning_contract.py and observation_contract.py will check, so write to them in fields, not in prose - both refused this story twice for exactly these two rules. `verification_depth: low` is accepted ONLY together with `impact: low`, `likelihood: low`, `confidence: high` and `bounded_reversible: true`; repeating the detector's sentence in a note is not evidence, and `impact: unknown` can never be low while `impact: severe` demands `critical`. Every row needs `risk_source_refs` and `required_scenarios` non-empty. A no-write obligation (kind `state_unchanged` or `no_write_attempt`) needs three things beside the claim: `sequence` of exactly four items with phases before_read, action, completion, after_read, each `ref` naming a check or step that exists; `positive_control_ref` naming a MUTATING check that is not one of those four; and `reachability_assertion_ref`. Without the last two, 'nothing was written' only proves nothing was reached. An oracle you cannot settle is `oracle_unknown: true` with `source_conflict: true` - an unresolved oracle does not authorize execution, and that is the row's correct state, not something to waive.

## The person's words that concern you

- standing: ticket is the person's text (qa-factory/tickets/CART-1.md), not read from Jira; CART-1 is a local placeholder key (supersedes ADD-TO-CART)
- standing: host_hooks unknown; vcs_api unknown; no lock file the factory reads
- answer: sources: go on without Jira; stand local (carried over from ADD-TO-CART)

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you.
