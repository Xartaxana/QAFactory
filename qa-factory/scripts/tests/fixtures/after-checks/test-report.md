# QA-1 — test report

**The change.** Checkout refuses a coupon above the cap and recalculates the cart total for every accepted coupon.

<!-- facts:verdict -->
<!-- /facts:verdict -->

Notation: R-n — a requirement (the list with its text: understanding.md, "What we verify");
TC-n — a test case (test-plan.md, "Case appendix"); TS-n — a plan row.

<!-- facts:proven -->
<!-- /facts:proven -->

<!-- facts:manual-checks -->
<!-- /facts:manual-checks -->

<!-- facts:bugs -->
<!-- /facts:bugs -->

<!-- facts:review-gaps -->
<!-- /facts:review-gaps -->

## Left with you

1. **The cart total after a coupon (R-2, TC-002).** To check: the persisted order shows the discounted total 180.00, not the rendered label. There is no test: the manual check could not conclude, the order record page returned 503 for the whole window. How: open order 8812 once the page is up and read the total.
2. **The token confirmation (R-4, TC-004).** To check: the token confirmation is asked for before the order is placed. There is no test: it needs a hardware token. Needed: a hardware-token customer account and the token.
3. **The coupon form on the android profile (R-5, TC-005).** To check: the coupon is accepted and the total is recalculated. There is a test: `TC-005`; the factory could not run it here. How: `android: npm run e2e -- --grep TC-005`.

<!-- facts:regression -->
<!-- /facts:regression -->

<!-- facts:open-questions -->
<!-- /facts:open-questions -->

<!-- facts:skipped-by-plan -->
<!-- /facts:skipped-by-plan -->

<!-- facts:not-proven -->
<!-- /facts:not-proven -->

<!-- facts:gate-a -->
<!-- /facts:gate-a -->

## Factory defects — nothing is wanted from you

Nothing the factory's own bookkeeping got wrong changes what this report says.

<!-- facts:size -->
<!-- /facts:size -->

<!-- facts:where-to-look -->
<!-- /facts:where-to-look -->

## Appendix — traceability

Sorted by requirement, then by case. Result vocabulary: **pass** · **BUG-n** · **wait** (the case is handed to a person) · **blocked** (the stand) · **not run** · **unreachable** (the scenario cannot occur in the product) · **deferred** (a recorded decision) · **not planned**. Level: unit · component · api · integration · e2e-ui · manual-agent · manual-human. Shape: new · extend · reuse · parameterize · consolidate.

Test files: **C** = `tests/test_coupon.py`, **S** = `tests/e2e/coupon.android.spec.ts`.

| R | What we verify | TC · Then | Test | Level · shape | Result | Basis |
|:--|:--|:--|:--|:--|:--|:--|
| R-1 | A coupon above the cap is rejected with DISCOUNT_TOO_LARGE | TC-001 | C `ti_`<br>`4fa2889035cac1487897` | api<br>new | **pass** | reviewed by the code critic - not probed (unchanged test) |
| R-1 | A coupon above the cap is rejected with DISCOUNT_TOO_LARGE | TC-001<br>ti_4fa2889035cac1487897 | C `ti_`<br>`4fa2889035cac1487897` | api<br>new | **pass** | reviewed by the code critic - not probed (unchanged test) |
| R-2 | The cart total is recalculated once a coupon is applied | TC-002 | — | manual-agent | **not run** | one-off check against the live order record |
| R-3 | The coupon field keeps focus after a rejected submit | TS-3 | — | — | **deferred** | cosmetic, outside the diff, no user impact recorded |
| R-4 | The token confirmation is asked for a hardware-token customer | TC-004 | — | manual-human | **wait** | a hardware token is needed |
| R-5 | The coupon form works on the android profile | TC-005 | S `ti_`<br>`b07d43ab51f78f92d998` | e2e-ui<br>new | **wait** | android: npm run e2e |
| R-5 | The coupon form works on the android profile | TC-005<br>ti_b07d43ab51f78f92d998 | S `ti_`<br>`b07d43ab51f78f92d998` | e2e-ui<br>new | **wait** | android: npm run e2e |
