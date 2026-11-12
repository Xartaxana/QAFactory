# Critic findings - S5-qa-code-critic-7 (CART-1_TC_010)

Roll-call: CART-1_TC_010 -> tests/e2e/cart/add-to-cart.spec.ts "@regression CART-1_TC_010 add from catalog shows badge and cart page" (OB-10, cv_514d05efe43b2506bb5f). Then 1-3 each asserted with a Then-named soft assert; badge compared with the sum read back through GET /api/cart (not a literal from code); own book and own data via ownBooks fixture.

- F-1 [tooling] probe_by_code cannot read Playwright TypeScript: verdict unverified, sensitivity_proof_missing_reason. Person's waiver "probe gap: CART-1_TC_010" applies. Not a test defect.
- F-2 [mechanical, non-blocking] core/pages/CartPage.ts itemByTitle/quantityOf use raw CSS attribute selectors (`[data-testid^=...]:not(...)`) instead of byId; acceptable as the testids are dynamic, but keep them in the page object only. Rubric 1a: the count is by row testid, not by text alone (hasText narrows a row, rows are testid-selected): fine.
- HomePage changes: locators as readonly via byId, actions as methods, no assertions in the page object; addToCart returns the response and the test asserts. Fits conventions.
- Note: Then 2 sum==1 assert and badge assert both read GET /api/cart; consistent with the case.
