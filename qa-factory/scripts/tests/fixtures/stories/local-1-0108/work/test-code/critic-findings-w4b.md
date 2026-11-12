# Critic findings - S5-qa-code-critic-7 (LOCAL-1_TC_003, round 2)

Roll-call: LOCAL-1_TC_003 -> `cart.spec.@regression LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal` (tests/e2e/cart/cart.spec.ts:79-117), verdict approved.

Round-1 defect (Then 4 set by fill) is repaired: `BookDetailPage.typeQuantity` (core/pages/BookDetailPage.ts:23-27) clicks, selects and pressSequentially types; the test asserts value "3" whole and focus kept before the add click (lines 92-93). Locators are page-object based; the unit-price Then (line 113) is last, so it hides no other Then.

Unit-price Then stays RED: contradicts_requirement (R-3, cart line has no price field). Accepted red per gate A.

Probe: not run. Gap tooling:typescript, recorded person's words "not receipted". cause: tooling.
No test_defect findings.
