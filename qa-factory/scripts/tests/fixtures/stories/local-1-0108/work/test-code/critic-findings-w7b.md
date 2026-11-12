# Critic findings, window 7 re-check (S5-qa-code-critic-11), LOCAL-1_TC_018, LOCAL-1_TC_019

Roll-call
- LOCAL-1_TC_018 -> tests/e2e/cart/cart.spec.ts add_path_obeys_the_add_rules[product_page|catalog_card|wishlist_move]: approved (red = product, contradicts_requirement, Then 1 price)
- LOCAL-1_TC_019 -> tests/e2e/cart/cart.spec.ts catalog card adds the book...: approved (same)

Checks
- (a) networkidle replaced: BasePage.clickAndAwaitCartReply (core/pages/BasePage.ts:6) waits for the POST /api/cart response; used at cart.spec.ts:388. No expectation change. (networkidle remains only in BookDetailPage.ts:42,55, outside this window.)
- (b) TC_018 refs 370/383/390/394 match asserts (Then 2, 4, 3, 1) - OK.
- (c) then_bindings: 87 rows, TC_001..TC_019 all present, no row without case/status; 32 tests, all with critic_verdict. TC_014..017 refs verified against tests/api/cart/cart.spec.ts: 014 -> 111,118,123; 015 -> 137,140; 016 -> 158,165; 017 -> 182,186 - each line asserts the named Then.
- Independent Thens: soft asserts, the price assert last, so a red price does not hide Thens 2-4.

Findings
- F-1 cause: mechanical (non-blocking). TC_019 then_bindings refs are one line off: manifest says cart.spec.ts:421 (Then 1) and :417 (Then 2); the asserts are at :420 and :416. Fix: correct both refs, a bookkeeping change, no assertion change.

Not verified
- No probe on the 4 instances: person's word, probe gap tooling:typescript, "not receipted". Cause tooling, not a verdict on the tests.

Note (no cause): Then 1 asks for the catalog price on the cart line; the product returns no price field - contradicts_requirement, left to S7.
