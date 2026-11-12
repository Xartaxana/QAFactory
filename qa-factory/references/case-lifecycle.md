# Case lifecycle actions

<!-- roles: qa-case-critic -->
## `state/story-case-links.json`

**Writer** `case_versions.py`. Each link pins `case_id`, `version`, `content_hash`, the
task-local snapshot `path` and `store_provenance`, whose `source_path` is **project-relative
with forward slashes** (audit A20: a delivered artifact never carries a machine-local path).
A pin written before that rule keeps its absolute value and is read without failing.

<!-- roles: qa-case-critic -->
## `test-cases/<area>/critic-findings.md`

**Writer** `qa-case-critic`, one file per area, a new round prepended on top, opening with a
`# ` heading (its sections use `##`); the bytes of earlier rounds are never edited (Gate A
matches a round's receipt against the end of the file). **Readers** the designer,
the orchestrator's Gate A message, `critic_rollcall.py`. **Shape** a `Verdict:` line from
`approve · approve_with_fixes · approve_with_concerns · partial · reject`; a `## Roll-call`
table `plan row | case | reviewed | verdict | note` with `reviewed` = `yes`/`no` and `verdict`
= one word of that list for the row's cases (Gate A reads each plan row's word there, never in
`note`); when anything is `no`,
the digest phrase `N of M reviewed` and a line `Unreviewed for Gate A: TC-…`; for
`approve_with_fixes`, `## Fixes without a new round` holding one fenced JSON array of
`{case_id, locator, find, replace, reviewed_version}`, and `## Gate A debts` for any of them
not applied, each line naming an `owner:`. **Validator** `critic_rollcall.py`, on write and
again at the S4 exit gate: the verdict is computed from the roll-call rather than quoted, so
an approving verdict beside an unreviewed row is refused, and every declared replacement must
be in the pinned case at a version later than the one reviewed.

<!-- roles: qa-case-critic -->
## Who pins a case version

`case_versions.py` writes `state/story-case-links.json`; the **orchestrator** runs it, once
for the whole story (`--all`) after the designer returns and after every repair round, and
`--verify` before dispatching the critic, which reviews pinned versions and nothing else. The
designer's handover is the case files: it has no Bash, and a role blocked for not running a
bookkeeping script is a defect of the factory, not of the role (TP1-15045, where the
orchestrator ended up pinning the cases itself and the event read "pinned by orchestrator
script"). Running an official script over the story's own state is not repairing a role's
artifact.

<!-- roles: qa-case-critic -->
## A fix that needs no second review round

The round cap stops review loops, not one-line repairs. A last-round concern that comes with
the exact replacement text is carried in the critic's `approve_with_fixes` block and applied
by CODE — `critic_rollcall.py --apply-fixes`, run by the orchestrator, with no dispatch and no
new round: it writes the replacement into the authoring case file, re-pins it, and checks that
the text is in the pinned case at a version later than the one reviewed. A replacement that
matches zero or several places cannot be applied by anything: it reaches Gate A as a debt with
an owner — never as a footnote in a findings file — and is then the person's call, not a
repair the factory owes itself.

At Gate A, propose `adapt`, `migrate`, or `retire` actions with exact CaseVersion pins,
coverage before/after, authoritative requirement change refs, replacement and shared-dependent
evidence. A removed component alone never authorizes retirement. Migration needs a replacement.

At Gate B, authorize `case_lifecycle` with the exact action hash and source revision. Run
`case_lifecycle.py INPUT --prepare-archive` only for an approved retirement. Archive transport
uses remote revision CAS and an idempotency key; unsupported archive remains pending. Historical
pins and prior results are never deleted.
