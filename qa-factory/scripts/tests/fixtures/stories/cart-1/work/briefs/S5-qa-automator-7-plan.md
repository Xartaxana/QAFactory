# S5 plan - window 4 of 4

Cases: CART-1_TC_010

## Requirements
R-1, R-2, R-10

## Cases

### CART-1_TC_010 (S3 row TS-10; level e2e-ui; fit new; oracle requirement:R-1)
1. The add call for B completes successfully (2xx) after the click.
2. The cart badge text equals the sum of quantities in the cart, 1.
3. The cart page lists B (by its unique title) with quantity 1; the content, not just the page visibility, is asserted.

## Remainders (left to a person)
none

## Tests

### T-10 - tests/e2e/cart/add-to-cart.spec.ts::CART-1_TC_010 add from catalog shows badge and cart page (new, e2e-ui, data own)
cases: CART-1_TC_010; asserts: CART-1_TC_010#1, CART-1_TC_010#2, CART-1_TC_010#3
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_010 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

## Remarks (plan review and case critic)
- PR-2 [remark] the whole plan (K-10; global): Boilerplate assert text on every test (mentions UI badge for API tests); shared helpers promised but not named per test. Expected: One cart API client and one guest-jar helper in core reused by T-1..T-9, no per-spec copies; Then values from R-n and case, never the code. Fix: Create the helpers once and use them in every window.
