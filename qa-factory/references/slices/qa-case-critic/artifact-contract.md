<!-- generated from plugin:references/artifact-contract.md for qa-case-critic by scripts/contract_slices.py; edit the source, never this file -->
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

## `test-cases/<area>/<case id>.md`

**Where** `config.cases_root` when the project keeps a case store, else the story's
`work/test-cases/`. **Case id** the file name and the `id:` are one id, in the project's form
(`config.case_id_form`, on the brief's `Case id form:` line when it has one; `TC-001` when none).
**Writer** `qa-case-designer`, S4; moved to `Automated` by
`qa-code-critic` on approval. **Readers** case critic, automator, runner,
`check_traceability.py`. **Shape** frontmatter `id, title, area, priority, status, channel,
reuse_decision, updated, task, covers, defect_class, basis`; two body lines verbatim
(`Requirements: R-1, R-2` and `Plan row: TS-n` — the chain `check_traceability.py` and
`ledger.py` read); and `## Obligation coverage`, mapping each obligation part to its oracle,
boundary, Then/evidence and residual gap, so one `covers: R-n` is not proof of every part.
**Validator**
`status`/`priority`/`channel`/`reuse_decision`/`defect_class` each held to their closed list
on write with the allowed values in the message; `status: Automated` only with `red_probe` and
`automated_by`; `covers` ids exist in the register.

**The body shape S5 counts.** `## Then` is a heading of its own, and each expectation is a
numbered item under it (`1.`, `2.` …); a data partition is named `P-<name>` wherever it is
used. `s5_precheck.py` binds every Then clause to a test and an
assertion line and reports a case `green` only when each of its Then clauses and partitions is
covered or recorded `unresolved` with a reason. A Then written as prose yields no clauses and passes the
binding check vacuously.

**A Then another check stops** is a `then_bindings` row of the automation contract (`references/artifact-contract-automation.md`).

**`preconditions` (optional key).** What the case needs from the STAND before its first
step, as ONE line of JSON (the front-matter parser is flat):

```
preconditions: [{"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are enabled", "partitions": ["P-selfref"], "check": {"http": {"path": "/v1/config", "status": 200, "json_path": "features.subWorkflow", "equals": true}}}]
```

`kind`: `feature_flag | data | account | env | service`. `what`: the plain words the person
reads at the gate. `partitions` (optional): the `P-` ids it gates. `check`: exactly one of
`{"env": "VAR_NAME"}` (a name, never a value — looked up in the env files the runner really
loads), `{"http": {path, status?, json_path?, equals?}}` (an anonymous GET of a path on the
environment's API base URL from config, never a full URL),
`{"case_seeds": "<what the case itself creates>"}` (never asked), `{"stand_account": "<credentials_by_role key>"}` (an account
the stand holds, e.g. `default_user`: met only when that role's note names keys that
are set, else a question; `default` is the stand's default account), `{"stand_frontend": "<why the case needs the stand's UI>"}`
(the address of the UI, looked up in the project's record: met when one is recorded, else a question; never `kind: account`),
`{"integration": "<name of one integration from your brief>"}` (a service the case goes through, by the name the brief lists, never a
variable name: met when the project's keys for it, any set of its alternatives, are set where the runner reads them, else a card
naming the case and its Then)
or `{"none": "<why no machine can check it>"}` (only what a
person alone can say; every `none` of the story reaches the person as ONE card). The
validator holds the shape on write; `gate_preflight.py` checks the stand before Gate A and
asks one grouped question per case.

**`question_thens` (optional key).** What a Then says under each answer of an open register
question, as ONE line of JSON:

```
question_thens: [{"question": "Q1", "then": 1, "readings": {"a": "HTTP 200, no execution", "b": "HTTP 400"}, "not_needed": ""}]
```

`question` is the register's own id, matched exactly (`Q1` is not `Q10`).
`then` is the number of an item under `## Then`; it keeps its number in every answer. `readings`
holds a text for EVERY reading letter (`a` is the first): an empty text means "this answer asserts
nothing here". A before/now question (`claim` on its readings, or `raise`) is keyed `now` / `before`, never by letter. `not_needed` is optional. Write the body's item in the conditional form. Two
questions may not give the same Then a reading (a DEPENDENT pair). The gate rehearsal refuses a
missing letter, a `then` past the list and an answered question; a case
with no `question_thens` is never refused.

**`branches` (optional key).** Each branch (`BN-n`, `BN-T<n>`) of the plan row that this case proves, as ONE line of JSON:
`branches: [{"id": "BN-1", "then": 2, "partition": "P-occupied"}]`. `then` is the number of an item under `## Then`; `partition`
(optional) is a `P-<name>` the body uses, compared by `contract.partition_key`. A branch no case carries is homed by the case
critic in `## Branch homes` of its findings (`| BN | home | reason |`, `home` a case id or `excluded` with a reason).

`then_oracles`: whether R's text supports the Then's value is the case critic's call.
