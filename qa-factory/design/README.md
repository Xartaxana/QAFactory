# Documents — index

**Nothing here is loaded at runtime.** No role is handed a file from this directory, no script
reads one, no skill or agent phase points at one as a thing to read while working. These documents
are read by a person or by an agent that is CHANGING the factory.

That is the whole difference from `references/`, and it decides where a document lives:

| | `references/` | `design/` (here) |
|---|---|---|
| who reads it | a `qa-*` role at dispatch, the conductor, a script, a skill phase | whoever changes the factory |
| size | capped at 12 000 bytes per file — it is somebody's context | uncapped; split a document when a reader would want it split, not when a check says so |
| package fingerprint | inside it: `release_fingerprint.package_fingerprint()` (the one recipe; `references/release-fingerprint.json` alone is excluded) and audit A14 reads `release_fingerprint.compare()` (`factory_manifest.py --stamp` pins the same map) | outside it — editing a plan or a rule here cannot invalidate a dispatch |
| moving a file | rewrite every citation; roles fail closed on a missing path | rewrite the citations in prose |

**Why this directory exists.** These eighteen documents lived in `references/` and paid all three
prices for nothing. Three of them sat within 100 bytes of the reference cap
(`controller-api.md` 11 997, `codex-scout-reliability-plan.md` 11 994, `driver.md` 11 899), so the
next paragraph anyone wrote would have broken the build over a limit that protects a role's context
from a document no role receives. And because `references/**/*` is in the definition layer, editing a
design plan changed the package fingerprint that binds a dispatch — a false invalidation of
work already done.

## What is here

| File | What it is |
|---|---|
| `factory-rules.md` | **the rules every change to the factory must satisfy** (`FR-1` … `FR-59`) — the contract, the review procedure, how to add a rule, and the seven sections. One file, because a checklist is walked in one pass. Read this first. |
| `factory-rules-debt.md` | **where this factory breaks its own rules today** — one entry per live violation with the file, the line, what it costs and the fix; entries leave when the fix lands, into the "Fixed since this walk" list at its end. |
| `architecture.md` | **the load-bearing invariants of the factory** (`AR-n`, one section per owner goal: universality across projects, low friction with our code, one action one way everywhere, continuity between stages) — for each: the carriers that hold it, the detector, one recorded breakage and the check a change runs; closes with how a change walks the map. Read it before changing the package; a one-line index is generated from it into the development repository. |
| `controller-blocks.md` | **every one of the controller's 189 refusals and the route through it** — the person's recorded word, a command the message names, the caller fixing its own call, or "no word passes this, because …". `test_controller_blocks.py` holds it to the source in both directions. |
| `state-exits.md` | **every state the factory records and the command that reverses it** (FR-40) — the story's own state, the manifest's lists, the run's records and what a person recorded. `test_state_exits.py` enumerates the states from the source, so a new field cannot be added without saying how a story leaves it. |
| `driver.md` | the python driver that replaces the orchestrator model: its loop, its actions, the journal it leaves |
| `controller-paths.md` | how the controller resolves paths |
| `orchestrator-handoff.md` | what the orchestrator hands over between stages |
| `metric-signal-policy.md` | which dashboard signals are published and which are held back |
| `dashboard-design-contract.md`, `dashboard-metric-coverage.md`, `dashboard-cost-repair-plan.md`, `dashboard-release-validation.md`, `dashboard-signal-acceptance.md` | the Factory tab: its contract, what it covers, the cost repair, and the acceptance runs |
| `codex-compatibility-audit.md`, `codex-native-acceptance.md`, `codex-native-acceptance-results.md`, `codex-repair-acceptance.md` | Codex CLI compatibility: the audit, the procedure, and the evidence of the runs |
| `codex-scout-incident-2026-09-19.md`, `codex-scout-reliability-plan.md` | one scout incident and the plan it produced |

## Adding a document here

A document belongs here when nothing loads it: it is not named by `references/inject-map.json`, it
carries no role marker lines, and no script, skill or agent points a working reader at it. The
check `selftest.py --homes` holds that boundary in both directions — a document here that something
starts loading must move back to `references/`, and a reference nothing consumes belongs here.
