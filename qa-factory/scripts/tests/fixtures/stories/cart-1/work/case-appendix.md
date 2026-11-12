## Case appendix

| Case | Plan row | Oracle/basis | Channel | Review status | Version |
|---|---|---|---|---|---|
| CART-1_TC_001 | TS-1 | requirement:R-3 | auto | Draft | cv_4752342fab279cf316cc |
| CART-1_TC_002 | TS-2 | requirement:R-4 | auto | Draft | cv_aaed235e685cdb6d3318 |
| CART-1_TC_003 | TS-3 | requirement:R-5 | auto | Draft | cv_0f8aaebc21c72b94456c |
| CART-1_TC_004 | TS-4 | requirement:R-6 | auto | Draft | cv_59c8d14f1852702b39cb |
| CART-1_TC_005 | TS-5 | requirement:R-7 | auto | Draft | cv_3767896d512c623e0b59 |
| CART-1_TC_006 | TS-6 | requirement:R-8 | auto | Draft | cv_3736b2c697846070acdd |
| CART-1_TC_007 | TS-7 | requirement:R-11 | auto | Draft | cv_2d9d27c7521bc3c4edcf |
| CART-1_TC_008 | TS-8 | requirement:R-12 | auto | Draft | cv_ce42982f1616cbc645f9 |
| CART-1_TC_009 | TS-9 | requirement:R-15 | auto | Draft | cv_2b3ebd621560f9547704 |
| CART-1_TC_010 | TS-10 | requirement:R-1 | auto | Draft | cv_514d05efe43b2506bb5f |
| CART-1_TC_011 | TS-11 | requirement:R-1 | manual-agent | Draft | cv_de13157c14b004fc1bbd |
| CART-1_TC_012 | TS-12 | requirement:R-14 | manual-agent | Draft | cv_8ad20339348408e4f727 |

Cases: 12. Generated from pinned case content; do not edit this section by hand.

### CART-1_TC_001 — cv_4752342fab279cf316cc

Requirements: R-3
Plan row: TS-1

Obligation: OB-1

## Given
- A guest session (fresh cookie jar) with no cart rows.
- Own book S0 with stock 0 (marker in its title); a bookId that does not exist (larger than any existing id).

## When
1. POST /api/cart { bookId: <nonexistent id>, quantity: 1 } (partition P-unknown).
2. POST /api/cart { bookId: S0, quantity: 1 } (partition P-soldout).

## Then
1. P-unknown: HTTP 404 with body code BOOK_NOT_FOUND (body has error and code).
2. P-soldout: HTTP 400 with body code OUT_OF_STOCK.
3. Independent read: GET /api/cart in the same cookie jar returns no row for S0 and no row for the nonexistent id (read through the cart list, not the POST response).

## Self-probe notes
- Discriminating input: two distinct partitions (unknown vs stock 0) so a swapped code is seen; Then 3 reads state through GET /api/cart, not the trigger response.
- Axis and oracle: R-3 (current-code derived, Q1 open: failure is a finding to confirm). Fixture does not precompute the result; the own book is seeded with stock 0 directly.
- Negative proof bounded: only this case's cookie jar is read; no global count asserted (data_cleanup not probed).
- Gap: disabled UI buttons for stock 0 not covered (recommended regression, component level).

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-1 unknown book | R-3 | HTTP response of POST /api/cart | Then 1, 3 | none |
| OB-1 stock 0 | R-3 | HTTP response of POST /api/cart | Then 2, 3 | disabled buttons (UI) not covered |

### CART-1_TC_002 — cv_aaed235e685cdb6d3318

Requirements: R-4
Plan row: TS-2

Obligation: OB-2

## Given
- Guest cookie jar, empty cart. Own book B with stock 5.

## When
1. POST /api/cart { bookId: B, quantity: 3 }.
2. POST /api/cart { bookId: B, quantity: 2 } (3 + 2 = stock) (partition P-equal).
3. POST /api/cart { bookId: B, quantity: 1 } (5 + 1 = stock + 1) (partition P-plus-one).
4. GET /api/cart.

## Then
1. P-equal: the second add (to exactly stock) succeeds with a 2xx status.
2. P-plus-one: the third add answers HTTP 400 with code INSUFFICIENT_STOCK.
3. GET /api/cart shows exactly one row for B with quantity 5 (not 6).
4. The row quantity read in Then 3 equals the stock of B (5) after the rejected add, so the rejected request changed nothing.

## Self-probe notes
- Discriminating input: existing in-cart rows (3) make the check depend on persisted inCart, not only the added amount; boundary pair equal / plus one.
- Then 3 and 4 read via GET /api/cart, independent of the POST responses. Oracle R-4; Q1 open.
- Negative bounded by reading the case's own cart after the rejected add; completion = third response received.
- CAND-1 (unit, partial) is not duplicated: it proves only the pure function.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-2 equal to stock allowed | R-4 | POST response + cart read-back | Then 1, 3 | none |
| OB-2 stock + 1 rejected | R-4 | POST response + cart read-back | Then 2, 4 | none |

### CART-1_TC_003 — cv_0f8aaebc21c72b94456c

Requirements: R-5
Plan row: TS-3

Obligation: OB-3

## Given
- Guest cookie jar, empty cart. Own book B with stock 10.

## When
1. POST /api/cart { bookId: B, quantity: 1 }.
2. POST /api/cart { bookId: B, quantity: 2 }.
3. GET /api/cart.

## Then
1. GET /api/cart contains exactly one row for B (no second row).
2. That row has quantity 3 (1 + 2: added, not replaced).

## Self-probe notes
- Discriminating input: distinct quantities 1 and 2 so replace (2), sum (3) and duplicate rows are all told apart.
- Reads through GET /api/cart after both adds respond. Oracle R-5 (openapi summary); Q1 open.
- Rows counted only for B in this case's own jar.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-3 one row | R-5 | GET /api/cart | Then 1 | none |
| OB-3 quantity accumulates | R-5 | GET /api/cart | Then 2 | none |

### CART-1_TC_004 — cv_59c8d14f1852702b39cb

Requirements: R-6
Plan row: TS-4

Obligation: OB-4

## Given
- Guest cookie jar, empty cart. Own book B with stock 1000.

## When
Each partition is a separate POST /api/cart in a fresh cookie jar:
- P-qty-min: quantity 1. P-qty-max: quantity 999.
- P-qty-over: quantity 1000. P-qty-zero: quantity 0. P-qty-fraction: quantity 1.5. P-qty-string: quantity "abc".
- P-id-zero: bookId 0. P-id-negative: bookId -1. P-id-fraction: bookId 1.5.

## Then
1. P-qty-min and P-qty-max: 2xx; GET /api/cart in that jar shows B with quantity 1 and 999 respectively.
2. P-qty-over, P-qty-zero, P-qty-fraction, P-qty-string: a 4xx rejection (never 5xx), not a 2xx.
3. P-id-zero, P-id-negative, P-id-fraction: a 4xx rejection (never 5xx).
4. Every rejection body contains both `error` and `code` fields, and GET /api/cart in that jar has no row created by the rejected request.

## Self-probe notes
- Boundary pairs 1/999/1000/0 plus type partitions; the cart read-back catches a rejection that still wrote.
- Only the shape (4xx, fields error and code) is asserted; the exact validation code string is not stated by a requirement and is not asserted (register R-6 unknown noted in plan).
- CAND-2 unread: remains a visible gap at Gate A.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-4 quantity boundaries | R-6 | POST status/body + cart read | Then 1, 2, 4 | exact code string not asserted |
| OB-4 bookId validity | R-6 | POST status/body | Then 3, 4 | CAND-2 unread |

### CART-1_TC_005 — cv_3767896d512c623e0b59

Requirements: R-7
Plan row: TS-5

Obligation: OB-5

## Given
- Own book B (stock 5). Own user U (registered by the case). Guest G1 and a second guest G2, each with its own cookie jar (cookie bookstore_session_id).
- Jar JU is the "guest then sign-in" browser: it holds G1's bookstore_session_id cookie (copied from G1's jar after the add) AND U's auth session cookie after U signs in. Its sessionId cookie value equals G1's, asserted before the read.

## When
1. G1: POST /api/cart { bookId: B, quantity: 2 }.
2. G1: GET /api/cart.
3. Build JU: send G1's bookstore_session_id cookie, sign in as U (login) in that same jar; confirm JU still carries G1's cookie value. Do not call merge.
4. JU (signed in as U, G1's cookie sent): GET /api/cart.
5. G2: GET /api/cart.

## Then
1. Control: G1's GET /api/cart lists B with quantity 2 (the guest sees its own row).
2. P-user: JU's GET /api/cart payload (request carrying both U's session and G1's guest cookie) contains no row for B and none of G1's rows (payload inspected directly; a user-owner query that also matches the guest sessionId would return B x2 here).
3. P-other-guest: G2's GET /api/cart payload contains no row for B and none of G1's rows (payload inspected directly).

## Self-probe notes
- Then 1 is the positive control: without it an empty foreign read could come from a failed add. Foreign Thens inspect the payload rows, not just status.
- Completion: the G1 add has responded before the foreign reads. Oracle R-7 (+ AUTH.md); Q1 open.
- Data is unique to this case (own book); the check is "no row for B", not a global count.
- Seeded defect (owner query for a signed-in user also matching sessionId, cartOwner.ts ownerWhere): caught because JU sends G1's cookie with U's session, so Then 2 returns B x2 and fails. Proof kind: design_analysis, no probe executed. Round 2 repair of critic F-1.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-5 guest sees own row | R-7 | GET /api/cart per jar | Then 1 | none |
| OB-5 account does not see guest rows | R-7 | GET /api/cart payload as U | Then 2 | none |
| OB-5 other guest does not see them | R-7 | GET /api/cart payload as G2 | Then 3 | none |

### CART-1_TC_006 — cv_3736b2c697846070acdd

Requirements: R-8
Plan row: TS-6

Obligation: OB-6

## Given
- Own user U (registered, own cookie jar, signed in). Guest jar G.
- Own books, all created with stock 10: B1, B2, B3, B4, B5.
- U's cart already holds: B1 x5, B2 x1.
- G's cart holds: B1 x2, B2 x4, B3 x6, B4 x1, B5 x2 (all added while stock is 10). Then, through the test seed endpoint (x-test-secret from TEST_SECRET, PC-2), B3 stock is lowered from 10 to 3 and B4 stock from 10 to 0.
  Note: if the seed endpoint cannot lower stock, the case is `blocked_by_env`.

## When
1. Call POST /api/cart/merge with U's session and the guest cookie of G.
2. GET /api/cart as U.
3. POST /api/cart/merge with no session (guest only).

## Then
1. P-overlap-higher-guest: B2 in U's cart has quantity 4 (guest 4 over user 1: max, not sum 5).
2. P-overlap-higher-user: B1 in U's cart has quantity 5 (user 5 over guest 2: max, not sum 7).
3. P-cap: B3 in U's cart has quantity 3 (guest 6 capped at stock 3).
4. P-soldout: U's cart has no row for B4.
5. P-disjoint: B5 is in U's cart with quantity 2; U's cart contains exactly the rows B1 x5, B2 x4, B3 x3, B5 x2 (and no row for B4).
6. P-unauth: the merge without a session answers 401.

## Self-probe notes
- Data distinguishes max from sum from replace in both directions; the stock cap and drop are separate partitions.
- Read-back is a fresh GET /api/cart as U, independent of the merge response; completion = merge responded before the read.
- Seed is not precomputed: stock changes are applied after the guest rows exist, so the merge, not the add path, enforces the cap.
- CAND-1 only proves arithmetic; transaction and persistence are what this case defends.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-6 higher quantity not sum | R-8 | merge then GET /api/cart | Then 1, 2 | none |
| OB-6 cap at stock | R-8 | merge then GET /api/cart | Then 3 | none |
| OB-6 stock 0 dropped | R-8 | merge then GET /api/cart | Then 4 | none |
| OB-6 disjoint kept | R-8 | merge then GET /api/cart | Then 5 | none |
| OB-6 auth | R-8 | merge response | Then 6 | none |

### CART-1_TC_007 — cv_2d9d27c7521bc3c4edcf

Requirements: R-11
Plan row: TS-7

Obligation: OB-7

## Given
- Guest jar with cart row for own book B (stock 5), quantity 1; the row id is read from GET /api/cart.

## When
1. PUT /api/cart/<row id> { quantity: 5 } (partition P-set-equal).
2. GET /api/cart.
3. PUT /api/cart/<row id> { quantity: 6 } (partition P-over).
4. GET /api/cart.
5. DELETE /api/cart/<row id> (partition P-delete).
6. GET /api/cart.

## Then
1. P-set-equal: PUT succeeds (2xx) and the read-back row for B has quantity 5 (set, not added to 1).
2. P-over: PUT answers 400 INSUFFICIENT_STOCK.
3. After P-over the read-back row for B still has quantity 5.
4. P-delete: DELETE succeeds and the final GET /api/cart has no row for B.

## Self-probe notes
- Boundary pair stock / stock+1; start quantity 1 distinguishes set from add (1+5 would be 6).
- All state Thens read via GET /api/cart, not the PUT/DELETE response. Oracle R-11; Q1 open.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-7 set within stock | R-11 | PUT + GET | Then 1 | none |
| OB-7 above stock rejected | R-11 | PUT + GET | Then 2, 3 | none |
| OB-7 delete | R-11 | DELETE + GET | Then 4 | none |

### CART-1_TC_008 — cv_ce42982f1616cbc645f9

Requirements: R-12
Plan row: TS-8

Obligation: OB-8

## Given
- Own book K (stock 10). Users A and B, each signed in in its own cookie jar. A's cart holds K x2; its row id R_A is read from A's GET /api/cart.

## When
1. (before_read) GET /api/cart as A; record the rows.
2. (action) As B: PUT /api/cart/R_A { quantity: 7 }; then DELETE /api/cart/R_A.
3. (completion) Both foreign responses received.
4. (after_read) GET /api/cart as A.
5. (control) As A: PUT /api/cart/R_A { quantity: 3 } and GET /api/cart as A.

## Then
1. Foreign PUT answers HTTP 404 with code CART_ITEM_NOT_FOUND.
2. Foreign DELETE answers HTTP 404 with code CART_ITEM_NOT_FOUND.
3. A's after_read rows are identical to the before_read rows (row R_A for K, quantity 2); mutable entity checked: CartItem only.
4. Positive control: A's own PUT succeeds and the next read shows K with quantity 3, proving R_A is reachable and mutable by its owner (so the 404s and the unchanged state are not an artifact of an unreachable id).
5. B's own GET /api/cart payload has no row for K.

## Self-probe notes
- Before/after read brackets the foreign action; positive control and reachability prevent a vacuous pass. This proves no persistent change, not that no write was attempted (no instrumentation).
- Quantity 7 is within stock so a missing owner check would visibly change the row. Oracle R-12; Q1 open.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-8 foreign PUT 404 | R-12 | PUT response | Then 1 | none |
| OB-8 foreign DELETE 404 | R-12 | DELETE response | Then 2 | none |
| OB-8 owner cart unchanged | R-12 | A's GET before/after | Then 3, 5 | no attempted-write claim |
| OB-8 reachability control | R-12 | A's PUT + GET | Then 4 | none |

### CART-1_TC_009 — cv_2b3ebd621560f9547704

Requirements: R-15
Plan row: TS-9

Obligation: OB-9

## Given
- The seeded verified user U signed in in a cookie jar with an empty cart (cleared first through DELETE of its own rows). Own books B1 and B2 (stock 5).

## When
1. P-empty: POST /api/checkout/quote as U with the empty cart.
2. Add B1 x2 and B2 x1 via POST /api/cart; POST /api/checkout/quote (P-quote).
3. Lower B1 stock to 1 through the test seed endpoint (x-test-secret from TEST_SECRET), POST /api/checkout/quote (P-overstock).
4. Restore B1 stock to 5, POST /api/orders as U with the mock card (P-order).
5. GET /api/cart as U.

## Then
1. P-empty: the quote answers 400/409/422 (not 401, 404 or 5xx) with a JSON body carrying `error` and `code`, and issues no quote (no quote items in the body). The signed-in session is proven by Then 2 succeeding on the same jar and path.
2. P-quote: the quote lists B1 x2 and B2 x1 (items and quantities read from the quote body match the cart read from GET /api/cart).
3. P-overstock: the quote answers 400/409/422 (not 401, 404 or 5xx) with a JSON body carrying `error` and `code`, and the body or message identifies B1 (the item above stock); no quote items are issued. Exact code value is not asserted (Q1).
4. P-order: the order succeeds (2xx) with items B1 x2 and B2 x1.
5. After the order GET /api/cart as U has no row for B1 or B2 (cart cleared).

## Self-probe notes
- The quote content is compared with the cart read through GET /api/cart, not computed from the quote itself; no price is hard-coded.
- Rejection status classes only: exact codes are not given by a requirement (Q1). Payment itself is out of scope.
- Paths are pinned: POST /api/checkout/quote (signed-in, route.ts:11) and POST /api/orders (verified user, route.ts:47); body fields come from spec.ts:576. PC-1 is the credentials_by_role key `user` (USER_EMAIL/USER_PASSWORD, seed user, assumed verified; S5 confirms on first login). PC-3 covers the seed secret.
- Four partitions share one cart by design (empty, quote, over-stock, order+clear); each is a named P- partition. Status-class assertions are bounded by the 4xx set and error/code shape, not any 4xx.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-9 empty/over-stock rejected | R-15 | quote responses | Then 1, 3 | exact codes not asserted |
| OB-9 quote reads cart | R-15 | quote body vs cart read | Then 2 | none |
| OB-9 order clears cart | R-15 | order response + GET /api/cart | Then 4, 5 | payment out of scope |

### CART-1_TC_010 — cv_514d05efe43b2506bb5f

Requirements: R-1, R-2, R-10
Plan row: TS-10

Obligation: OB-10

## Given
- Seed user U signed in through the UI, cart emptied through the API first. Own book B (stock 5, unique title) is listed in the catalog.

## When
1. Open the catalog and locate the card of B.
2. Click its add-to-cart-button once.
3. Wait for the add call response (completion).
4. Read the cart badge, then open the cart page.

## Then
1. The add call for B completes successfully (2xx) after the click.
2. The cart badge text equals the sum of quantities in the cart, 1.
3. The cart page lists B (by its unique title) with quantity 1; the content, not just the page visibility, is asserted.

## Self-probe notes
- Badge value is cross-read against the cart page rows, an independent channel. Cart cleaned first so the sum is not inherited from other data; rows read only for B's title.
- Oracle R-1 / R-10 / R-2 (current-code derived, Q1 open). Detail-page and wishlist paths are manual rows TS-11, TS-12.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-10 card add succeeds | R-1 | add call response | Then 1 | detail page, wishlist in TS-11, TS-12 |
| OB-10 badge sum | R-10 | UI badge | Then 2 | refresh on session change not covered |
| OB-10 cart page content | R-2 | cart page rows | Then 3 | none |

### CART-1_TC_011 — cv_de13157c14b004fc1bbd

Requirements: R-1, R-2
Plan row: TS-11

Obligation: OB-11
Evidence policy: ui. Required evidence: before and after screenshots of each partition, the actual steps taken, the final state read from the cart page. Completion condition: the toast is shown or the disabled button state is read. Missing required evidence is `inconclusive`, never pass.

## Given
- Seed user U signed in, cart empty. Own book D3 (stock 3) and own book D0 (stock 0).

## When
1. Open the detail page of D3 (before screenshot); set quantity 2; click add to cart (after screenshot, toast).
2. Open the cart page and read the rows.
3. On D3 set quantity 4 (above stock) and click add (screenshot, toast).
4. Re-read the cart page.
5. Open the detail page of D0 (screenshot of the button state).

## Then
1. P-valid: quantity 2 gives a success toast and the cart page lists D3 with quantity 2.
2. P-above-stock: quantity 4 (or a total of 2 + 4 above stock 3) gives an error toast and the cart page still shows D3 with quantity 2.
3. P-soldout: the add button for D0 is disabled and D0 is not in the cart.

## Self-probe notes
- Cart page read-back is the independent channel for each Then; the toast is only the trigger side. Evidence policy copied from the plan (ui, before/after).
- Boundary above stock is also defended at API level by CART-1_TC_002; this case is the UI path only.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-11 quantity add | R-1 | page UI + cart page | Then 1; screenshots + steps | not repeatable |
| OB-11 above stock | R-2 | toast + cart page | Then 2; screenshots + steps | not repeatable |
| OB-11 stock 0 | R-3 | button state | Then 3; screenshot | not repeatable |

### CART-1_TC_012 — cv_8ad20339348408e4f727

Requirements: R-14
Plan row: TS-12

Obligation: OB-12
Evidence policy: ui. Required evidence: before and after screenshots of the wishlist and cart pages plus the actual steps. Completion condition: the wishlist item is gone after the move. Missing required evidence is `inconclusive`, never pass.

## Given
- Seed user U signed in, cart empty. Wishlist holds own in-stock book W1 and own stock-0 book W0.

## When
1. Open the wishlist page (before screenshot).
2. Click move to cart for W1.
3. Reload the wishlist page and open the cart page (after screenshots).
4. Look at the move button of W0.

## Then
1. P-move: the cart page lists W1 with quantity 1 (one copy).
2. P-move: after reload W1 is no longer on the wishlist.
3. P-soldout: the move button of W0 is disabled and W0 is not in the cart.

## Self-probe notes
- Both lists are re-read after reload (independent of the click feedback). A failed wishlist removal is not forced (expected behavior unstated; plan unknown), so that part stays a named gap.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-12 add one copy | R-14 | cart page | Then 1; screenshots + steps | none |
| OB-12 wishlist removal | R-14 | wishlist page | Then 2; screenshots | failed removal not forced |
| OB-12 stock 0 | R-14 | button state | Then 3; screenshot | none |

