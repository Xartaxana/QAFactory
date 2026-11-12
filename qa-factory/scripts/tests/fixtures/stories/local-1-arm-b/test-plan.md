---
task: LOCAL-1
created: 2026-11-05
rows_total: 20
candidates: 20
planned: 20
---

# Test plan - LOCAL-1 (add to cart and the cart, grounded on current code)

Pyramid: unit 0 · api 7 · e2e-ui 10 automated + 3 walked by the agent. Budget: 20 rows against a ceiling of 28 (size L), inside it.

Two open questions are marked "until answered": Q3 (TS-4, the move onto an item already in the cart) and Q2 (TS-12, PUT or PATCH for the quantity update). One question is new (TS-6, what the shopper gets when the merge fails at sign-in); the code contradicts R-12 there, so TS-6 is an expected red and both readings go to gate A. Rows with less depth: R-8 (one extra instance), R-6, R-10 (partitions only). Rows whose requirement the register derived from the code alone (R-9, R-11, R-12, R-13, R-14) carry no oracle of their own; their expected values are the stated norm, confirmed with the person.

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | Add from a catalog card: success message, badge moves; short stock is an error (walk: Add from the catalog) | R-1 | state @ HomePage.tsx:118 add handler | blocked-flow | P1 | expected-contract:work/requirements-register.md:13 | requirement:R-1 | `automate` - regression: yes, main path | new | e2e-ui | smoke |
| TS-2 | Add from the book page: message differs above 1, out-of-stock button unusable (walk: Add from the book page) | R-2 | boundary @ BookDetailPage.tsx:45 quantity handler | blocked-flow | P1 | expected-contract:work/requirements-register.md:14 | requirement:R-2 | `automate` - regression: yes | new | e2e-ui | equivalence partitioning |
| TS-3 | Move to cart: added with quantity 1, removed from the wishlist (walk: Move from the wishlist) | R-3 | state @ WishlistPage.tsx:47 move handler | degraded | P2 | expected-contract:work/requirements-register.md:15 | requirement:R-3 | `automate` - regression: yes | new | e2e-ui | state transition |
| TS-4 | Move of a book already in the cart: quantity summed | R-3 | state @ WishlistPage.tsx:48 move handler | degraded | P2 | expected-contract:work/requirements-register.md:15 | requirement:R-3 | `automate` — regression: yes - quantity is summed (Q6 a) | new | e2e-ui | decision table |
| TS-5 | Guest cart merge: higher wins, capped at stock, no-stock dropped, empty guest cart | R-4 | boundary @ cartService.ts:118 merge | data-loss | P0 | expected-contract:work/requirements-register.md:16 | requirement:R-4 | `automate` - regression: yes; EX-2 covers the helper only | new | api | equivalence partitioning |
| TS-6 | Failed merge (500, timeout) is not shown as success - expected red | R-12 | error-path @ LoginPage.tsx:36 merge call | data-loss | P0 | expected-contract:work/requirements-register.md:24 |  | `automate` — regression: yes - expected red: assert the visible error text | new | e2e-ui | fault injection |
| TS-7 | Re-adding a book sums into one item, answers 201 | R-5 | state @ cartService.ts:53 add | money | P0 | expected-contract:MyBooks/docs/openapi.json | external:MyBooks/docs/openapi.json | `automate` - regression: yes | new | api | state transition |
| TS-8 | Invalid quantity or bookId refused, cart unchanged | R-6 | boundary @ schemas.ts:40 cart schema | degraded | P2 | expected-contract:MyBooks/docs/openapi.json | external:MyBooks/docs/openapi.json | `automate` - regression: yes, parametrised | new | api | boundary value analysis |
| TS-9 | OUT_OF_STOCK and INSUFFICIENT_STOCK, cart unchanged | R-7 | boundary @ cartService.ts:35 stock check | money | P0 | expected-contract:work/requirements-register.md:19 | requirement:R-7 | `automate` - regression: yes; EX-1 covers the helper only | new | api | boundary value analysis |
| TS-10 | Unknown book id answers 404 BOOK_NOT_FOUND | R-8 | error-path @ cartService.ts:33 book lookup | degraded | P2 | expected-contract:MyBooks/docs/openapi.json | external:MyBooks/docs/openapi.json | `automate` - regression: yes, one instance | new | api | error guessing |
| TS-11 | Guest and user (and ADMIN) carts are separate owners | R-9 | permission @ route.ts:15 owner resolution | access | P0 | expected-contract:work/requirements-register.md:21 | | `automate` - regression: yes | new | api | pairwise |
| TS-12 | Quantity update never exceeds stock (PUT) | R-10 | boundary @ cartService.ts:80 update | degraded | P2 | expected-contract:work/requirements-register.md:22 | requirement:R-10 | `automate` — regression: yes - verb PUT as in contract and code | new | api | boundary value analysis |
| TS-13 | Badge equals sum of quantities, total equals sum of price x quantity (walk: See and change the cart) | R-11 | state @ AppProviders.tsx:35 badge count | money | P0 | expected-contract:work/requirements-register.md:23 | | `automate` - regression: yes | new | e2e-ui | state transition |
| TS-14 | Walk: sign in with a guest cart, change, sign out and in again | R-4, R-12 | state @ LoginPage.tsx:36 sign-in | data-loss | P0 | current-code:MyBooks/src/components/pages/LoginPage.tsx:36 | requirement:R-4 | `manual-agent` - regression: no, a walk | | e2e-ui | exploratory charter |
| TS-15 | Walk: add with real input, double click, sold out meanwhile | R-5, R-6, R-7, R-8 | boundary @ cartService.ts:35 add | money | P0 | current-code:MyBooks/src/lib/services/cartService.ts:35 | requirement:R-7 | `manual-agent` - regression: no, a walk | | e2e-ui | exploratory charter |
| TS-16 | Walk: guest and signed-in browsers, sign-out leftovers | R-9 | permission @ route.ts:15 owner | access | P0 | current-code:MyBooks/src/app/api/cart/route.ts:15 | | `manual-agent` - regression: no, a walk | | e2e-ui | exploratory charter |
| TS-17 | Cart page under failed GET /api/cart, GET /api/books/{bookId}, PUT and DELETE /api/cart/{itemId} | R-14 | error-path @ CartPage.tsx:30 cart read | degraded | P2 | expected-contract:work/requirements-register.md:26 | | `automate` - regression: yes, likely red | new | e2e-ui | fault injection |
| TS-18 | Wishlist move under failed DELETE /api/wishlist/{bookId}, POST /api/cart, GET /api/wishlist | R-13 | error-path @ WishlistPage.tsx:58 wishlist delete | degraded | P2 | expected-contract:work/requirements-register.md:25 | | `automate` - regression: yes, likely red | new | e2e-ui | fault injection |
| TS-19 | Catalog add under failed POST /api/cart | R-1 | error-path @ HomePage.tsx:120 add call | blocked-flow | P1 | expected-contract:work/requirements-register.md:13 | requirement:R-1 | `automate` - regression: yes | new | e2e-ui | fault injection |
| TS-20 | Book page add and read under failed POST /api/cart, GET /api/books/{bookId} | R-2 | error-path @ BookDetailPage.tsx:49 add call | blocked-flow | P1 | expected-contract:work/requirements-register.md:14 | requirement:R-2 | `automate` - regression: yes | new | e2e-ui | fault injection |

Requests of the flow that no row fails (admin, reviews, related books, categories, orders, catalog listing, the heart button) are set aside with a reason in `request_homes` of `work/test-plan.json`. Two call sites whose address is not a literal (AdminPage.tsx:195, ReviewsSection.tsx:72) are not measured; both are outside the cart register.

## Recommended regression

No regression: the story changes no code (grounded on current code) and `tests/` holds no cart, wishlist or sign-in-merge test; the only existing tests of the area, EX-1 and EX-2 in the application's `src/lib/cartRules.test.ts`, are read only here and cover pure helpers.

<!-- qa-factory:case-appendix:start -->
## Case appendix

| Case | Plan row | Oracle/basis | Channel | Review status | Version |
|---|---|---|---|---|---|
| LOCAL-1_TC_001 | unlinked | requirement:R-1 | auto | Draft | cv_790347248271698f96a8 |
| LOCAL-1_TC_002 | unlinked | requirement:R-2 | auto | Draft | cv_954699fb8b99e3d517f8 |
| LOCAL-1_TC_003 | unlinked | requirement:R-3 | auto | Draft | cv_5fc837acf896dfff90af |
| LOCAL-1_TC_004 | unlinked | requirement:R-3 | auto | Draft | cv_cca54fdf799e544afa20 |
| LOCAL-1_TC_005 | unlinked | requirement:R-4 | auto | Draft | cv_63c288a61eb8991687ce |
| LOCAL-1_TC_006 | unlinked | consistency:work/requirements-register.md Behaviour claims R-12 (before unknown, now login shown as success) | auto | Draft | cv_53582e9fd2b6ca89c1d8 |
| LOCAL-1_TC_007 | unlinked | external:MyBooks/docs/openapi.json | auto | Draft | cv_c9db7e5d30cd72586fd9 |
| LOCAL-1_TC_008 | unlinked | external:MyBooks/docs/openapi.json | auto | Draft | cv_8ede714a71163159739c |
| LOCAL-1_TC_009 | unlinked | external:MyBooks/docs/openapi.json | auto | Draft | cv_076607482889f76c8067 |
| LOCAL-1_TC_010 | unlinked | external:MyBooks/docs/openapi.json | auto | Draft | cv_56c42ddf595793688b24 |
| LOCAL-1_TC_011 | unlinked | consistency:work/requirements-register.md Behaviour claims R-9 (before unknown, now cart separated by owner) | auto | Draft | cv_1034782aa1322af81825 |
| LOCAL-1_TC_012 | unlinked | external:MyBooks/docs/openapi.json | auto | Draft | cv_449be24f68e1f4525921 |
| LOCAL-1_TC_013 | unlinked | consistency:work/requirements-register.md Behaviour claims R-11 (before unknown, now badge is the sum of quantities) | auto | Draft | cv_a66f995d657e98e066b3 |
| LOCAL-1_TC_014 | unlinked | requirement:R-4 | manual-agent | Draft | cv_6a7b2dde6d47ad7bccd9 |
| LOCAL-1_TC_015 | unlinked | external:MyBooks/docs/openapi.json | manual-agent | Draft | cv_d5f8d0a9c43032173271 |
| LOCAL-1_TC_016 | unlinked | consistency:work/requirements-register.md Behaviour claims R-9 (before unknown, now cart separated by owner) | manual-agent | Draft | cv_f3d9f6c5056b38862707 |
| LOCAL-1_TC_017 | unlinked | consistency:work/requirements-register.md Behaviour claims R-14 (before unknown, now page reads response without status) | auto | Draft | cv_99bf718f3411b4bf6c6f |
| LOCAL-1_TC_018 | unlinked | consistency:work/requirements-register.md Behaviour claims R-13 (before unknown, now delete answer ignored, Moved to cart shown) | auto | Draft | cv_0b1d818aebd03eb1b7fd |
| LOCAL-1_TC_019 | unlinked | requirement:R-1 | auto | Draft | cv_42197f7763d53d7d627e |
| LOCAL-1_TC_020 | unlinked | requirement:R-2 | auto | Draft | cv_2c77502f513509930339 |

Cases: 20. Generated from pinned case content; do not edit this section by hand.

### LOCAL-1_TC_001 — cv_790347248271698f96a8

Requirements: R-1
Plan row: TS-1

## Given
A guest on the catalog page; empty cart; one in-stock book A and one book B whose stock is 0 (marked records of this case).

## Steps
1. Read the cart badge (0). Click "Add to cart" on card A.
2. Read the cart through GET /api/cart as the same guest.
3. Click "Add to cart" on card B (stock 0).

## Then
1. P-instock: after clicking Add on A a success message is on screen (a non-error toast naming the add).
2. P-instock: the badge reads 1 and GET /api/cart (independent channel) holds one line for A with quantity 1.
3. P-shortstock: for B an error message is shown, no success message, the badge stays 1 and GET /api/cart has no line for B.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-1 | success + badge | R-1 | quantity 1 | 1, 2 | exact toast wording not given by R-1 |
| OB-1 | short stock error | R-1 | stock 0 | 3 | stock 1 vs 2 left to TS-9 |

### LOCAL-1_TC_002 — cv_954699fb8b99e3d517f8

Requirements: R-2
Plan row: TS-2

## Given
A guest on the page of in-stock book A (stock >= 4) and of stock-0 book B.

## Steps
1. On A with quantity 1 click Add; capture the message M1.
2. Reload A, set quantity 3, click Add; capture M3.
3. Read GET /api/cart.
4. Open B; observe the Add button; try to click it; watch the network.

## Then
1. P-qty1: a success message M1 is shown.
2. P-qty3: a success message M3 is shown and M3 differs from M1 (R-2 "differs for quantity above 1").
3. GET /api/cart holds one line for A with quantity 4 (1+3), read independently of the page.
4. P-outofstock: on B the button is disabled and no POST /api/cart is sent when it is clicked; the cart has no line for B.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-2 | quantity 1 vs >1 | R-2 | 1 and 3 | 1, 2, 3 | quantity edges 0/999/1000 are TS-8 |
| OB-2 | out of stock | R-2 | stock 0 | 4 | |

### LOCAL-1_TC_003 — cv_5fc837acf896dfff90af

Requirements: R-3
Plan row: TS-3

## Given
User signed in with an empty cart; book A (not in cart) on the wishlist.

## Steps
1. Open the wishlist, click "Move to cart" on A.
2. GET /api/cart and GET /api/wishlist.
3. Undo: add A to the wishlist again and move it again.

## Then
1. P-notincart: GET /api/cart shows exactly one line for A with quantity 1 and the badge reads 1.
2. GET /api/wishlist no longer contains A (independent of the page list).
3. The second move (undo path) ends with A in the cart and out of the wishlist again, and no other cart line appears.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-3 | add qty 1, remove from wishlist | R-3 | book not in cart | 1, 2, 3 | already-in-cart is TC_004; failures are TC_018 |

### LOCAL-1_TC_004 — cv_cca54fdf799e544afa20

Requirements: R-3
Plan row: TS-4

## Given
User signed in; book A in the cart with quantity 2 (stock >= 3); A also on the wishlist.

## Steps
1. Click "Move to cart" on A in the wishlist.
2. GET /api/cart and GET /api/wishlist.

## Then
1. P-incart: GET /api/cart holds exactly ONE line for A and its quantity is 3 (2 before the move plus 1; person's answer Q6 reading a). A quantity of 2 (move ignored) or 1 (line replaced) fails.
2. A is gone from GET /api/wishlist and the cart holds no second line for A.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-4 | already in cart | R-3, Q6 a | quantity 2 before the move | 1, 2 | cap at stock on move left to TC_009 |

### LOCAL-1_TC_005 — cv_63c288a61eb8991687ce

Requirements: R-4
Plan row: TS-5

## Given
The account cart holds A=2 and B=5. The guest cart (own session cookie) holds A=4 (higher), B=3 (lower), C=1 (only in guest), D=1 where D's stock is then set to 0. A later run uses an empty guest cart.

## Steps
1. POST /api/cart/merge with the guest cookie and the account session.
2. GET /api/cart as the account.
3. Repeat with guest A quantity above stock: add guest A=12 while stock is 20, then lower stock to 10 (admin or seed) BEFORE the merge, because POST /api/cart refuses 12 over stock 10 (R-7).
4. Repeat with an empty guest cart.

## Then
1. P-higher: A reads 4 (the higher, not the sum 6) and B reads 5 (the account was higher, not 8).
2. P-guestonly: C is in the account cart with quantity 1.
3. P-nostock: D is absent from the account cart.
4. P-cap: with guest A=12 and stock 10, A reads 10, not 12.
5. P-emptyguest: with an empty guest cart the account cart is identical to before (same lines, same quantities) and the merge answers 2xx.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-5 | higher wins | R-4 | guest above and below account | 1 | equal quantities not stated by R-4 |
| OB-5 | cap, drop, empty | R-4 | stock exactly and one over, stock 0 | 2-5 | failed merge is TC_006 |

### LOCAL-1_TC_006 — cv_53582e9fd2b6ca89c1d8

Requirements: R-12
Plan row: TS-6

## Given
A guest holds one marked book in the cart. The browser request POST /api/cart/merge is intercepted to answer 500 (P-merge500) and, in a second run, never to answer (P-mergetimeout). The signed-in account cart is empty.

## Steps
1. Sign in as the stand user on the login page.
2. Observe the page after sign-in. Read the guest cart with the guest cookie (GET /api/cart; the guest owner is still the cookie's cart because the merge did not run), and the account cart as the signed-in user.

## Then
1. R-12: after the failed merge EITHER the page shows a visible error/notice text about the cart not being carried over, OR the guest item is still readable in the guest cart (GET /api/cart with the guest cookie returns the marked book). Both P-merge500 and P-mergetimeout. Success-only outcome (no text on the page, guest cart empty, account cart empty) fails; the code today is this outcome (merge failure only logged), so the case is expected red.
2. The signed-in user's page is reached (URL is not the login form, the page body is non-blank) and shows the account header/menu of the signed-in user; the shopper is not stuck on the login form. This holds in both runs.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-6 | 500 | R-12, Q1 a norm | failed call | 1, 2 | exact wording not stated |
| OB-6 | timeout | R-12 | no answer | 1, 2 | timeout length not stated |

### LOCAL-1_TC_007 — cv_c9db7e5d30cd72586fd9

Requirements: R-5
Plan row: TS-7

## Given
A guest with an empty cart; book A with stock >= 5.

## Steps
1. POST /api/cart {bookId: A, quantity: 2}.
2. POST /api/cart {bookId: A, quantity: 3}.
3. GET /api/cart.

## Then
1. P-first: the first add answers 201.
2. P-readd: the second add of the same book answers 201 (not 200, not 409, not 400).
3. P-readback: GET /api/cart, read independently of both POST answers, holds exactly ONE line for A with quantity 5 (2 + 3). A line replaced by the last add (quantity 3) or two lines (2 and 3) fails.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-7 | sum into one item, 201 | R-5 / openapi POST /api/cart | 2 then 3 | 1-3 | sum above stock is TC_009 |

### LOCAL-1_TC_008 — cv_8ede714a71163159739c

Requirements: R-6
Plan row: TS-8

## Given
A guest with an empty cart; book A with stock 1000.

## Steps
For each input POST /api/cart, then GET /api/cart: quantity 0, -1, 1000, 1.5; bookId 0 and -3 with quantity 1; then quantity 1 and quantity 999 for A (separate guest sessions so the sum does not hit stock).

## Then
1. P-qty-below, P-qty-above, P-fraction: quantity 0, -1, 1000 and 1.5 each answer 400 with code VALIDATION_ERROR.
2. P-badid: bookId 0 and -3 each answer 400 VALIDATION_ERROR (not 404, not 500).
3. P-edges: quantity 1 and quantity 999 are accepted (201); after every refusal GET /api/cart, read independently, is empty, equal to the cart before the call.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-8 | quantity edges | R-6 / openapi POST /api/cart | 0,1,999,1000,1.5,-1 | 1, 3 | text and missing field not in the plan |
| OB-8 | bookId | R-6 | 0, negative | 2 | |

### LOCAL-1_TC_009 — cv_076607482889f76c8067

Requirements: R-7
Plan row: TS-9

## Given
Guest cart empty; book Z stock 0; book A stock 5 with 3 already in the cart.

## Steps
1. POST /api/cart Z quantity 1.
2. POST /api/cart A quantity 2 (total equals stock).
3. Reset A to 3 in the cart (PUT /api/cart/{itemId} quantity 3), POST /api/cart A quantity 3 (total 6, one over stock).
4. GET /api/cart after each call.

## Then
1. P-zero: Z quantity 1 answers 400 OUT_OF_STOCK. P-met: A +2 (3+2 = stock 5) is accepted (201) and the cart reads A = 5. P-over: A +3 on 3 answers 400 INSUFFICIENT_STOCK, a different code from P-zero.
2. After each refused add, GET /api/cart (independent of the POST answer) equals the cart before the call: no Z line, A unchanged (3 after the P-over refusal).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-9 | stock 0 | R-7, openapi 400 codes | 0 | 1, 2 | |
| OB-9 | met / one over with cart | R-7, Q7 a | stock and stock+1 | 1, 2 | concurrent buyers walked in TC_015 |

### LOCAL-1_TC_010 — cv_56c42ddf595793688b24

Requirements: R-8
Plan row: TS-10

## Given
A guest with an empty cart; an id N that no book has (positive integer).

## Steps
1. POST /api/cart {bookId: N, quantity: 1}.
2. GET /api/cart.

## Then
1. P-unknownid: the answer is 404 with code BOOK_NOT_FOUND (not 400, not 500).
2. GET /api/cart, read independently, is empty: no line and no empty line for N (refused add writes nothing, Q8 a).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-10 | unknown id | R-8 / openapi 404 | highest id + 1 | 1, 2 | one instance by plan |

### LOCAL-1_TC_011 — cv_1034782aa1322af81825

Requirements: R-9
Plan row: TS-11

## Given
Guest session G1 and a second guest session G2 with another cookie; the USER and ADMIN accounts; each with an empty cart (marked books only; read only own marked lines, never a global count).

## Steps
1. G1 adds book A; the USER (signed in) reads GET /api/cart.
2. The USER adds book B; G2 reads GET /api/cart.
3. Repeat 1 and 2 with ADMIN in place of USER.
4. G1 sends PUT and DELETE for the item id of the USER's line; then the USER reads the cart.

## Then
1. P-guest-vs-user: the USER cart has no line for A (the item added by the guest is absent).
2. P-user-vs-guest: G2's cart has no line for B (absent).
3. P-admin: the ADMIN cart has no line for A and G2's cart has no ADMIN-added line, same as for USER.
4. P-foreign-item: after the foreign PUT and DELETE (the status code is not asserted, no source names it) the USER's own GET /api/cart (an allowed call by the same account, answers 2xx) still holds B's line with its original quantity, unchanged.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-11 | guest / user / admin | R-9 | owner pairs | 1-3 | session cookie reuse after sign-out is TC_016 |
| OB-11 | foreign item id | R-9 ("never changed by another owner") | other owner's id | 4 | refusal status/code named by no source |

### LOCAL-1_TC_012 — cv_449be24f68e1f4525921

Requirements: R-10
Plan row: TS-12

## Given
A guest cart with one line of book A (stock 5), quantity 1. The update call is PUT /api/cart/{itemId} (Q2 reading a: PUT). Level: api; the cart page message is a UI check not carried here (declared gap).

## Steps
1. PUT quantity 5 (at stock), then GET /api/cart.
2. PUT quantity 6 (one over), then GET /api/cart.

## Then
1. P-atstock: PUT 5 is accepted (2xx) and GET /api/cart reads 5. P-overstock: PUT 6 answers 400 INSUFFICIENT_STOCK (Q9 a).
2. After the refused update GET /api/cart (independent of the PUT answer) still holds quantity 5, the value before the refused call (Q10 a: item unchanged).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-12 | cap at stock | R-10, Q9 a | 5 and 6 | 1, 2 | quantity 0 and 1000 on update not in the plan; cart page message on a refused update (Q11 a: a message is shown) is a UI check not carried by this api row; declared gap |

### LOCAL-1_TC_013 — cv_a66f995d657e98e066b3

Requirements: R-11
Plan row: TS-13

## Given
A guest with an empty cart; books A and B with known prices pA and pB (marked records, set by the case).

## Steps
1. Add 2 of A and 1 of B. Read the badge and the cart page total; read GET /api/cart.
2. Add A again (quantity 1).
3. On the cart page change A's quantity to 2, then remove B's line.

## Then
1. P-lines-vs-units: badge is 3 and total is 2*pA + pB (a badge counting lines gives 2 and fails).
2. After adding A again badge is 4 and total is 3*pA + pB.
3. After A is set to 2 and B is removed, badge is 2 and total is 2*pA; both agree with the stored lines of GET /api/cart (independent channel).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-13 | badge | R-11 | units vs lines | 1-3 | rounding of totals not stated |
| OB-13 | total | R-11 | price x quantity | 1-3 | |

### LOCAL-1_TC_014 — cv_6a7b2dde6d47ad7bccd9

Requirements: R-4
Plan row: TS-14

Evidence policy: ui; before/after captures of the cart page and badge at each step, plus the actual steps taken.

## Given
Account cart of the stand user empty. A guest with 2 marked books A (quantity 1) and B (quantity 2) in the cart; the stand user signed out. Level: UI sign-in path (merge rules are api-tested in TC_005; failed merge R-12 is TC_006).

## Steps
1. Sign in; read the cart page and the badge.
2. Change A to quantity 3; sign out; sign in again; read the cart and the badge.
3. Sign out, with an empty guest cart sign in again; read the cart.

## Then
1. After the first sign-in the account cart holds A with 1 and B with 2 (both guest books) and the badge is 3.
2. P-second-signin: after sign-out and sign-in the account cart holds A with 3 and B with 2 (nothing doubled: not 6/4), badge 5; the guest cart after sign-out holds neither book.
3. P-emptyguest: sign-in with an empty guest cart leaves the account cart as it was (A 3, B 2).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-14 | walk of sign-in | R-4 | second sign-in | 1-3 | failure of merge (R-12) is TC_006 |

### LOCAL-1_TC_015 — cv_d5f8d0a9c43032173271

Requirements: R-6, R-7, R-8
Plan row: TS-15

Evidence policy: ui; before/after captures of the page, the quantity field and GET /api/cart, plus the actual steps taken.

## Given
A book with stock 1 (marked). A guest session in two tabs. Level: UI behaviour (double click, typed values); status rules are api-tested in TC_007..TC_010.

## Steps
1. Double click Add on the last copy; read GET /api/cart.
2. In tab 2 sell the last copy (stock set to 0 by admin or seed); in tab 1 click Add; read the page and GET /api/cart.
3. In the quantity box type 0, 1000, 2.5, text, spaces only, one key at a time for 999; click Add each time.
4. Open the add for a book id that does not exist (URL of a book page with an unused id, or the add call of that id) and read the page and GET /api/cart.

## Then
1. P-doubleclick: invariant - the cart quantity of the book is never above stock: GET /api/cart reads exactly 1 (second click refused or ignored), never 2.
2. P-soldout: the page shows an out-of-stock message (OUT_OF_STOCK, Q12 a) and GET /api/cart is unchanged from before the click.
3. P-typed: 0, 1000, 2.5, text and spaces only add nothing (GET /api/cart unchanged); 999 typed one key at a time keeps all three digits and the field keeps focus.
4. P-unknownbook: the unknown book id gives a refusal (404 BOOK_NOT_FOUND, no success message) and GET /api/cart holds no line for it.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-15 | double click, sold out, typed values, unknown id | R-6, R-7, R-8, Q12 a | stock 1; 0, 1000, 2.5, text; unused id | 1-4 | timing between tabs not deterministic; R-5 sum is TC_007 |

### LOCAL-1_TC_016 — cv_f3d9f6c5056b38862707

Requirements: R-9
Plan row: TS-16

Evidence policy: ui; cookie state and cart page captured after each step, plus the actual steps taken.

## Given
Two browser profiles; the stand user with an empty account cart. Level: cookies and two browsers; scripted separation is TC_011.

## Steps
1. Profile 1 as a guest adds marked book A, signs in, adds marked book B, then signs out; read the cart and the cookie state.
2. Clear the cookies and reopen the cart.
3. Profile 2 signs in with the same account and reads the cart.

## Then
1. P-signout: after sign-out the guest cart in profile 1 holds neither A nor B (the user's items are never visible to the guest owner); after the cookies are cleared no previous cart reopens (empty cart).
2. P-twobrowsers: profile 2 with the same account shows the account cart with A and B (and nothing else marked); GET /api/cart as the signed-in user agrees.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-16 | sign-out leftovers, two browsers | R-9 | cookie reuse | 1, 2 | scripted separation is TC_011 |

### LOCAL-1_TC_017 — cv_99bf718f3411b4bf6c6f

Requirements: R-14
Plan row: TS-17

## Given
A guest cart with two lines (stored qty 1 each); route interception on the browser.

## Steps
1. Fail GET /api/cart with 500, then with no answer; open the cart page.
2. Fail GET /api/books/{bookId} with 500; open the cart page.
3. Fail PUT /api/cart/{itemId} (500, timeout); change a quantity; GET /api/cart without interception.
4. Fail DELETE /api/cart/{itemId} (500, timeout); remove a line; GET /api/cart without interception.

## Then
1. P-cartread: with the cart read failed the page shows an error text saying the cart could not be read; it does not show the empty-cart text as if the cart were empty (the stored cart has two lines).
2. P-bookread: with the book read failed the page shows an error text or the two cart lines (with ids/quantities); it is not silently blank.
3. P-putfail: after the failed quantity change the page shows an error text, and the stored quantity (unintercepted GET /api/cart) is still 1.
4. P-deletefail: after the failed delete a message is shown, the line stays on the page, and the stored cart (unintercepted GET) still holds the line.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-17 | read failures | R-14, Q1 a norm | 500 and timeout | 1, 2 | badge read failure (AppProviders) only observed, not asserted |
| OB-17 | write failures | R-14, Q1 a norm | 500 and timeout | 3, 4 | message wording not stated |

### LOCAL-1_TC_018 — cv_0b1d818aebd03eb1b7fd

Requirements: R-13
Plan row: TS-18

## Given
A user with a marked book on the wishlist; route interception.

## Steps
1. Fail DELETE /api/wishlist/{bookId} (500, timeout); click Move to cart; read GET /api/cart and GET /api/wishlist unintercepted.
2. Fail POST /api/cart (500, timeout); click Move to cart; read both lists.
3. Fail DELETE on the remove button; click it.
4. Fail GET /api/wishlist; open the page.

## Then
1. P-deletefail: no "Moved to cart" success message is shown; an error text is shown instead, or the book is announced as left in both places; a book in both lists (GET /api/cart and GET /api/wishlist both hold it) with only a success message fails.
2. P-postfail: after a failed add the book is still in GET /api/wishlist, GET /api/cart holds no line for it, and the page shows an error text, not a success message.
3. P-removefail: the remove-button failure shows an error text and GET /api/wishlist still holds the book.
4. P-getfail: the page with a failed wishlist read shows an error text (not a blank page or the empty-wishlist text as the truth).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-18 | move under failed calls | R-13, Q1 a norm | DELETE, POST failing | 1, 2 | success path is TC_003 |
| OB-18 | remove and read failures | R-13, Q1 a norm | DELETE, GET failing | 3, 4 | message wording not stated |

### LOCAL-1_TC_019 — cv_42197f7763d53d7d627e

Requirements: R-1
Plan row: TS-19

## Given
A guest on the catalog page with the badge at 0.

## Steps
1. Intercept POST /api/cart to answer 500 (P-http500); click Add on a card.
2. Repeat with POST /api/cart never answering (P-timeout).
3. Read GET /api/cart unintercepted.

## Then
1. In both runs an error text is shown and no success message appears (R-1 promises success only for an add that happened).
2. The badge stays 0 and GET /api/cart holds no line, so the badge and the stored cart agree.
3. The catalog list is still shown and the Add button works again after the failure.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-19 | failed add | R-1 | 500 and no answer | 1-3 | R-1 does not word the failure message |

### LOCAL-1_TC_020 — cv_2c77502f513509930339

Requirements: R-2
Plan row: TS-20

## Given
A guest on the page of an in-stock book; route interception.

## Steps
1. Intercept POST /api/cart to answer 500 (P-http500), then to never answer (P-timeout); set quantity 3 and click Add.
2. Read GET /api/cart unintercepted.
3. Intercept GET /api/books/{bookId} with 500 and then with no answer; open the book page.

## Then
1. After the failed add an error text is shown and neither the single-item nor the quantity-above-1 success message appears.
2. GET /api/cart holds no line for the book (independent of the page).
3. With the book read failed the page shows a message and is not blank.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-20 | failed add | R-2 | 500 and no answer, quantity 3 | 1, 2 | R-2 does not word the failure message |
| OB-20 | failed book read | R-2 | 500 and no answer | 3 | blank page is judged by the page showing any text |
<!-- qa-factory:case-appendix:end -->
