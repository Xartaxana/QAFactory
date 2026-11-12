# Behavior-level risk and verification depth

Risk chooses depth, not model price. Apply the versioned project policy first; onboarding
records its sources and unresolved questions, not a universal industry checklist. If there
is no policy, use `factory-starter-v1` below and show that choice at Gate A.

Assess each changed behavior independently. Store impact, likelihood, existing confirmed
coverage and confidence separately. Ticket priority, diff length, component name or missing
tests alone cannot determine risk. Unknown business consequences remain unknown.

**Two scales, two fields.** A row's `impact` is this RISK scale: low, moderate, severe,
unknown. The register's damage class (`data-loss · money · access · blocked-flow · degraded ·
cosmetic · none`, what priority is derived from) is a different question: the row carries it
verbatim as `impact_class`. Likelihood is low, medium, high, unknown; confidence the same.
Project-specific scales need an explicit mapping and policy revision. Sources identify both
location and revision.

- Critical depth: evidenced severe consequences, including unauthorized access, irreversible
  data loss, material financial harm, or key-flow failure with broad impact. A one-line
  access-control diff may qualify. Cover important positive/negative paths, boundaries,
  applicable recovery/idempotency/data-integrity rules, and every material oracle branch.
  Independent case-design review is mandatory; new/changed assertions need sensitivity proof.
- Low depth: bounded, reversible, local effect; sufficient consistent sources; low defect
  likelihood and a clear oracle. A cosmetic hint may qualify, but not if it affects a
  critical decision. Minimum sufficient checks still need meaningful independent code review.
- Normal depth: the remaining understood changes. A reversible local calculation generally
  qualifies absent stronger risk evidence. Unknown impact/oracle or conflicting sources
  require independent design review and explicit unresolved scope; never downgrade to low.

Missing coverage increases required verification and reduces confidence; it does not invent
catastrophic impact. A budget shortage does not lower risk. Offer a cheaper sufficient level
or expose the gap. Reuse verified existing coverage and choose the lowest sufficient test
layer. Independent oracle must not recompute the same implementation output. Async negative
checks need an action-completion or observation boundary. Limited list queries do not prove
absence without complete search or a direct lookup.

Write each row in work/test-plan.json with id, impact, impact_class, likelihood, confidence,
risk_rationale, risk_source_refs[], risk_policy_revision, coverage_refs[], unknowns[],
verification_depth, required_scenarios[], test_level_rationale, design_review_required. Include
bounded_reversible for starter low depth. A row the register's `## Contradiction matrix`
touches carries `source_conflict: true` (requirement sources disagree with each other; a diff against a requirement is the register's `code_says` cell, not a matrix row) or
`oracle_unknown: true` (no settled expected value): both force independent design review and
reach gate A as the owner's question, with the matrix quote. `test-plan.md` is the human view
of the same rows. Critical/ambiguous design review records author and independent reviewer
dispatch IDs and the exact reviewed plan/case versions. Regression is recommendation-only for
every depth, including CI. Model policy is separate.
