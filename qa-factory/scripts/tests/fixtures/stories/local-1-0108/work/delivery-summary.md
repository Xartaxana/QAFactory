<!-- factory-summary:start -->
## Recorded verification

| Rows in the plan | Checks run | Checks planned by hand | Checks run by hand | Rows verified | Rows that failed | Rows not verified | Rows blocked by the environment | Rows deferred |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 26 | 43 | 2 | 0 | 3 | 13 | 7 | 0 | 3 |

Rows and checks are different units and are not presented as a ratio. Checks run include current automated checks and manual checks whose evidence was recorded.

Tests by proof level: not probed: 15; probe not applicable: red: 19

- TS-2: only partly run
- TS-5: only partly run
- TS-6: only partly run
- TS-7: skipped — cosmetic, badge sum asserted inside TS-1 and TS-3; toast text goes to the Developers line
- TS-11: only partly run
- TS-12: only partly run
- TS-23: skipped — the owner's answer leaves no implemented quick-view add path to verify inside add-to-cart scope
- TS-24: not run — no result recorded for this row's cases
- TS-25: not run — no result recorded for this row's cases
- TS-26: skipped — unverifiable — no observable, two readings (BN-11); owner decides at gate A

## Left with you

1. **An unconfirmed expectation: what happens after the session expires (R-26, no case).** To check: answer Q9: after session expiry, must the system extend the session, or ask for login and then add the product? There is no test: the plan marks it as not observable in code. Needed: your answer to which of the two readings is right; accept the risk or defer with a reminder.
2. **A guest's add is kept by the cookie (R-5, LOCAL-1_TC_005).** To check: the guest add is accepted with no redirect to login, the same cookie sees the line for book B with quantity 1, an anonymous context sees none, and the cookie is persistent. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
3. **An out-of-stock book cannot be added (R-2, LOCAL-1_TC_002).** To check: after the UI attempt the cart has no line for the book and the badge is unchanged, a message names the out-of-stock state, and the API attempt is not a 2xx. There is a test in the cart UI suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
4. **A signed-in cart survives logout and login (R-6, LOCAL-1_TC_006).** To check: after login the cart page shows book B with quantity 2 and the cart API holds one line for it. There is a test in the cart UI suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
5. **Quantity above stock is refused with a message (R-11, LOCAL-1_TC_010).** To check: a visible message states the available number (4) and the cart holds no line for the book. There is a test in the cart UI suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
6. **Stock check counts copies already in the cart (R-12, LOCAL-1_TC_011).** To check: both second requests are refused with a 4xx, the line quantities stay 3 and 1, and a third add up to exactly the stock is accepted. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
7. **Quantity classes: valid values stored exactly, invalid ones rejected (R-13, LOCAL-1_TC_012).** To check: valid quantities are stored exactly as entered; zero, negative, fractional, non-numeric and above-stock values are rejected with a message and no line. There is a test with a variant per quantity class; the invalid ones are red because the product turns them into 1 (see Product bugs), and the code critic did not verify it. How: run it yourself after the product fix. Answer wanted: accept the risk.
8. **An extremely large quantity does not break the app (R-15, LOCAL-1_TC_014).** To check: each request gets a 4xx or is capped at most at the stock (10), never a 5xx, and the application still answers a normal add afterwards. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
9. **An unknown book id is refused (R-18, LOCAL-1_TC_017).** To check: the answer is 404 with the error code BOOK_NOT_FOUND and the cart gains no line. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
10. **A guest cart is merged at sign-in (R-22, LOCAL-1_TC_021).** To check: the guest item stays at the quantity the guest added, the higher quantity wins when both carts hold the book, and an item with no stock is dropped. There is a test; it is green, but the code critic could only read it, not run a deliberate-break check. How: run it yourself where you can. Answer wanted: accept the risk.

<!-- Every check the ledger leaves with the person has an item above - one per case, naming its R-n and its case
     id (`report_facts.py --check` names an item that is missing). The two code-owned blocks below stand LAST in the
     section and are never typed: what the person's gate B answers left with them (it exists only after the gate, and only
     when an answer did), and the plan's regression list, verbatim - it is always here and never changes the verdict.
     Nothing of yours goes after them. -->

<!-- facts:left-branches -->
### Branches left with you

- **BN-2** (R-8) — To check: A quantity of 0 is rejected with a clear message and nothing is added. Needed: LOCAL-1_TC_007 carries it, but no test or recorded check proves it
- **BN-3** (R-9) — To check: negative (-1) and fractional (1.5) quantities. Needed: LOCAL-1_TC_008 carries it, but no test or recorded check proves it
- **BN-7** (R-14) — To check: "maximum allowed" is not defined (stock vs the schema cap 999). Needed: LOCAL-1_TC_013 carries it, but no test or recorded check proves it
- **BN-10** (R-25) — To check: the system completes the action or notifies the user to retry. Needed: LOCAL-1_TC_023 carries it, but no test or recorded check proves it
- **BN-11** (R-26) — To check: the session is extended or a new login is asked. Needed: the role left it out, you have not said so: plan row TS-26 is `unverifiable`: No code observable (REF-8); two readings (BN-11); owner decides at gate A.
- **U-a929b15ff589** — To check: *Objective:* Verify that raising a cart line's quantity above available stock is rejected and the stored quantity stays unchanged. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-126d8bb02629** — To check: Book "Ariel" is in stock; read its real stock S0. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-b306bc733eb9** — To check: Initial quantity: 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-a9becee51472** — To check: Attempted cart quantity: S0 + 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-443c860e4a21** — To check: *Expected:* One line "Ariel" with quantity 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-a96b3e0b1a34** — To check: Change the line's quantity to S0 + 1 and commit it (Enter or blur). Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-640f71a6da65** — To check: *Expected:* A visible error states there is not enough stock. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-fb8e200cdf18** — To check: Reload the cart page. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-789949bf9f23** — To check: *Expected:* Line "Ariel" still shows quantity 1; cart badge shows 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-4e59f1300e2c** — To check: Cart line quantity is unchanged. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
<!-- /facts:left-branches -->

<!-- facts:regression -->
### Regression to run (from the plan approved at gate A)

No regression: the tests repository has no cart test (coverage_search tests: none) and the implementation source is current-code with no diff, so no existing test defends this blast radius; developers keep the application's own unit tests `src/lib/cartRules.test.ts` and `src/lib/validation/schemas.test.ts`.

Tests of this story (not regression): tests/api/cart/cart.spec.ts, tests/e2e/cart/cart.spec.ts
<!-- /facts:regression -->

<!-- facts:open-questions -->

What blocks delivery on the product side:
- traceability: R-1 has no terminal outcome (LOCAL-1_TC_001: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-2 has no terminal outcome (LOCAL-1_TC_002: run result 'partial' is not terminal)
- traceability: R-3 has no terminal outcome (LOCAL-1_TC_003: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-4 has no terminal outcome (LOCAL-1_TC_004: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-5 has no terminal outcome (LOCAL-1_TC_005: run result 'partial' is not terminal)
- traceability: R-6 has no terminal outcome (LOCAL-1_TC_006: run result 'partial' is not terminal)
- traceability: R-8 has no terminal outcome (LOCAL-1_TC_007: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-9 has no terminal outcome (LOCAL-1_TC_008: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-10 has no terminal outcome (LOCAL-1_TC_009: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-11 has no terminal outcome (LOCAL-1_TC_010: run result 'partial' is not terminal)
- traceability: R-12 has no terminal outcome (LOCAL-1_TC_011: run result 'partial' is not terminal)
- traceability: R-13 has no terminal outcome (LOCAL-1_TC_012: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-14 has no terminal outcome (LOCAL-1_TC_013: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-16 has no terminal outcome (LOCAL-1_TC_015: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-17 has no terminal outcome (LOCAL-1_TC_016: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-19 has no terminal outcome (LOCAL-1_TC_018: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-20 has no terminal outcome (LOCAL-1_TC_019: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-21 has no terminal outcome (LOCAL-1_TC_020: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-24 has no terminal outcome (LOCAL-1_TC_022: neither in automation-manifest tests[] nor unresolved[])
- traceability: R-25 has no terminal outcome (LOCAL-1_TC_023: neither in automation-manifest tests[] nor unresolved[])
- ledger: TS-2 is `partial` (LOCAL-1_TC_002)
- ledger: TS-5 is `partial` (LOCAL-1_TC_005)
- ledger: TS-6 is `partial` (LOCAL-1_TC_006)
- ledger: TS-8 is `failed:APP_BUG` (LOCAL-1_TC_007)
- ledger: TS-9 is `failed:APP_BUG` (LOCAL-1_TC_008)
- ledger: TS-10 is `failed:APP_BUG` (LOCAL-1_TC_009)
- ledger: TS-11 is `partial` (LOCAL-1_TC_010)
- ledger: TS-12 is `partial` (LOCAL-1_TC_011)
- ledger: TS-13 is `failed:APP_BUG` (LOCAL-1_TC_012)
- ledger: TS-24 is `not_executed:no result recorded for this row's cases` (LOCAL-1_TC_022)
- ledger: TS-25 is `not_executed:no result recorded for this row's cases` (LOCAL-1_TC_023)
- ledger: cart.spec.@regression LOCAL-1_TC_007 invalid_quantity_rejected[tc007_zero] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_007)
- ledger: cart.spec.@regression LOCAL-1_TC_008 invalid_quantity_rejected[tc008_negative] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_008)
- ledger: cart.spec.@regression LOCAL-1_TC_008 invalid_quantity_rejected[tc008_non_integer] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_008)
- ledger: cart.spec.@regression LOCAL-1_TC_009 invalid_quantity_rejected[tc009_non_numeric] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_009)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_zero] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_negative] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_non_integer] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_non_numeric] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- coverage red: OB-4 — none
- coverage red: OB-8 — none
- coverage red: OB-9 — none
- coverage red: OB-10 — none
- coverage red: OB-13 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage red: OB-14 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage red: OB-16 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage red: OB-17 — none
- coverage red: OB-19 — none
- coverage red: OB-20 — none
- coverage red: OB-21 — none
- coverage red: OB-23 — no implementation or observable

Factory defects (not the product's — nothing is wanted from you):
- 13 behaviour(s) no test proves because of the factory's tools or coverage; they stay unproven
- test instance LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal requires current sensitivity proof: no sensitivity receipt
- factory: LOCAL-1_TC_004 cart unit price and total equal the catalog price — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: LOCAL-1_TC_005 guest adds without login and the cart follows the cookie — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: LOCAL-1_TC_011 an add that exceeds stock is refused and the cart is unchanged — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: LOCAL-1_TC_013 maximum quantity is added with the right subtotal — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_001 an in-stock book is added once with the right price from the product page — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_002 an out-of-stock book cannot be added to the cart — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_006 a signed-in cart survives logout and login — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_010 a quantity above stock is refused with the available number shown — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- ledger: TS-1 is `failed:CASE_DEFECT` (LOCAL-1_TC_001)
- ledger: TS-3 is `failed:CASE_DEFECT` (LOCAL-1_TC_003)
- ledger: TS-4 is `failed:CASE_DEFECT` (LOCAL-1_TC_004)
- ledger: TS-14 is `failed:CASE_DEFECT` (LOCAL-1_TC_013)
- ledger: TS-16 is `failed:CASE_DEFECT` (LOCAL-1_TC_015)
- ledger: TS-17 is `failed:CASE_DEFECT` (LOCAL-1_TC_016)
- ledger: TS-19 is `failed:CASE_DEFECT` (LOCAL-1_TC_018)
- ledger: TS-20 is `failed:CASE_DEFECT` (LOCAL-1_TC_019)
- ledger: TS-21 is `failed:CASE_DEFECT` (LOCAL-1_TC_020)
- ledger: cart.spec.@api @regression LOCAL-1_TC_004 cart unit price and total equal the catalog price is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_004)
- ledger: cart.spec.@api @regression LOCAL-1_TC_013 maximum quantity is added with the right subtotal is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_013)
- ledger: cart.spec.@api @regression LOCAL-1_TC_015 adding the same product twice gives one line with the summed quantity is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_015)
- ledger: cart.spec.@api @regression LOCAL-1_TC_016 several products give one line each and a summed total is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_016)
- ledger: LOCAL-1_TC_001 an in-stock book is added once with the right price from the product page is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_001)
- ledger: LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_003)
- ledger: cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[product_page] is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018)
- ledger: cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[catalog_card] is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018)
- ledger: cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[wishlist_move] is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018)
- ledger: cart.spec.@regression LOCAL-1_TC_019 the catalog card adds the book to the cart with the right line is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_019)
- ledger: cart.spec.@regression LOCAL-1_TC_020 moving a wishlist item to the cart adds it and removes it from the wishlist is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_020)
- coverage: OB-1 — none
- coverage: OB-2 — none
- coverage: OB-3 — none
- coverage: OB-5 — none
- coverage: OB-6 — none
- coverage: OB-7 — toast text not asserted by an automated check
- coverage: OB-11 — none
- coverage: OB-12 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-15 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-18 — none
- coverage: OB-22 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-24 — none
- coverage: OB-25 — none

Bug publication:
Product bugs — 1 unconfirmed. An unconfirmed bug is one no person and no second run on another stand has reproduced; it counts toward nothing.
- qty-invalid-input-coerced: a draft, not chosen so far — unconfirmed
<!-- factory-summary:end -->
