# Closed vocabularies

Every value below is verbatim, as `scripts/contract.py` holds it. Anything outside these
lists is an invented status the validator rejects on write.

<!-- roles: qa-case-designer, qa-case-critic, qa-doc-scribe -->
## Disposition

**Disposition** (plan row) — `automate` · `manual-agent` · `manual-human` · `skip` ·
`unverifiable`. Each carries a non-empty `reason`. Changed by the human at gate A →
the row also carries `overridden: true` and `overridden_by: human`.

<!-- roles: qa-scout, qa-requirements-tester, qa-case-designer, qa-case-critic -->
## Observable source

**Observable source** — `diff` (this story's implementation) · `current-code` (existing
behaviour on the default branch) · `expected-contract` (requirement, ticket, owner
answer, spec). Every observable names one.

<!-- roles: qa-requirements-tester, qa-case-designer, qa-case-critic -->
## Oracle basis

**Oracle basis** — `requirement:<R-n>` · `external:<ref>` · `history:<ref>`. A
new-behaviour row (`fit: new`, or `pending_implementation`) may use only `requirement:` or
`external:`; `history:` or an observable with `source: current-code` there is rejected —
current code never becomes the oracle for new behaviour.

<!-- roles: qa-case-designer, qa-case-critic -->
## A case's basis

A case's `basis` (per Then): `requirement:R-n` · `invariant:<id>` · `consistency:<where>` ·
`history:<baseline>` · `impact:<harm>` · `external:<norm>` (scripts/grammar.py). The plan row's
`oracle` column is another field, three kinds; never judge a basis by it.

<!-- roles: -->
## Where a Then's expected value comes from

**Oracle word** (`then_oracles`, one entry per Then of a case; `contract.THEN_ORACLE_WORDS`) — `code` is
not a word: a value read from the implementation under test can only pass. Beside the case `basis`
prefix: `requirement` ↔ `requirement:`, `spec` ↔ `external:`, `precedent` ↔ `history:` for a `base:` ref
(a `reference:` ref sits under `requirement:R-n` of a parity row, never under `history:`); `person` and `unknown`
carry a question id instead.

- `requirement` — a requirement of the register, read from any ticket source (the description, a criterion, a
  comment, an attachment, a linked ticket); `ref` is the register's R-n (never an implementation-only one).
- `ac` — the older name of `requirement`: a case saved with it is read as it was and never rewritten.
- `spec` — a document the story names; `ref` is R-n.
- `precedent` — a requirement names parity with OLDER behaviour; `ref` is `base:<rev>:<path>:<line>`, or `reference:<item>` (an item of the
  reference snapshot; only under a case basis `requirement:R-n` whose register row says `parity: yes`).
- `person` — a person answered the question; `ref` is its id. Read at run time, never edited into the case.
- `unknown` — nobody confirmed it; `ref` is the open question, which shows before/now. Never asserted.
- `claim` — not an oracle word: the `from` of the two readings of a before/now question (the behaviour
  now is shown as data, never `from: code`).
- `expectation_unconfirmed` (`ledger.EXPECTATION_UNCONFIRMED`) — the `reason` of a `then_bindings` row
  for an `unknown` Then (with `question`, `observed`): traceability `wait`, ledger
  `not_verified:expectation_unconfirmed`, listed in the report's "Left with you"; it holds nothing.

<!-- roles: qa-automator, qa-doc-scribe -->
## `unresolved[]` reason

**`unresolved[]` reason** (automation manifest) — `impossible` · `blocked_by_env` ·
`pending_implementation` · `blocked_by_check` · `contradicts_requirement` (the code does what the requirement
forbids: the row names the requirement id, the expected and the observed value) ·
`deferred_by_decision:<gate>`.

<!-- roles: qa-doc-scribe -->
## `remedy`

**`remedy`** (on a `blocked_by_env` row of the manifest, or an `env_blocked[]` row of the run
report) — `{kind: flag|credential|data|service, where: <file:lines or the variable NAME>,
change: <what to set>, restart?}`: the change that would end the block. Names only — a
credential value in an artifact is a leak. A blocked row without one is refused.

<!-- roles: qa-runner, qa-failure-analyst, qa-doc-scribe -->
## `execution_status`

**`execution_status`** (run report) — `passed` · `failed` · `env_blocked` ·
`not_executed` · `broken_run` · `timeout`. Computed from the run's own evidence, never
typed by a role.

<!-- roles: qa-failure-analyst, qa-bug-reporter, qa-doc-scribe, qa-retro-analyst -->
## Triage verdict and FLAKY mechanism

**Triage verdict** — `APP_BUG` · `TEST_BUG` · `TEST_BUG:collection` · `ENV_ISSUE` ·
`FLAKY` · `APP_CHANGED` · `CASE_DEFECT` · `ASSERT_STRICTER` · `RUNNER_MISREAD_EVIDENCE` · `NO_DEFECT`.

**FLAKY mechanism** — `isolation` · `race` · `timing` · `shared_state` · `teardown` ·
`environment` · `unknown`.

<!-- roles: qa-failure-analyst, qa-bug-reporter, qa-retro-analyst -->
## Bug confirmation

**`confirmation`** (a `bug-drafts/*.json` draft and the `bugs/BUG-n.md` it becomes) — who has
seen the defect. A red test is a draft until someone reproduces it.

- `unconfirmed` — the default: nobody outside the run has seen it. Still filed when the person
  chooses it at gate B, and it counts toward nothing.
- `reproduced_by_factory` — the analyst saw it fail again (a rerun on fresh data, or its own
  script) and the code checked the receipt; no person has confirmed it. Derived by code from the
  draft's `reproduction`, never written by a role. It counts toward nothing and changes no verdict.
- `confirmed_by_person` — said so at gate B, in words the decision records. A bug filed before
  this field existed carries none and reads as this.
- `confirmed_by_rerun` — a second run reproduced it on another stand (a different `environment`
  in the run receipt). The same stand twice is not a second reading.

<!-- roles: qa-doc-scribe, qa-retro-analyst -->
## Checks-ledger state

**Checks-ledger state** — exactly one per plan row and one per test:
`passed_green` · `failed:<verdict>` · `not_executed:<reason>` · `skipped:<reason>` ·
`env_blocked:<owner>` · `impossible` · `pending_implementation` · `deferred_by_decision`
· `not_verified_flaky` · `review_skipped` · `subtask_in_progress` · `waived` · `review_rejected` ·
`review_unverified` · `review_unrecognised:<word>` · `not_verified:<reason>` · `partial` · `error`.
`waived` — a person waived all its requirements: not passed, blocks nothing.

<!-- roles: qa-doc-scribe, qa-retro-analyst -->
## Traceability result

**Traceability result** — what the person reads for a requirement × case row, never a
ledger state: `pass` · `bug` (names `BUG-n`) · `wait` (handed to a person, or planned
manual) · `blocked` (the stand; with the cause and whether a decision is recorded) ·
`not run` · `unreachable` · `deferred` (a recorded decision) · `not planned`.
**Level** — `unit` · `component` · `api` · `integration` · `e2e-ui` · `manual-agent` ·
`manual-human`. **Shape** — `new` · `extend` · `reuse` · `parameterize` · `consolidate`.

<!-- roles: -->
## Retry reason

**Retry reason** (`retry_reason` on a dispatch that resumes another) — why the factory is
doing this piece of work a second time. One value, stamped by the controller when the
`parent_retry` link is created; a repeat a person asked for also carries their words in
`retry_words`. None of these is the person's to repair.

- `no_digest_at_exit` — the role ended without handing its result over.
- `subagent_silent` — the dispatch never reached an agent, or the agent stopped saying anything.
- `host_error:<code>` — the host or the network dropped the run (`host_error:ENOTFOUND`).
- `turn_budget` — the window's turn or context budget ran out mid-work.
- `compaction` — the context was compacted and the role continued in a fresh one.
- `unaccepted_result` — the work came back and was not accepted as it stood.
- `awaiting_person` — the role stopped on a question only a person can answer.
- `environment` — the stand: a toolchain, credential or service that was not there.
- `factory_defect` — a script of the factory itself broke the run.
- `checkpoint` — a planned window boundary: real progress was recorded and continues.
- `person_word` — a person asked for the repeat; `retry_words` holds what they said.
- `unknown` — the parent recorded nothing a reader could classify. Not a verdict on anyone.
