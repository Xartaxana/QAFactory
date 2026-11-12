# Brief - S1-qa-scout-1 - qa-scout at S1, CART-1

Scope: the story scope. Environment: local; size ?; source ?.

## What earlier roles produced

- S0 done: preflight green, env=local

## Read these files

- qa-factory/artifacts/CART-1/pipeline.json (1.3 KB)
- qa-factory/artifacts/CART-1/work/ticket-snapshot.json (1.2 KB)
- work/ticket-references.json: https://example.invalid/2 — not_fetched: not read yet
- work/ticket-references.json: https://github.com/person-1/MyBooks — not_fetched: not read yet
- qa-factory/state/readiness.json (18.5 KB)
- qa-factory/strategy/project-profile.md (3.7 KB)

## Commands

Every command is `python "<path-2>/ai-packages/qa-factory/scripts/<script>"`, run from the project root; `<task root>` = qa-factory/artifacts/CART-1. `--help` of a script is allowed and answers what this card does not; the plugin's scripts are not read.
- ticket_adapter.py get|children|diff <KEY> [--json] [--ticket-file <path>] - the read cascade (diff takes --old <path> --new <path> in place of <KEY>)
- ticket_adapter.py peek <KEY> --output <task root>/work/source-inventory.json --summary - a mentioned ticket's first look, recorded in the inventory unassessed
- ticket_adapter.py assess --output <task root>/work/source-inventory.json --source-id <id> --relevance relevant|not_relevant|unknown --reason <reason> --assessment-ref <path> --summary - the verdict on a peeked source
- ticket_adapter.py collect <KEY> --output <task root>/work/source-inventory.json --relation task|subject|parent|normative|referenced --summary - the full read of a relevant source; --relation has no default
- ticket_adapter.py inspect --output <task root>/work/source-inventory.json --source-id <id> --attachment-id <id> --evidence-ref <path> --inspection-status read|partial|unavailable --summary - one attachment's receipt (external media: --media-url <url> [--local-ref <path>] in place of the attachment pair)
- diff_pass.py --diff <work/impl-diff*.txt> [--files-only | --file <path>] - the changed files and hunks in one call, never the diff whole
- vcs_evidence.py --url <MR URL> --output qa-factory/artifacts/CART-1/work/sources/<source id>/mr-<iid>.json - the merge request whole into the file, a summary on stdout; a file already at that path is the driver's receipt: Grep it, never collect again; its `status` says whether it was read; `mr-<iid>-git.md` next to it is the driver's partial route; record a new one with ticket_adapter.py inspect --output <inventory> --source-id <source id> --media-url <MR URL> --inspection-status read --local-ref sources/<source id>/mr-<iid>.json; never `glab mr view` into your context
- context_bundle.py --manifest <task root>/work/context-manifest.json --output <task root>/work/context-bundle.json --root <task root> - builds the bundle from your manifest; --root is where work/source-inventory.json is read and where a relative known_paths path or diff_path resolves (give absolute paths or paths relative to <task root>); a refusal names the manifest field
- context_bundle.py --validate <work/context-bundle.json> - the bundle's own validator, run before your digest
- env_probe.py --env <name> - the stand's liveness and login scheme, names only

## The rules code will apply to your handoff

work/context-manifest.json is read field by field: `ticket`, `acceptance_criteria` and `implementation` present; every `related[]` row is {key, kind, source}, kind one of implementation|blocker|bug|mention, `source` saying WHERE in this ticket the key was read; one `implementations[]` row per repository. `coverage_search[]` rows: repo, revision, changed_area, searched_paths, status complete|partial|unavailable, reason; nothing found is top-level `coverage_status: not_found`. `existing_test_candidates[]` rows: candidate_id, repo, revision, path, selector, parameter_ids, level, assertion_refs, candidate_requirement_refs, origin existing|added_in_change|unknown, result_candidate_refs. S1 closes on work/source-inventory.json: every required source retrieved and inspected, none `pending`, no material without receipts. A source you could not get: name it in your digest with its id and what is missing - recording a person's words is the orchestrator's door; you are resumed with their answer. Build with `context_bundle.py --manifest`, then `--validate`.

## The person's words that concern you

- standing: ticket is the person's text (qa-factory/tickets/CART-1.md), not read from Jira; CART-1 is a local placeholder key (supersedes ADD-TO-CART)
- standing: host_hooks unknown; vcs_api unknown; no lock file the factory reads

## Rule

Do not search: read what is named above with `offset`/`limit`; search the repository only when the map is empty, and never the plugin - the card above is what it would tell you, and `--help` is the door.
