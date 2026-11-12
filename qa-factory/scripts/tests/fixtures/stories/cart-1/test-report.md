# CART-1 — test report


**The change.** CART-1 covers Add to Cart in MyBooks, checked against the current code: adding a book from the catalog or the detail page, stock limits, quantity and id validation, guest and account carts, merging the guest cart at sign-in, changing and removing cart items, the checkout quote and order reading the cart, and move-from-wishlist. No formal requirements exist; you ruled at gate A that the documented contract is the expected behaviour.

<!-- facts:verdict -->
**Verdict: not ready to ship as is.** Because TS-9 (CART-1_TC_009) failed in the run - the triage verdict is ASSERT_STRICTER. Product bugs: none recorded. Of 16 requirements: 0 proven by tests, 0 with a product bug, 16 not proven, 0 waiting for a person, 0 deferred by your decision. A person must check 0 cases; 0 cases are closed only partly. 0 green tests count as proven. 17 tests could not be verified by the code critic.

`delivery_ready: no — TS-9 (CART-1_TC_009) failed in the run - the triage verdict is ASSERT_STRICTER`
<!-- /facts:verdict -->

Notation: R-n — a requirement (the list with its text: understanding.md, "What we verify");
<case id> — a test case, its id in the form the project uses (test-plan.md, "Case appendix");
TS-n — a plan row; BUG-n — a bug file in `qa-factory/bugs/`.

<!-- facts:proven -->
## Proven — 0 green tests

No green test is counted as proven.

Changed after a red run, not in the list above (CART-1_TC_005): its expectation changed after a red run — no assertion changed; fixture guest/ownBooks jars start with an empty storageState (playwright.config preloads a saved bookstore_session_id so G1 and G2 shared one guest session (test defect); Then 3 value unchanged); recorded and judged: legitimate_correction.

Unknown which tests changed after a red run — a red run has no later pass for cart-quote-order.spec.@api @regression CART-1_TC_009 quote and order from cart, and the test file that would say whether the test still exists cannot be read (not a Python file, a syntax error, or no file named by the manifest).
<!-- /facts:proven -->


<!-- facts:manual-checks -->
## Checked by hand — 2 of 2

- **CART-1_TC_011** (R-1, R-2) — "P-valid: quantity 2 gives a success toast and the cart page lists D3 with quantity 2. / P-above-stock: quantity 4 (or a total of 2 + 4 above stock 3) gives an error toast and the cart page still shows D3 with quantity 2. / P-soldout: the add button for D0 is disabled and D0 is not in the cart." — before the change: not recorded by the requirements — now: Signed in as the seed user with an emptied cart. D3 (stock 3), qty 2, Add to Cart: toast '2 copies added to cart'; cart page lists D3 with subtotal $20.00 (2 x $10.00). D3 qty 4: error toast 'Only 3 in stock and 2 already in your cart'; cart page still shows D3 at $20.00 (qty 2). D0 (stock 0): stock badge and button label read 'Out of Stock', the button is labelled Out of Stock and D0 is absent from the final cart (only D3 listed); the disabled attribute read returned an empty string for both enabled and sold-out buttons, so the disabled state itself rests on the label and the page screenshot. · evidence/c29fe4ce9032e9f6aa7c0358f2824ed8dbd835eeaeb4c7794e7ac33aea714bbf.png — result: passed — before the action: evidence/8b1888b0ad54a18e12416fc24e07b3aa943421227bc84c60ccf7e1b5cc394d1d.png; after the action: evidence/c29fe4ce9032e9f6aa7c0358f2824ed8dbd835eeaeb4c7794e7ac33aea714bbf.png, evidence/cd5fa896b6f7d616696ee877e626b44bf0cbfbba6584a34f28bf4650676af035.png, evidence/f82bf1e6a40739fae456d69aca7f7a16e11e05d8b886f641be584b2fd4cd8ecb.png, evidence/9dbf38c45a25b1b3ecc9786fd83804309655e08b11b209ed7aea0ec706b1bdcf.png; also captured: evidence/161312019d970d8b8711dbcc9cab050321950775c2eac687accfa885bb6a0770.png, evidence/6ff3124b9bc32b454d08d251e8ed4265f7094435cfb2468ef5a9783ff8ab8930.txt, evidence/a5ba697ece39ba960fb21cfc34593ecafefdc8a059c2a405347176b48e932d78.txt, evidence/7a4870ad0db7bc6b220a327fe43d46195571982b10df737c47dd417a499930fe.txt, evidence/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.txt, evidence/58d68e7eecc7e36668622fe30a21874989649b3b592200951cda40e4a3a1adca.txt, evidence/cd5fa896b6f7d616696ee877e626b44bf0cbfbba6584a34f28bf4650676af035.png
- **CART-1_TC_012** (R-14) — "P-move: the cart page lists W1 with quantity 1 (one copy). / P-move: after reload W1 is no longer on the wishlist. / P-soldout: the move button of W0 is disabled and W0 is not in the cart." — before the change: not recorded by the requirements — now: Seed user, cart emptied, wishlist held W1 (in stock) and W0 (stock 0). Move to cart on W1: toast 'Moved to cart'; after reload the wishlist lists only W0; cart page lists W1 qty 1 (subtotal $10.00 at $10.00 each) and not W0. W0 row shows an Out of Stock badge; its Move to cart button is disabled (separate diagnostic attempt a9, not in the record: click refused as 'not enabled', cursor not-allowed). · evidence/62f16f2b0ca23210fd07c5612ea53af57ba7eafe66ec7c032b22cc5412dd758b.png — result: passed — before the action: evidence/4aea8ba2847493a33f514e72a17cb574a222c486ea6202a7d3b318d8c7d9b240.png; after the action: evidence/62f16f2b0ca23210fd07c5612ea53af57ba7eafe66ec7c032b22cc5412dd758b.png, evidence/55499a13daa0ea54a2c6bae741bf57b762a26fb2e246bad83c18db00ed8a5d53.png; also captured: evidence/161312019d970d8b8711dbcc9cab050321950775c2eac687accfa885bb6a0770.png, evidence/1c4d0ebe3a39231f944a3ef3e2884c86e27c03c1ad1d7fd59407aa1e5da17035.txt, evidence/ab43e44c3771e87441e712d14ce80da631d7b81faa65b1ec56cbeb635dc03939.txt, evidence/67bfd3b2934be70bc207c327a3beb4df231e0596c70f00a36a36c14cd4140f42.txt, evidence/09faefd9d9a6a494f4e0cc131dd9cd65ad99f4a51975f7621da34d1f7c426d4f.txt, evidence/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.txt, evidence/65d2ba9abbd7c88aebdc4ced3e12bc3664c1d3ec2be4e346088f61ef3b60b630.txt
<!-- /facts:manual-checks -->

<!-- facts:bugs -->
## Product bugs — 0 confirmed · 0 unconfirmed

None found (looked in the story's own bugs folder: no such folder; the project's bug folder (qa-factory/bugs): no such folder; unfiled drafts: 0 files).
<!-- /facts:bugs -->

<!-- facts:review-gaps -->
## Review gaps — 0 tests the code critic rejected

None: the code critic left no test rejected.
<!-- /facts:review-gaps -->

## Left with you

1. **Unknown or sold-out book is rejected (R-3, CART-1_TC_001).** To check: the Then: "HTTP 404 BOOK_NOT_FOUND for an unknown book, 400 OUT_OF_STOCK for stock 0", and no cart row is created. There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
2. **Add beyond stock is rejected (R-4, CART-1_TC_002).** To check: the Then: "a third add past the stock of 5 answers 400 INSUFFICIENT_STOCK" and the row stays at 5. There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
3. **Repeat add accumulates (R-5, CART-1_TC_003).** To check: the Then: "exactly one row for the book, quantity 3 (1 + 2)". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
4. **Invalid quantity or id gets a stable error (R-6, CART-1_TC_004).** To check: the Then: "quantity 1 and 999 accepted; 0, fraction, string, over-limit and bad ids give 4xx with error and code, never 5xx". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
5. **Guest cart is separate from the account cart (R-7, CART-1_TC_005).** To check: the Then: "the account and another guest never see the first guest cart rows". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
6. **Guest cart merges on sign-in (R-8, CART-1_TC_006).** To check: the Then: "the higher quantity wins, capped at stock, sold-out dropped, no session gives 401". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
7. **Update and delete a cart item (R-11, CART-1_TC_007).** To check: the Then: "PUT sets the quantity within stock, over stock gives 400, DELETE removes the row". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
8. **A foreign cart item cannot be changed (R-12, CART-1_TC_008).** To check: the Then: "PUT and DELETE on another owner item give 404 CART_ITEM_NOT_FOUND and that cart is unchanged". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
9. **Add from the catalog shows badge and cart page (R-1, R-2, R-10, CART-1_TC_010).** To check: the Then: "the badge equals the sum of quantities (1) and the cart page lists the book with quantity 1". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
10. **Quote and order from the cart (R-15, CART-1_TC_009).** To check: Then 2, "the quote lists B1 x2 and B2 x1". There is a test and it is red on that one assert (the other four pass). The quote prices the cart (200) and rejects an empty cart (400) but has no items array; R-15 and the documented Quote schema do not ask for one, and the same happens without this story's change. Needed: your decision. Answer wanted: remove that check from the test, or add the items array to the requirement.
   Your words at gate B: "CART-1_TC_009: open"
11. **Requirements with no case (R-9, R-13, R-16; no case id).** To check: guest cart after register then login (R-9, gate A question 2), NaN in the cart quantity box and unchecked fetches (R-13, question 3), concurrent add of the same book (R-16, question 4). There is no test: you answered "a" (in scope, a failure is a bug) at gate A, but the plan did not give them a case. Needed: plan cases for them, or a decision to defer.


<!-- facts:regression -->
### Regression to run (from the plan approved at gate A)

blast: none (current-code source, no diff). Existing defence: none in tests/ (grep cart: 0 hits).
- Application unit suite `MyBooks/src/lib/cartRules.test.ts`: `python "<path-2>/ai-packages/qa-factory/scripts/run_suite.py" --label cart -- npm --prefix ../MyBooks run test -- src/lib/cartRules.test.ts src/lib/validation/schemas.test.ts` (developer-owned, read only).
- For developers at component level: badge refresh, disabled out-of-stock buttons (TS-1 UI part), CartPage empty-input and failed-fetch handling.

<!-- qa-factory:case-appendix:start -->
<!-- /facts:regression -->

<!-- facts:open-questions -->
## Open questions — 4

```
po_ba · No requirement beyond two generic acceptance criteria exists; may the current code, docs/AUTH.md and the openapi summaries serve as the expected behaviour for the cart? (named in your gate A words; the factory recorded no answer)
po_ba · Should a guest cart survive registration followed by login, given RegisterPage never calls merge? (named in your gate A words; the factory recorded no answer)
dev_arch · What is expected on the cart page when the quantity input is emptied (NaN is sent) or the cart or book fetch fails? (named in your gate A words; the factory recorded no answer)
dev_arch · Is concurrent adding of the same book in scope, and what must hold (one row, quantity within stock)? (named in your gate A words; the factory recorded no answer)
```
<!-- /facts:open-questions -->

<!-- facts:skipped-by-plan -->
## Skipped by the plan (approved at gate A)

Nothing: the approved plan skipped no requirement.
<!-- /facts:skipped-by-plan -->

<!-- facts:not-proven -->
## Not proven, and what it costs

- **R-1** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it; server rule covered by TS-2 : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: seam @ BookCard to CartPage
- **R-2** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it; server rule covered by TS-2 : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: seam @ BookCard to CartPage
- **R-3** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: error-path @ cartService.addToCart
- **R-4** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: boundary @ cartRules.fitsInStock / addToCart
- **R-5** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: state @ cartService.addToCart
- **R-6** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: contract @ addToCartSchema
- **R-7** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: someone can reach what they must not, or be locked out of what they need; the plan's defect hypothesis: permission @ ownerWhere
- **R-8** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: data can be lost or corrupted in production; the plan's defect hypothesis: data-loss @ mergeGuestCart
- **R-9** — no plan row names this requirement and no reason is recorded : risk: not assessed at planning — no plan row
- **R-10** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: seam @ BookCard to CartPage
- **R-11** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: boundary @ updateCartItem
- **R-12** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: someone can reach what they must not, or be locked out of what they need; the plan's defect hypothesis: permission @ cart/[id] route
- **R-13** — no plan row names this requirement and no reason is recorded : risk: not assessed at planning — no plan row
- **R-14** — degraded impact does not earn e2e code : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: order @ WishlistPage.moveToCart
- **R-15** — red run, triaged ASSERT_STRICTER: no reason recorded; no bug, left with you : risk: money can be charged, paid or counted wrongly in production; the plan's defect hypothesis: seam @ orderService and cart
- **R-16** — no plan row names this requirement and no reason is recorded : risk: not assessed at planning — no plan row
<!-- /facts:not-proven -->

<!-- facts:gate-a -->
## Decided at gate A

```
Test it as one story.
Q1: a (but if the code does not let a user do the intended action, or has any other error that contradicts the application's logic, that is a bug)
Q2: a
Q3: a
Q4: a
Uncommitted changes: go on on this branch.
The application is not in a container: MyBooks runs as a local node process (npm run start in ../MyBooks, port 3000); docker holds only the database and Mailpit. The story has no code changes, so there is nothing to compare.
For the user: use EMAIL_USER / EMAIL_PASS, they are this project's user keys.
Values are set in .env now, rehearse again.
TS-10: automate it
approve
```
Your words here name Q1, but no answer to it is recorded, so it stays under Open questions.
Your words here name Q2, but no answer to it is recorded, so it stays under Open questions.
Your words here name Q3, but no answer to it is recorded, so it stays under Open questions.
Your words here name Q4, but no answer to it is recorded, so it stays under Open questions.
- S4 · vcs-1: "Uncommitted changes: go on on this branch."
- S4 · s5_runtime_probe-1: "The application is not in a container: MyBooks runs as a local node process (npm run start in ../MyBooks, port 3000); docker holds only the database and Mailpit. The story has no code changes, so there is nothing to compare."
<!-- /facts:gate-a -->



<!-- facts:gate-b -->
## Decided at gate B

```
No MR needed, otherwise continue with what we have. (original: MR ne nado v ostalnom prodolzhai s tem chto est)
deliver with known gaps: the person chose to continue with what exists (R-9, R-13, R-16 stay without cases).
CART-1_TC_009: open
```
- Your words name CART-1_TC_009: "CART-1_TC_009: open"
- Bugs: none recorded.
- What went outward: not recorded
<!-- /facts:gate-b -->

## Factory defects — nothing is wanted from you

The factory's probe tool, which checks that a test's assertion fails when it should, cannot read this project's Playwright TypeScript tests, so none of the nine green automated tests could be verified by the code critic. That is why they stand under Left with you and not under Proven; it is the factory's gap, not a product finding.

The coverage check also lists obligations as unverified because it counts those same unverified tests and the three requirements the plan left without a case; those lines repeat the items above. Data left on the stand by the manual checks: books 110 to 113, a wishlist entry and a cart row.

<!-- facts:size -->
## Size

Forecast: **XXL** — the requirements weigh 32 (each weighted by its priority and area); the XXL cap is 28.
Fact: **XXL** — 13 testable requirements, 12 plan rows, 12 cases, 18 tests.
Difference: none.
<!-- /facts:size -->

<!-- facts:where-to-look -->
## Where to look

- understanding.md — sections: Why this change; Size; What we verify; What we do not verify, and why; What else the change may touch; Questions without which testing is pointless
- test-plan.md — sections: Plan; Not planned; Budget; Recommended regression; Case appendix; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage; Given; When; Then; Self-probe notes; Obligation coverage
- retro.md — sections: What went wrong and what to change; Time; Cost; Marathons and what they spent turns on; Gate-A disposition overrides; Estimate vs actual; What happened to the process; The human's answer; Routed out of the story
- the appendix below — every requirement, case and test with its result
- config.json: not reverted: another story of this project is still in flight (ADD-TO-CART), and a revert now could undo or restore its changes; config.json was left as it is. If ADD-TO-CART is abandoned, archive it (archive_task.py) so the next story's revert is not held back by it
- the factory's own signals during this run: 1 (exit_gate_note ×1) - the whole list: the journal <path-1>\test-automation-framework\qa-factory\records\journal.jsonl, event hook_signal
<!-- /facts:where-to-look -->

## Appendix — traceability

Sorted by requirement, then by case. Result vocabulary: **pass** · **BUG-n** · **wait** (the case is handed to a person) · **blocked** (the stand) · **not run** · **unreachable** (the scenario cannot occur in the product) · **deferred** (a recorded decision) · **not planned**. Level: unit · component · api · integration · e2e-ui · manual-agent · manual-human. Shape: new · extend · reuse · parameterize · consolidate.

Test files: **S** = `tests/e2e/cart/add-to-cart.spec.ts`, **R** = `tests/api/cart/add-rejections.spec.ts`, **L** = `tests/api/cart/add-stock-limit.spec.ts`, **A** = `tests/api/cart/add-accumulate.spec.ts`, **B** = `tests/api/cart/add-boundaries.spec.ts`, **I** = `tests/api/cart/cart-isolation.spec.ts`, **M** = `tests/api/cart/cart-merge.spec.ts`, **D** = `tests/api/cart/cart-update-delete.spec.ts`, **O** = `tests/api/cart/cart-ownership.spec.ts`, **Q** = `tests/api/cart/cart-quote-order.spec.ts`.

| R | What we verify | TC · Then | Test | Level · shape | Result | Basis |
|:--|:--|:--|:--|:--|:--|:--|
| R-1 | A signed-in shopper adds a book from the catalog card and sees it in the badge ... | CART-1_TC_010<br>Then 1–3 | S `..atalog shows badge and cart page` | e2e-ui<br>new | **pass** | the code critic could not verify it |
| R-1 | Book detail page adds the chosen quantity and handles above-stock and ... | CART-1_TC_011 | — | e2e-ui | **not run** | server rule covered by TS-2 |
| R-2 | A signed-in shopper adds a book from the catalog card and sees it in the badge ... | CART-1_TC_010<br>Then 1–3 | S `..atalog shows badge and cart page` | e2e-ui<br>new | **pass** | the code critic could not verify it |
| R-2 | Book detail page adds the chosen quantity and handles above-stock and ... | CART-1_TC_011 | — | e2e-ui | **not run** | server rule covered by TS-2 |
| R-3 | Adding an unknown book or a book with stock 0 to the cart is rejected with the ... | CART-1_TC_001<br>Then 1–3 | R `..nknown or sold-out book rejected` | api<br>new | **pass** | the code critic could not verify it |
| R-4 | Cart quantity never exceeds stock: equal to stock is accepted, one more is ... | CART-1_TC_002<br>Then 1–4 | L `..002 add beyond stock rejected` | api<br>new | **pass** | the code critic could not verify it |
| R-5 | Adding a book already in the cart increments the one existing row | CART-1_TC_003<br>Then 1–2 | A `..TC_`<br>`003 repeat add accumulates` | api<br>new | **pass** | the code critic could not verify it |
| R-6 | Add to cart validates quantity 1..999 and positive integer bookId with a stable ... | CART-1_TC_004<br>Then 1 | B `..TC_`<br>`004 quantity accepted` [P-qty-min, P-qty-max] | api<br>parameterize | **pass** | the code critic could not verify it |
| R-6 | Add to cart validates quantity 1..999 and positive integer bookId with a stable ... | CART-1_TC_004<br>Then 2–4 | B `..jected with a stable error shape` [7 variants] | api<br>parameterize | **pass** | the code critic could not verify it |
| R-7 | A guest cookie cart is separate from the signed-in account cart and from other ... | CART-1_TC_005<br>Then 1–3 | I `..05 cart isolation between owners` | api<br>new | **pass** | the code critic could not verify it |
| R-8 | Guest cart merge keeps the higher quantity, caps at stock and drops stock 0 rows | CART-1_TC_006<br>Then 1–6 | M `..006 guest cart merge on login` | api<br>new | **pass** | the code critic could not verify it |
| R-9 | Registration does not call merge and does not sign in; what happens to the ... | — | — | — | **not planned** | no plan row names this requirement and no reason is recorded |
| R-10 | A signed-in shopper adds a book from the catalog card and sees it in the badge ... | CART-1_TC_010<br>Then 1–3 | S `..atalog shows badge and cart page` | e2e-ui<br>new | **pass** | the code critic could not verify it |
| R-11 | Changing a cart quantity sets it within stock, rejects above stock, and ... | CART-1_TC_007<br>Then 1–4 | D `..007 update and delete cart item` | api<br>new | **pass** | the code critic could not verify it |
| R-12 | Another owner's cart item cannot be changed or removed and the owner's cart ... | CART-1_TC_008<br>Then 1–5 | O `..oreign cart item mutation denied` | api<br>new | **pass** | the code critic could not verify it |
| R-13 | Cart page with an emptied quantity input or a failed cart/book fetch: expected ... | — | — | — | **not planned** | no plan row names this requirement and no reason is recorded |
| R-14 | Wishlist move to cart adds one copy to the cart and removes the wishlist item | CART-1_TC_012 | — | e2e-ui | **not run** | degraded impact does not earn e2e code |
| R-15 | Checkout quote reads the owner's cart and a successful order clears it | CART-1_TC_009<br>Then 1–5 | Q `..009 quote and order from cart` | api<br>new | **blocked** | red run, triaged ASSERT_STRICTER: no reason recorded; no bug, left with you |
| R-16 | Concurrent adds of the same book must not create duplicate rows or exceed stock ... | — | — | — | **not planned** | no plan row names this requirement and no reason is recorded |
