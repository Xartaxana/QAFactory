# Artifact contract

Every file a role writes, who writes it, who reads it, its shape, and what code checks. The
validator (`scripts/validate_artifacts.py`, PostToolUse on Write/Edit) is the authority — this
document explains what it cannot. The closed vocabularies are in `vocabularies.md`, JSON
artifacts in `artifact-contract-json.md`, and the per-artifact contracts are split by who
writes them (`artifact-contract-plan.md`, `artifact-contract-results.md`).

<!-- roles: all -->
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

<!-- roles: qa-automator -->
### The S5 plan

`work/s5-plan.json` is written by `s5_plan.py --init` for qa-automator; fields: the brief.

<!-- roles: qa-case-designer, qa-case-critic -->
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

<!-- roles: qa-case-designer -->
### `then_oracles` form

Where each Then's expected value comes from, ONE line of JSON, one entry per numbered Then (a Then
that mixes sources is split):

```
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-13"}, {"then": 4, "source": "unknown", "ref": "Q7"}]
```

`source`: `requirement | ac | spec | precedent | person | unknown`; `code` is not a word. `requirement`
(`ac` is its older name)/`spec`: ref `R-n`, never an implementation-only R. `precedent`: only when a requirement names the
parity with OLDER behaviour, ref `base:<rev>:<path>:<line>` or `reference:<item>` (a reference snapshot item, under a `parity: yes` requirement basis); any other precedent is a question.
`person`: ref a question the person answered. `unknown`: ref a question that shows before/now, the
same Then in `question_thens`, and no literal in the Then. `basis` never names an implementation-only R.
A case asserts only its own requirements: a Then whose oracle is an R-n outside covers belongs to that R-n's case.
Its `then_oracles` ref is the field's own requirement R, never `unknown`, when the Then is a focus-and-partial-input Then.

No question yet: `unknown` with ref `raise` and ONE `raise_questions` line, e.g. `[{"then": 4,
"question": "<asked of the person>", "source_says": [{"quote": "…", "where": "…"}], "severity":
"major", "owner_role": "po_ba", "before": {"value": "400", "where": "…"}, "now": {"value": "403",
"where": "…"}}]` (`before.value`: `unknown` if the base is unreadable). Only as a pair: the S4
exit raises it, writes the new id and drops the line; a `raise` left at gate A is refused.

**`alternatives` (optional key).** A Then that must tell reading A from reading B names B, as ONE line of JSON:
`alternatives: [{"id": "ALT-1", "then": 2, "reading": "the stamp is taken at completion", "ref": "R-2"}]`;
`reading` ≤ 300 characters; `ref` the `R-n` or `Qn` that leaves both readings open. The Then must FAIL under B:
the S5 critic probes it. No key or `[]`: no claim.

<!-- roles: qa-requirements-tester -->
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

<!-- roles: qa-bug-reporter, qa-doc-scribe, qa-retro-analyst -->
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

<!-- roles: qa-retro-analyst -->
### Strategy documents: one fact, one owner

Ownership is by verb, and audit A21 enforces it: a trap about writing or running test code
(a flag that deselects tests, a config file that shadows another, a helper that looks
reusable and is not) belongs to `framework-rules.md`; a trap about planning (an area that is
always underestimated, a dependency that keeps making stories sequential) belongs to
`test-strategy.md`. Append under a section the owning document already has, never create a
section that exists in the other file, and never repeat a fact across both to be safe. A fold lands only where that document's `strategy_documents[]` record says
`editable: true`; otherwise it is an addendum line under `test-report.md`'s existing "Our
tests and the factory" section, naming the owning file.

<!-- roles: qa-bug-reporter, qa-doc-scribe, qa-retro-analyst -->
### Where the working files sit

`evidence/` holds raw run logs, junit XML, screenshots and `run_suite` summaries — never
retellings. `proposals/` holds one file per external write awaiting `external_writes.py`
after gate B. `bug-drafts/` holds `APP_BUG` drafts from S7; a draft becomes `bugs/BUG-n.md`
only on a gate-B decision.

<!-- roles: qa-doc-scribe, qa-retro-analyst -->
## Versioned lifecycle records

`artifact-registry.json` is the logical ID/path/producer/consumer/retention registry.
`record-schemas.json` supplies machine record shapes; semantic validators additionally
check joins, freshness, scope and revisions. `controller-api.md` names the actual CLI calls.
Machine writes use the canonical registry path; a differing legacy alias is a migration
conflict, not an alternate source to silently select. Event log `state/events.jsonl` is
append-only authority; pipeline, ledger, controller and dashboard are projections.
