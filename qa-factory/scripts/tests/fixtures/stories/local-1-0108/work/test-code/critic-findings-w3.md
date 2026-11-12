# Critic findings - window 3 (S5-qa-code-critic-5), LOCAL-1_TC_001, LOCAL-1_TC_002

Roll-call (case -> instance, file tests/e2e/cart/cart.spec.ts):
- LOCAL-1_TC_001 -> "cart.spec.@regression LOCAL-1_TC_001 an in-stock book is added once with the right price from the product page" (Thens 1,2,3 at lines 25/30/36/41)
- LOCAL-1_TC_002 -> "cart.spec.@regression LOCAL-1_TC_002 an out-of-stock book cannot be added to the cart" (Thens 1,2,3 at lines 62/66/73)

Probe: not run. Person's recorded word: probe gap tooling:typescript, "not receipted". TC_001 is red with a contradicts_requirement row (no probe by rule). TC_002 stays `unverified`: tooling, no test defect found other than F-1/F-2 below.

## TC_001 (R-1) - approved_with_fixes (expected RED)
Red proves the requirement: GET /api/cart line carries no price, assert `unitPrice(line) toBe price(catalog)`. The oracle P is read from the catalog API (not the code under test); the cart is read through the API independent of the click; count asserted before unpacking; price assert placed last so Thens 2 and 3 are not hidden. No invented expectation, no stricter assert. No finding.

## TC_002 (R-2) - unverified (tooling, no probe)
- F-1 cause: mechanical, cart.spec.ts:66 - raw locator `page.getByText(/out of stock/i)` in the test body. Expected: a `BookDetailPage` member (e.g. `outOfStockText`).
- F-2 cause: mechanical, cart.spec.ts:70-74 - the API attempt (Then 3) is independent of Thens 1-2 yet runs after them; a red on Then 1/2 hides it. Expected: Then 3 evaluated before the Then 1/2 asserts, or soft assertions. No assertion value changes.
- Note (no cause): the UI branch clicks only if the control is enabled; both Q5 readings pass, by design of the case.

Plan remarks PR-1/PR-6 (reuse, TC_001/TC_003 parameterization): author declared shape new; not a window defect.
