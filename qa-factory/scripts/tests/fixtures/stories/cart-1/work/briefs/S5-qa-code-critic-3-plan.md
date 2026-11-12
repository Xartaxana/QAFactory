# S5 plan - window 2 of 4

Cases: CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008

## Requirements
R-7, R-8, R-11, R-12

## Cases

### CART-1_TC_005 (S3 row TS-5; level api; fit new; oracle requirement:R-7)
1. Control: G1's GET /api/cart lists B with quantity 2 (the guest sees its own row).
2. P-user: JU's GET /api/cart payload (request carrying both U's session and G1's guest cookie) contains no row for B and none of G1's rows (payload inspected directly; a user-owner query that also matches the guest sessionId would return B x2 here).
3. P-other-guest: G2's GET /api/cart payload contains no row for B and none of G1's rows (payload inspected directly).

### CART-1_TC_006 (S3 row TS-6; level api; fit new; oracle requirement:R-8)
1. P-overlap-higher-guest: B2 in U's cart has quantity 4 (guest 4 over user 1: max, not sum 5).
2. P-overlap-higher-user: B1 in U's cart has quantity 5 (user 5 over guest 2: max, not sum 7).
3. P-cap: B3 in U's cart has quantity 3 (guest 6 capped at stock 3).
4. P-soldout: U's cart has no row for B4.
5. P-disjoint: B5 is in U's cart with quantity 2; U's cart contains exactly the rows B1 x5, B2 x4, B3 x3, B5 x2 (and no row for B4).
6. P-unauth: the merge without a session answers 401.

### CART-1_TC_007 (S3 row TS-7; level api; fit new; oracle requirement:R-11)
1. P-set-equal: PUT succeeds (2xx) and the read-back row for B has quantity 5 (set, not added to 1).
2. P-over: PUT answers 400 INSUFFICIENT_STOCK.
3. After P-over the read-back row for B still has quantity 5.
4. P-delete: DELETE succeeds and the final GET /api/cart has no row for B.

### CART-1_TC_008 (S3 row TS-8; level api; fit new; oracle requirement:R-12)
1. Foreign PUT answers HTTP 404 with code CART_ITEM_NOT_FOUND.
2. Foreign DELETE answers HTTP 404 with code CART_ITEM_NOT_FOUND.
3. A's after_read rows are identical to the before_read rows (row R_A for K, quantity 2); mutable entity checked: CartItem only.
4. Positive control: A's own PUT succeeds and the next read shows K with quantity 3, proving R_A is reachable and mutable by its owner (so the 404s and the unchanged state are not an artifact of an unreachable id).
5. B's own GET /api/cart payload has no row for K.

## Remainders (left to a person)
none

## Tests

### T-5 - tests/api/cart/cart-isolation.spec.ts::CART-1_TC_005 cart isolation between owners (new, api, data own)
cases: CART-1_TC_005; asserts: CART-1_TC_005#1, CART-1_TC_005#2, CART-1_TC_005#3
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_005 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

### T-6 - tests/api/cart/cart-merge.spec.ts::CART-1_TC_006 guest cart merge on login (new, api, data own)
cases: CART-1_TC_006; asserts: CART-1_TC_006#1, CART-1_TC_006#2, CART-1_TC_006#3, CART-1_TC_006#4, CART-1_TC_006#5, CART-1_TC_006#6
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_006 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

### T-7 - tests/api/cart/cart-update-delete.spec.ts::CART-1_TC_007 update and delete cart item (new, api, data own)
cases: CART-1_TC_007; asserts: CART-1_TC_007#1, CART-1_TC_007#2, CART-1_TC_007#3, CART-1_TC_007#4
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_007 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

### T-8 - tests/api/cart/cart-ownership.spec.ts::CART-1_TC_008 foreign cart item mutation denied (new, api, data own)
cases: CART-1_TC_008; asserts: CART-1_TC_008#1, CART-1_TC_008#2, CART-1_TC_008#3, CART-1_TC_008#4, CART-1_TC_008#5
apart_reason: own setup and distinct Thens; no sibling case shares setup and action
assert: Each Then of CART-1_TC_008 asserted as written, state read back through GET /api/cart (UI: badge and cart page for TC_010)

## Remarks (plan review and case critic)
- PR-2 [remark] the whole plan (K-10; global): Boilerplate assert text on every test (mentions UI badge for API tests); shared helpers promised but not named per test. Expected: One cart API client and one guest-jar helper in core reused by T-1..T-9, no per-spec copies; Then values from R-n and case, never the code. Fix: Create the helpers once and use them in every window.
