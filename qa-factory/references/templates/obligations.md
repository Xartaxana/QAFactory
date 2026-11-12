# Obligations ledger

Lives at `qa-factory/obligations.md` in the project. Written by `qa-doc-scribe` at S8/S9 of
every story; read at the start of the next `qa-story` (S0) — any obligation whose trigger
has arrived is shown to the human before work begins.

Rules:

- One row = one obligation. The essence — in plain language, one sentence: what must be
  done and why.
- **The registry is shared, writers are many** (sessions, the orchestrator): re-read the
  file from disk before writing and APPEND only — never delete or reorder another writer's
  row; the id is the next free one across the whole file.
- The trigger is a concrete observable event ("MR-456 merged", "the owner answered
  question 3", "a credential for `staging` is issued"), never "later".
- An env-debt obligation is legitimate only with a link to the human's decision (a gate B
  event in the journal) — a skip is never the factory's own call, see `common-rules.md`.
- An `automate` case with zero real executions gets a first-run obligation.
- A status changes only with a witness: what closed it and when (a commit, a run, an
  answer).

| id | essence (plain language) | task | type | trigger | created | details | status |
|---|---|---|---|---|---|---|---|
| OB-1 | When the backend MR merges, remove the old area tests and verify nothing orphaned | PRJ-123 | deferred-verification | MR-456 merged | 2026-09-01 | test-plan.md, row TS-03 | open |
| OB-2 | The pre-prod-only case has never actually executed — first run once credentials arrive | PRJ-123 | first-run | pre-prod access issued | 2026-09-01 | test-cases/ui/TC-001.md | open |

Types: `deferred-verification` (a check waiting for an event) · `first-run` (the case is
written but has never executed) · `env-debt` (only with the human's gate decision) ·
`external-writes` (a proposal file awaiting the executor) · `owner-questions` (an open gate
A/B question still unanswered).

Statuses: `open` · `ripe` (the trigger has arrived, surfaced to the human) · `closed`
(+witness) · `waived` (by the human's decision, with a date).
