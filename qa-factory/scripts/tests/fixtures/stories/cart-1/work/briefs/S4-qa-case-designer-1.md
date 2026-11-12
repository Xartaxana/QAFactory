# Brief - S4-qa-case-designer-1 - qa-case-designer at S4, CART-1

Scope: the story scope. Environment: local; size XXL; source current-code.
Case id form: CART-1_TC_001 (config.case_id_form; {ticket}_TC_{nnn})

## What earlier roles produced

- S0 done: preflight green, env=local
- S1 done: qa-scout S1 grounding · CART-1 · concerns · qa-factory/artifacts/CART-1/work/context-manifest.json
- S2 done: qa-requirements-tester S2 CART-1 · concerns · qa-factory/artifacts/CART-1/understanding.md
- S3 done: qa-test-strategist S3 CART-1 · concerns · qa-factory/artifacts/CART-1/test-plan.md

## Read these files

- qa-factory/artifacts/CART-1/test-plan.md (5.8 KB)
- qa-factory/artifacts/CART-1/work/test-plan.json: do not read whole - `Grep -n` the TS ids of your cases in it, then Read the range; the S1 observables of those rows are in qa-factory/artifacts/CART-1/work/context-manifest.json, Read it with offset/limit (the conductor can cut either slice for you on request)
- qa-factory/artifacts/CART-1/work/requirements-register.md (7.2 KB)
- qa-factory/artifacts/CART-1/work/context-manifest.json (17.5 KB)
- qa-factory/strategy/test-strategy.md (3.1 KB)

## Commands

A role with no shell reads on Claude Code with Read, Grep and Glob and writes with Write and Edit. On Codex Desktop there is no Read, Grep, Glob, Write or Edit tool. Read or search a file with tools.exec_command running ONE plain command. One plain read command passes: `rg -n '<pattern>' <path>` or `Get-Content <path>`. A quoted pattern may hold | ; & ( ) inside ASCII quotes; $ < > a backtick, a newline and a typographic quote are refused even quoted; there is no pipe, no chaining and no redirect outside quotes, and never rg --pre. Any other shell command is refused. Edit a file you may write with tools.apply_patch: an Update File hunk with real context lines (the host refuses an empty hunk). Create a NEW file with tools.apply_patch and an *** Add File: <path> hunk (the guard reads it as Write and applies the same write rules). Connector and app tools (tools.mcp__codex_app__*, open_in_codex) are not file access. The scripts of the plugin are run for you by the orchestrator and the exit gate; the plugin's scripts are not read.
- the pins of your cases and the roll-call are made by the orchestrator and the exit gate after you hand over; you write the case files

## The rules code will apply to your handoff

A case file's `id` IS its file name, both in the form named on this brief's `Case id form:` line: `<case id>.md` declares `id: <case id>`. That is the factory's contract over any project note (a note naming another form is not read by code), and the exit gate refuses the handoff otherwise - a renamed id breaks every later join and the run stops on a question to a person. Frontmatter every case owes: id, title, area, priority P0|P1|P2|P3, status (yours are Draft|Review|Approved - only the code critic moves a case to Automated, and only after a probe), channel auto|manual-agent|manual-human, reuse_decision new|updated|extend:<case id>|dedupe:<case id>, updated, task, covers: [R-n] that exist in that task's register (an R the register does not carry reads as invented), defect_class from the project's closed list (or smoke, or regression:BUG-NNN), and basis per the oracle grammar requirement:R-n | invariant:<id> | consistency:<where> | history:<baseline> | impact:<harm> | external:<norm>. defect_class and basis are inherited from your plan row, never reassigned.

## The person's words that concern you

- standing: ticket is the person's text (qa-factory/tickets/CART-1.md), not read from Jira; CART-1 is a local placeholder key (supersedes ADD-TO-CART)
- standing: host_hooks unknown; vcs_api unknown; no lock file the factory reads
- answer: sources: go on without Jira; stand local (carried over from ADD-TO-CART)

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you.
