# Critic findings - window 7 (S5-qa-code-critic-10) - LOCAL-1_TC_018, LOCAL-1_TC_019

Read in full: tests/e2e/cart/cart.spec.ts (lines 1-40, 320-425), core/pages/HomePage.ts, WishlistPage.ts, CartPage.ts, BookDetailPage.ts. Run report: evidence/runs/70c64e53d871768835c5 (TC_018 x3), evidence/runs/6be0653c44bf5bc1f2d4 (TC_019).

## Roll-call (case -> instance)
- LOCAL-1_TC_018 -> add_path_obeys_the_add_rules[product_page], [catalog_card], [wishlist_move] (parameterize; Thens 1-4 each)
- LOCAL-1_TC_019 -> the catalog card adds the book to the cart with the right line (Thens 1-2)

## Thens independent of the price assert (conductor question)
Every assert after the first action is `expect.soft`; the unit-price assert (line 395 / 421) is last. `run_suite --detail` for [wishlist_move] shows exactly one error (the price assert, Expected 17.35, Received undefined) and Playwright reports every failed soft assert, so Thens 2 (370), 4 (383) and 3 (391-392) ran and held on all three paths. Same for TC_019: only the price assert (421) failed. Per-Then green is therefore proven by the single-error report, not by per-Then rows.

## TC_019 Then 2
Asserts badge '1' (415) and line quantity 1 (417). Q6 = a ("the behaviour now is intended") was answered at gate A and by the person's word; the literal comes from that answer, not the code. Matches the case. Note CC-2: a card adding 2 copies would also fail 417, so the quantity is covered.

## Findings
- F-1 [mechanical, non-blocking] cart.spec.ts:389 `page.waitForLoadState('networkidle')` after the out-of-stock add: a wait on idle network, not on a state, and sits in the test body (core should wrap it). Replace with a condition (the refusal mark visible or the cart read polled via expect.poll). cause: mechanical.
- F-2 [note, no cause] wishlist_move is never the second path (otherPath maps it to product_page), so Then 4 "different path sums into one line" is checked for wishlist as first add only. Within the case wording; no action.
- F-3 [note, no cause] assertion_id on the TC_018 rows is :391 while the red line is :395; then_bindings carry the correct refs (395, 370, 391, 383). Bookkeeping only.

## Product red (not a test defect)
Unit price: cart line carries no price field (R-19, contradicts_requirement, same defect as TC_001/004). Left red for S7. Level matches S3 (e2e-ui); oracle P is the catalog price read via API (requirement), no invented value.

## Probe
None run: person's word "probe gap tooling:typescript" (not receipted). critic_verdict approved on the 4 rows (static review; red is the product defect); sensitivity_proof_missing_reason already on the rows.

## Manifest check
32 test rows, all with case/file/status, 32 with critic_verdict (17 approved, 1 approved_with_fixes, 14 unverified). CAUTION: after manifest_put the manifest holds then_bindings only for TC_018/TC_019 (14 rows); earlier windows' then_bindings (TC_001-017) are absent from the manifest although their fragments carried them. I cannot tell whether they were lost before this dispatch or by the merge's "instance rows retracted into their current spelling" note; the conductor/author should re-send them (frag-w2..w9, frag-w9-restore).
