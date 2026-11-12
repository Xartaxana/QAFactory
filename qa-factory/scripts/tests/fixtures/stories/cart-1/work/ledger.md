# CART-1 — checks ledger

| Ref | Kind | State | Detail |
|---|---|---|---|
| TS-1 | plan_row | `passed_green` | CART-1_TC_001 |
| TS-2 | plan_row | `passed_green` | CART-1_TC_002 |
| TS-3 | plan_row | `passed_green` | CART-1_TC_003 |
| TS-4 | plan_row | `passed_green` | CART-1_TC_004 |
| TS-5 | plan_row | `passed_green` | CART-1_TC_005 |
| TS-6 | plan_row | `passed_green` | CART-1_TC_006 |
| TS-7 | plan_row | `passed_green` | CART-1_TC_007 |
| TS-8 | plan_row | `passed_green` | CART-1_TC_008 |
| TS-9 | plan_row | `failed:ASSERT_STRICTER` | CART-1_TC_009 |
| TS-10 | plan_row | `passed_green` | CART-1_TC_010 |
| TS-11 | plan_row | `passed_green` | CART-1_TC_011 |
| TS-12 | plan_row | `passed_green` | CART-1_TC_012 |
| @api @regression CART-1_TC_001 add unknown or sold-out book rejected | test | `review_unverified` | [1] |
| @api @regression CART-1_TC_002 add beyond stock rejected | test | `review_unverified` | [2] |
| @api @regression CART-1_TC_003 repeat add accumulates | test | `review_unverified` | [3] |
| @api @regression CART-1_TC_004 rejected with a stable error shape[P-id-fraction] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 quantity accepted[P-qty-min] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 quantity accepted[P-qty-max] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 rejected with a stable error shape[P-qty-over] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 rejected with a stable error shape[P-qty-zero] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 rejected with a stable error shape[P-qty-fraction] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 rejected with a stable error shape[P-qty-string] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 rejected with a stable error shape[P-id-zero] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_004 rejected with a stable error shape[P-id-negative] | test | `review_unverified` | [4] |
| @api @regression CART-1_TC_005 cart isolation between owners | test | `review_unverified` | [5] |
| @api @regression CART-1_TC_006 guest cart merge on login | test | `review_unverified` | [6] |
| @api @regression CART-1_TC_007 update and delete cart item | test | `review_unverified` | [7] |
| @api @regression CART-1_TC_008 foreign cart item mutation denied | test | `review_unverified` | [8] |
| @api @regression CART-1_TC_009 quote and order from cart | test | `failed:ASSERT_STRICTER` | tests/api/cart/cart-quote-order.spec.ts::CART-1_TC_009 |
| @regression CART-1_TC_010 add from catalog shows badge and cart page | test | `review_unverified` | [9] |

[1] tests/api/cart/add-rejections.spec.ts::CART-1_TC_001 — tooling: probe_by_code cannot read this project's TypeScript tests (no selector_args/report_test_id; template-literal titles unmatched); person's word recorded as waiver 'probe gap'
[2] tests/api/cart/add-stock-limit.spec.ts::CART-1_TC_002 — tooling: probe_by_code cannot read this project's TypeScript tests (no selector_args/report_test_id; template-literal titles unmatched); person's word recorded as waiver 'probe gap'
[3] tests/api/cart/add-accumulate.spec.ts::CART-1_TC_003 — tooling: probe_by_code cannot read this project's TypeScript tests (no selector_args/report_test_id; template-literal titles unmatched); person's word recorded as waiver 'probe gap'
[4] tests/api/cart/add-boundaries.spec.ts::CART-1_TC_004 — tooling: probe_by_code cannot read this project's TypeScript tests (no selector_args/report_test_id; template-literal titles unmatched); person's word recorded as waiver 'probe gap'
[5] tests/api/cart/cart-isolation.spec.ts::CART-1_TC_005 — tooling: probe_by_code refused, no selector_args/report_test_id for a Playwright TS test; probe gap returned to conductor
[6] tests/api/cart/cart-merge.spec.ts::CART-1_TC_006 — tooling: probe_by_code refused, no selector_args/report_test_id for a Playwright TS test; probe gap returned to conductor
[7] tests/api/cart/cart-update-delete.spec.ts::CART-1_TC_007 — tooling: probe_by_code refused, no selector_args/report_test_id for a Playwright TS test; probe gap returned to conductor
[8] tests/api/cart/cart-ownership.spec.ts::CART-1_TC_008 — tooling: probe_by_code refused, no selector_args/report_test_id for a Playwright TS test; probe gap returned to conductor
[9] tests/e2e/cart/add-to-cart.spec.ts::CART-1_TC_010 — tooling: probe_by_code cannot read Playwright TypeScript; person accepted probe gap: CART-1_TC_010

## Behavior evidence

| Obligation | Design | Execution | Verified | Gap |
|---|---|---|---|---|
| OB-1 | unknown | not_run | False | disabled buttons not covered (UI) |
| OB-2 | unknown | not_run | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-3 | unknown | not_run | False | none |
| OB-4 | unknown | not_run | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-5 | sufficient | passed | False | none |
| OB-6 | sufficient | passed | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-7 | sufficient | passed | False | none |
| OB-8 | sufficient | passed | False | proves no persistent change, not that no write was attempted |
| OB-9 | sufficient | failed | False | payment itself is out of scope |
| OB-10 | sufficient | passed | False | detail-page and wishlist paths are manual-agent rows |
| OB-11 | sufficient | passed | True |  |
| OB-12 | sufficient | passed | True |  |

## Manual evidence

- CART-1_TC_011: pass — expected: ['detail-page add with quantity']; actual: Signed in as the seed user with an emptied cart. D3 (stock 3), qty 2, Add to Cart: toast '2 copies added to cart'; cart page lists D3 with subtotal $20.00 (2 x $10.00). D3 qty 4: error toast 'Only 3 in stock and 2 already in your cart'; cart page still shows D3 at $20.00 (qty 2). D0 (stock 0): stock badge and button label read 'Out of Stock', the button is labelled Out of Stock and D0 is absent from the final cart (only D3 listed); the disabled attribute read returned an empty string for both enabled and sold-out buttons, so the disabled state itself rests on the label and the page screenshot. — [supporting](evidence/161312019d970d8b8711dbcc9cab050321950775c2eac687accfa885bb6a0770.png) · [pre_action](evidence/8b1888b0ad54a18e12416fc24e07b3aa943421227bc84c60ccf7e1b5cc394d1d.png) · [supporting](evidence/6ff3124b9bc32b454d08d251e8ed4265f7094435cfb2468ef5a9783ff8ab8930.txt) · [post_action](evidence/c29fe4ce9032e9f6aa7c0358f2824ed8dbd835eeaeb4c7794e7ac33aea714bbf.png) · [post_action](evidence/cd5fa896b6f7d616696ee877e626b44bf0cbfbba6584a34f28bf4650676af035.png) · [supporting](evidence/a5ba697ece39ba960fb21cfc34593ecafefdc8a059c2a405347176b48e932d78.txt) · [supporting](evidence/7a4870ad0db7bc6b220a327fe43d46195571982b10df737c47dd417a499930fe.txt) · [post_action](evidence/f82bf1e6a40739fae456d69aca7f7a16e11e05d8b886f641be584b2fd4cd8ecb.png) · [post_action](evidence/cd5fa896b6f7d616696ee877e626b44bf0cbfbba6584a34f28bf4650676af035.png) · [supporting](evidence/a5ba697ece39ba960fb21cfc34593ecafefdc8a059c2a405347176b48e932d78.txt) · [supporting](evidence/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.txt) · [supporting](evidence/58d68e7eecc7e36668622fe30a21874989649b3b592200951cda40e4a3a1adca.txt) · [post_action](evidence/9dbf38c45a25b1b3ecc9786fd83804309655e08b11b209ed7aea0ec706b1bdcf.png) · [supporting](evidence/cd5fa896b6f7d616696ee877e626b44bf0cbfbba6584a34f28bf4650676af035.png) · [supporting](evidence/a5ba697ece39ba960fb21cfc34593ecafefdc8a059c2a405347176b48e932d78.txt)
- CART-1_TC_012: pass — expected: ['move to cart adds and removes']; actual: Seed user, cart emptied, wishlist held W1 (in stock) and W0 (stock 0). Move to cart on W1: toast 'Moved to cart'; after reload the wishlist lists only W0; cart page lists W1 qty 1 (subtotal $10.00 at $10.00 each) and not W0. W0 row shows an Out of Stock badge; its Move to cart button is disabled (separate diagnostic attempt a9, not in the record: click refused as 'not enabled', cursor not-allowed). — [supporting](evidence/161312019d970d8b8711dbcc9cab050321950775c2eac687accfa885bb6a0770.png) · [pre_action](evidence/4aea8ba2847493a33f514e72a17cb574a222c486ea6202a7d3b318d8c7d9b240.png) · [supporting](evidence/1c4d0ebe3a39231f944a3ef3e2884c86e27c03c1ad1d7fd59407aa1e5da17035.txt) · [supporting](evidence/ab43e44c3771e87441e712d14ce80da631d7b81faa65b1ec56cbeb635dc03939.txt) · [post_action](evidence/62f16f2b0ca23210fd07c5612ea53af57ba7eafe66ec7c032b22cc5412dd758b.png) · [supporting](evidence/67bfd3b2934be70bc207c327a3beb4df231e0596c70f00a36a36c14cd4140f42.txt) · [supporting](evidence/09faefd9d9a6a494f4e0cc131dd9cd65ad99f4a51975f7621da34d1f7c426d4f.txt) · [supporting](evidence/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.txt) · [post_action](evidence/55499a13daa0ea54a2c6bae741bf57b762a26fb2e246bad83c18db00ed8a5d53.png) · [supporting](evidence/65d2ba9abbd7c88aebdc4ced3e12bc3664c1d3ec2be4e346088f61ef3b60b630.txt)

`delivery_ready: no`

**What blocks delivery on the product side**

- traceability: R-9 has no terminal outcome (no row of test-plan.md names this requirement)
- traceability: R-13 has no terminal outcome (no row of test-plan.md names this requirement)
- traceability: R-16 has no terminal outcome (no row of test-plan.md names this requirement)
- coverage: OB-1 — disabled buttons not covered (UI)
- coverage: OB-2 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-3 — none
- coverage: OB-4 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-5 — none
- coverage: OB-6 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-7 — none
- coverage: OB-8 — proves no persistent change, not that no write was attempted
- coverage: OB-9 — payment itself is out of scope
- coverage: OB-10 — detail-page and wishlist paths are manual-agent rows
