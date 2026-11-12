<!-- generated from plugin:references/artifact-contract.md for qa-doc-scribe by scripts/contract_slices.py; edit the source, never this file -->
# Artifact contract

Every file a role writes, who writes it, who reads it, its shape, and what code checks. The
validator (`scripts/validate_artifacts.py`, PostToolUse on Write/Edit) is the authority — this
document explains what it cannot. The closed vocabularies are in `vocabularies.md`, JSON
artifacts in `artifact-contract-json.md`, and the per-artifact contracts are split by who
writes them (`artifact-contract-plan.md`, `artifact-contract-results.md`).

## Where artifacts live

```
<project>/qa-factory/
  config.json  readiness.json  obligations.md  factory-backlog.md
  strategy/*.md            bugs/BUG-n.md
  records/journal.jsonl  records/estimation-ledger.jsonl  state/cost/
  artifacts/<TICKET>/
    understanding.md  test-plan.md
    test-report.md  retro.md
    pipeline.json
    state/story-case-links.json  state/case-versions/<CASE>/<VERSION>.md
    work/
      ticket-snapshot.json  context-manifest.json  context-bundle.json  impl-diff.txt
      requirements-register.md  requirements-readiness.json  test-plan.json  grounding.yaml  first-look.yaml  reference-snapshot.yaml
      test-cases/<area>/<id>.md
      automation-manifest.json  run-report.json  triage.json
      ledger.json  ledger.md  s5-plan.json  retro-numbers.json  retro-numbers.md  estimate-facts.json
      evidence/  proposals/  bug-drafts/  s5-notes/
```

Names are fixed. A role that invents a filename makes an artifact nobody reads. `records/` is
committed, `state/` is ignored; an older project keeps them in `state/`.

**Four documents are written for a person**, and they sit at the top of the story's folder:
`understanding.md` and `test-plan.md` at gate A, `test-report.md` and `retro.md` at the end.
Everything else is a working artifact — one role handing facts to the next — and lives under
`work/`.

`pipeline.json` stays at the top level: the story's state machine, at a fixed path.

**What is committed.** A closed story commits the four documents, the test code, and the
project-level files (`records/journal.jsonl`, `factory-backlog.md`, `obligations.md`,
`bugs/`). `work/` is not committed — it stays on disk for the audit, and `work/evidence/`
belongs in the project's `.gitignore`. The one exception is a **story interrupted mid-way**:
then `work/` is committed too, along with `pipeline.json`. Code reads an artifact through `contract.artifact()`, which looks
under `work/` first and falls back to the flat path.

## Project-level files

`config.json` (onboarding; `schema_version` must equal the version the plugin requires —
`hooklib.REQUIRED_SCHEMA_VERSION`; a mismatch is rejected with the list of missing keys),
`readiness.json` (written by `scripts/readiness.py`), `strategy/*.md` (onboarding, edited
by the retro analyst through knowledge folding), `bugs/BUG-n.md` (`qa-bug-reporter`, only
after gate B), `records/journal.jsonl` (append-only events: delegated, accepted, rejected,
gate, escalated, `deliver_with_risks`, `external_write`), `state/cost/` (`cost_capture.py`),
`records/estimation-ledger.jsonl` (append-only forecast vs actual records; each schema-v1 record
binds `task`, `task_revision`, `retro_sha256`, `facts`, `forecast`, `actual`, `drivers`,
`record_id`, and `supersedes`; exactly
one unsuperseded record matches the current completed-S9 retro),
`obligations.md` and `factory-backlog.md` (tails and factory findings, S8/S9).

### Where the working files sit

`evidence/` holds raw run logs, junit XML, screenshots and `run_suite` summaries — never
retellings. `proposals/` holds one file per external write awaiting `external_writes.py`
after gate B. `bug-drafts/` holds `APP_BUG` drafts from S7; a draft becomes `bugs/BUG-n.md`
only on a gate-B decision.

## Versioned lifecycle records

`artifact-registry.json` is the logical ID/path/producer/consumer/retention registry.
`record-schemas.json` supplies machine record shapes; semantic validators additionally
check joins, freshness, scope and revisions. `controller-api.md` names the actual CLI calls.
Machine writes use the canonical registry path; a differing legacy alias is a migration
conflict, not an alternate source to silently select. Event log `state/events.jsonl` is
append-only authority; pipeline, ledger, controller and dashboard are projections.
