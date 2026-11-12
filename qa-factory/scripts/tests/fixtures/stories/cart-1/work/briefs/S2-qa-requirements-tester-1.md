# Brief - S2-qa-requirements-tester-1 - qa-requirements-tester at S2, CART-1

Scope: the story scope. Environment: local; size ?; source current-code.

## What earlier roles produced

- S0 done: preflight green, env=local
- S1 done: qa-scout S1 grounding · CART-1 · concerns · qa-factory/artifacts/CART-1/work/context-manifest.json

## Read these files

- qa-factory/artifacts/CART-1/work/context-bundle.lines.md (14.4 KB) - the bundle, one line per fact, source and candidate; the JSON (work/context-bundle.json) is the record for any field the view does not show
- qa-factory/artifacts/CART-1/work/context-manifest.json (17.5 KB)
- qa-factory/artifacts/CART-1/work/impl-diff*.txt: not written yet — that is the path it will have, and nothing else is it
- <path-2>/ai-packages/qa-factory/references/templates/requirements-register.md (7.3 KB)
- <path-2>/ai-packages/qa-factory/references/templates/understanding.md (2.0 KB)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- diff_pass.py --diff <work/impl-diff*.txt> --files-only, then --file <path> --max-lines 100000 for EVERY file it lists, in every impl-diff - every changed line of every hunk, numbered in the new file (a removed line is numbered at its place in the new file, so a `diff:-<path>:<line>` reference carries that number); never Read a diff whole
- artifact_producer.py prepare --kind readiness --task-root <task root> - the readiness skeleton to fill
- artifact_producer.py validate-batch --task-root <task root> --input <batch.json> - checks the handoff as one unit; batch.json is {"artifacts": [{"kind": "readiness", "path": "work/requirements-readiness.json", "data": <the artifact object>}]}
- artifact_producer.py publish --kind readiness --task-root <task root> --path work/requirements-readiness.json --input <file> [--expected-hash <sha256>] - the atomic publication (--expected-hash only over a file that exists)
- sizing.py --task CART-1 - the size, computed by code from the register; never chosen by hand

## The rules code will apply to your handoff

Three artifacts, three checks. work/requirements-register.md: `ids` non-empty and all R-n, `by_source` within ac|story|feature|discussion|assumption|derived, `confidence` high|low - a register of AC alone while a parent feature exists must be `low`; every row's observable prefixed diff:|current-code:|expected-contract: or the word `none`; every `derived` row naming what it was derived from; `impact` from config.json impact_scale. Every production module work/impl-diff*.txt CREATES has to be cited by a `derived` row - the exit gate compares them, so read every hunk, limits, rejected inputs and guards included; a `derived` row only the diff speaks to also gets its `## Behaviour claims` row. work/requirements-readiness.json: `verdict` ready|blocked agreeing with the facts, `goal_summary` >= 30 characters in your own words, `aspects` non-empty with status ready|blocked|n/a and a reason on every n/a, `open_questions[]` each with question, severity blocker|major|minor and owner_role po_ba|dev_arch|qa. understanding.md: at most 40 lines, its five sections in order, and every register R named in a 'What we verify' or 'What we do not verify' line.

## The person's words that concern you

- standing: ticket is the person's text (qa-factory/tickets/CART-1.md), not read from Jira; CART-1 is a local placeholder key (supersedes ADD-TO-CART)
- standing: host_hooks unknown; vcs_api unknown; no lock file the factory reads
- answer: sources: go on without Jira; stand local (carried over from ADD-TO-CART)

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
