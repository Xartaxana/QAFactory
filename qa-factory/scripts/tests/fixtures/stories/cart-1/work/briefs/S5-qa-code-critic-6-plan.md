# S5 plan - window 3 of 4

Cases: CART-1_TC_009

## Requirements
R-15

## Cases

### CART-1_TC_009 (S3 row TS-9; level api; fit new; oracle requirement:R-15)
1. P-empty: the quote answers 400/409/422 (not 401, 404 or 5xx) with a JSON body carrying `error` and `code`, and issues no quote (no quote items in the body). The signed-in session is proven by Then 2 succeeding on the same jar and path.
2. P-quote: the quote lists B1 x2 and B2 x1 (items and quantities read from the quote body match the cart read from GET /api/cart).
3. P-overstock: the quote answers 400/409/422 (not 401, 404 or 5xx) with a JSON body carrying `error` and `code`, and the body or message identifies B1 (the item above stock); no quote items are issued. Exact code value is not asserted (Q1).
4. P-order: the order succeeds (2xx) with items B1 x2 and B2 x1.
5. After the order GET /api/cart as U has no row for B1 or B2 (cart cleared).

## Remainders (left to a person)
none

## Tests

### T-9 - tests/api/cart/cart-quote-order.spec.ts::CART-1_TC_009 quote and order from cart (new, api, data own)
cases: CART-1_TC_009; asserts: CART-1_TC_009#1, CART-1_TC_009#2, CART-1_TC_009#3, CART-1_TC_009#4, CART-1_TC_009#5
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_009 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

## Remarks (plan review and case critic)
- PR-2 [remark] the whole plan (K-10; global): Boilerplate assert text on every test (mentions UI badge for API tests); shared helpers promised but not named per test. Expected: One cart API client and one guest-jar helper in core reused by T-1..T-9, no per-spec copies; Then values from R-n and case, never the code. Fix: Create the helpers once and use them in every window.
- CC-1 [remark] case CART-1_TC_009 (case critic, S4; window): Round 1 C-1, C-3, C-4 resolved (error/code shape, B1 named, paths pinned, PC-3). Open concern: PC-1 stand_account user is checked only for credential keys; "verified" is assumed in prose and left to S5, so a non-verified seed user fails POST /api/orders at S5, not at the preflight. Four partitions share one cart, accepted with named P- ids. Seeded defect (order not clearing cart, quote not reading cart) fails Then 5 / Then 2 (OB-9, design_analysis). Expected: the case critic's full finding is in work/test-cases/critic-findings.md, round S4-qa-case-critic-2; take it into account when the case is automated, or say in `plan_remarks` why it does not apply Fix: S5 automator: confirm the seed user is verified before the first run, or create a verified user in the case; no case text change required.
