# S5 plan - window 1 of 4

Cases: CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004

## Requirements
R-3, R-4, R-5, R-6

## Cases

### CART-1_TC_001 (S3 row TS-1; level api; fit new; oracle requirement:R-3)
1. P-unknown: HTTP 404 with body code BOOK_NOT_FOUND (body has error and code).
2. P-soldout: HTTP 400 with body code OUT_OF_STOCK.
3. Independent read: GET /api/cart in the same cookie jar returns no row for S0 and no row for the nonexistent id (read through the cart list, not the POST response).

### CART-1_TC_002 (S3 row TS-2; level api; fit new; oracle requirement:R-4)
1. P-equal: the second add (to exactly stock) succeeds with a 2xx status.
2. P-plus-one: the third add answers HTTP 400 with code INSUFFICIENT_STOCK.
3. GET /api/cart shows exactly one row for B with quantity 5 (not 6).
4. The row quantity read in Then 3 equals the stock of B (5) after the rejected add, so the rejected request changed nothing.

### CART-1_TC_003 (S3 row TS-3; level api; fit new; oracle requirement:R-5)
1. GET /api/cart contains exactly one row for B (no second row).
2. That row has quantity 3 (1 + 2: added, not replaced).

### CART-1_TC_004 (S3 row TS-4; level api; fit new; oracle requirement:R-6)
1. P-qty-min and P-qty-max: 2xx; GET /api/cart in that jar shows B with quantity 1 and 999 respectively.
2. P-qty-over, P-qty-zero, P-qty-fraction, P-qty-string: a 4xx rejection (never 5xx), not a 2xx.
3. P-id-zero, P-id-negative, P-id-fraction: a 4xx rejection (never 5xx).
4. Every rejection body contains both `error` and `code` fields, and GET /api/cart in that jar has no row created by the rejected request.

## Remainders (left to a person)
none

## Tests

### T-1 - tests/api/cart/add-rejections.spec.ts::CART-1_TC_001 add unknown or sold-out book rejected (new, api, data own)
cases: CART-1_TC_001; asserts: CART-1_TC_001#1, CART-1_TC_001#2, CART-1_TC_001#3
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_001 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

### T-2 - tests/api/cart/add-stock-limit.spec.ts::CART-1_TC_002 add beyond stock rejected (new, api, data own)
cases: CART-1_TC_002; asserts: CART-1_TC_002#1, CART-1_TC_002#2, CART-1_TC_002#3, CART-1_TC_002#4
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_002 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

### T-3 - tests/api/cart/add-accumulate.spec.ts::CART-1_TC_003 repeat add accumulates (new, api, data own)
cases: CART-1_TC_003; asserts: CART-1_TC_003#1, CART-1_TC_003#2
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_003 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

### T-4 - tests/api/cart/add-boundaries.spec.ts::CART-1_TC_004 quantity and id boundaries (new, api, data own)
cases: CART-1_TC_004; asserts: CART-1_TC_004#1, CART-1_TC_004#2, CART-1_TC_004#3, CART-1_TC_004#4
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_004 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

## Remarks (plan review and case critic)
- PR-1 [remark] case CART-1_TC_004, test T-4, then CART-1_TC_004#2 (K-2; window): Nine partitions share one setup and action but the plan is shape new with one body. Expected: shape parameterize; one parameter per partition, ids name the partition, Thens 2-4 asserted per parameter so one 5xx does not hide the others. Fix: Parameterize in the window and declare the deviation.
- PR-2 [remark] the whole plan (K-10; global): Boilerplate assert text on every test (mentions UI badge for API tests); shared helpers promised but not named per test. Expected: One cart API client and one guest-jar helper in core reused by T-1..T-9, no per-spec copies; Then values from R-n and case, never the code. Fix: Create the helpers once and use them in every window.
