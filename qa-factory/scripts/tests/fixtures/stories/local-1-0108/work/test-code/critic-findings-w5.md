# Critic findings, window 5 (S5-qa-code-critic-8): LOCAL-1_TC_007, TC_008, TC_009

Test: tests/e2e/cart/cart.spec.ts, parameterized `invalid_quantity_rejected` (4 instances). Page object: core/pages/BookDetailPage.ts.

## Roll-call (case -> instance)
- LOCAL-1_TC_007 -> invalid_quantity_rejected[tc007_zero] (OB-8)
- LOCAL-1_TC_008 -> invalid_quantity_rejected[tc008_negative], [tc008_non_integer] (OB-9)
- LOCAL-1_TC_009 -> invalid_quantity_rejected[tc009_non_numeric] (OB-10)

## Static review
- Oracle: requirement R-8/R-9/R-10 (rejected, no cart line, field keeps typed value). No literal taken from the code. Pass.
- Thens: 1 (visible message), 2 (cart via API has 0 lines for B, asserted first, independent of the UI), 3 (field keeps typed value; for "abc" only `not.toHaveValue('1')`, per CC-1). All soft asserts, so no independent Then hides behind a red. Pass.
- Quantity typed with real keystrokes (`typeQuantity`: click, selectText, pressSequentially). Pass.
- Own data: one book per test (stock 50), own context, closed in finally. Pass.
- Wait: `addToCartAndSettle` waits on a message or toast with a bounded timeout and networkidle, no sleep. Pass.
- Statuses: all four red / contradicts_requirement per the person's decision (BookDetailPage.tsx:164 coerces to 1). Not a defect of the tests.
- Parameter ids name their case (caseId in title and partition). Pass.

## Notes
- N-1 (no cause, reader note): `invalidQuantityMessage` is a broad text regex (`invalid|must be|positive|...`). A different page text matching it could turn Then 1 falsely green once the product is fixed. Not blocking; suggest a tighter locator when the app gains a test id.
- Then 3 for TC_009 asks only "not 1": weaker than the requirement by decision CC-1, accepted.

## Probes
No probe receipts: person's recorded word, probe gap tooling:typescript, "not receipted". Each row carries `sensitivity_proof_missing_reason`. Red tests with a `contradicts_requirement` row take no probe. cause: tooling for the probe gap, not the test's defect.

## Findings
None with a cause blocking approval.
