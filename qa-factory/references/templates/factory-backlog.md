# Findings about the factory itself

Lives at `qa-factory/factory-backlog.md` in the project. Written by `qa-retro-analyst` at
S9 of every story (and by any role, via the orchestrator); read whenever the factory's own
setup is revisited.

## Findings about the factory

A finding has one of three addressees, the `scope` field:

- `local-urgent` — breaks runs here and now (a broken schema, a dead hook): fix in this
  project's factory before the next story;
- `local-calibration` — an inconvenience with no acute pain (numbering, report noise): no
  deadline, revisited when several similar findings accumulate;
- `upstream-candidate` — a candidate for the shared plugin canon. Passing upstream is a
  human decision, not automatic: a local adaptation is not necessarily a canon defect.

Rules:

- **The registry is shared**: re-read the file from disk before writing, append only
  (never touch another writer's row), the id is the next free one across the whole file.
- The essence is in plain language, with a witness (journal, file, verbatim output) — a
  finding with no evidence is not accepted.
- A `local-urgent` finding is not left open past the story that found it — either fixed, or
  explicitly reasoned why not, before the next story starts.

| id | essence | scope | witness/details | created | status | decision |
|---|---|---|---|---|---|---|
| FB-1 | The exit gate blocks the agent finishing now, not the author of the broken artifact | upstream-candidate | journal.jsonl: three unsafe_completion events on 09-01 | 2026-09-01 | passed | yes, 09-01 |
| FB-2 | Case-id numbering collides across areas — an area prefix is needed | local-calibration | S4 designer finding, case-review notes | 2026-09-01 | open | — |

Statuses: `open` · `fixed` (+ commit) · `passed` (upstream, with the decision date) ·
`rejected` (with a reason).

## Deferred decisions (onboarding/gates)

Not a task obligation (those live in `obligations.md`) — a debt of the factory's own setup:
an onboarding or gate question left unanswered, with a default taken in its place (the
main risk areas left open, a tracker integration postponed, a threshold unknown), except an
impact-class map left unanswered with no legacy value: the canonical map stands, no row. Such a
choice is made while the project does not yet fully understand the factory, and must stay
visible.

Rules:

- Every row is paired with a machine marker `[DEFERRED: <the essence in one sentence>]` in
  the document where the hole was left (`test-strategy.md`, `project-profile.md`,
  `config.json`). A marker with no matching DD row is a violation: a hole with no record is
  invisible.
- **`asked` is mandatory**: the question as it was actually put, plus where (which interview
  batch, or which gate). A deferral records "we asked and the answer did not come"; a topic
  nobody asked about gets no row at all — it gets asked. A13 fails a row with an empty
  `asked` cell, which is what keeps "deferred" from becoming a place to file skipped
  questions.
- The ripeness trigger is a named event ("a live environment appears", "after 5
  precedents"), never "later".
- Closing — only by an explicit decision with a witness (who, when, what); the paired
  marker is removed from its document in the same move.

| id | essence + where the marker is | asked | ripeness trigger | created | status | decision with witness | field_refs | scope | owner | trigger_type | trigger_value | resolution_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

Statuses: `open` · `closed` (+ decision with witness: who, when, what was decided).
