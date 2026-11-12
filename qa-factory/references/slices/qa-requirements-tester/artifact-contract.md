<!-- generated from plugin:references/artifact-contract.md for qa-requirements-tester by scripts/contract_slices.py; edit the source, never this file -->
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

## `## Behaviour claims` of the register

A row that is `derived`, has no `ac_ref`, a `diff:` observable and a matrix row of only `silent` /
`n/a:*` is implementation-only: code computes it, and a register `created` >= 2026-10-02 is refused
until it has a claim row `| R | before | before_ref | now | now_ref | differs | question | origin |`
(eight columns, `origin` last: empty when S2 writes the row, `S3-grounding` when the grounding step
does; a 7-column table without it is still read). The register's own last column `delta` (after
`impact`) takes `new`, `changed` or `unchanged`; code reads five words from it: those three, `absent`
(no such column) and `invalid` (any other word, or an empty cell).
`before_ref`: `diff:-<path>:<line>`, `base:<rev>:<path>:<line>`, `screenshot:<ref>` or `absent` (a
new path); `before: unknown` when nothing can be read. `now_ref`: the diff line. `differs`: `yes |
no | unknown`. `question`: an `open_questions` id carrying `before {value, where}` and `now {value,
where}`; one question may list every claim of a new surface. Its readings are the fixed pair, both
`from: claim`. The answer, not the code, becomes the oracle.
