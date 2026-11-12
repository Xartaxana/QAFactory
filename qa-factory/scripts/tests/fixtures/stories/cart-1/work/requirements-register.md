---
task: CART-1
created: 2026-10-31
ids: [R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-9, R-10, R-11, R-12, R-13, R-14, R-15, R-16]
by_source: {story: 0, feature: 0, assumption: 0, discussion: 0, ac: 2, derived: 14}
confidence: low
---

## Register

| R | requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |
|---|---|---|---|---|---|---|---|---|
| R-1 | Every path by which a product can be added to the cart is identified and checked (catalog card, book detail, wishlist move, direct POST /api/cart, guest-cart merge at login) | ac | — | yes | AC-1 | current-code:MyBooks/src/components/BookCard.tsx:78 | blocked-flow | unchanged |
| R-2 | Every scenario in which Add to Cart is used is identified and checked (guest, signed-in, stock edges, change quantity, remove, badge, checkout read) | ac | — | yes | AC-2 | current-code:MyBooks/src/lib/session.ts:34 | blocked-flow | unchanged |
| R-3 | Adding an unknown book answers 404 BOOK_NOT_FOUND and a book with stock 0 answers 400 OUT_OF_STOCK; the card and detail buttons are disabled for stock 0 | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:31 | blocked-flow | unchanged |
| R-4 | A cart quantity never exceeds stock: inCart + adding > stock answers 400 INSUFFICIENT_STOCK, equal to stock is allowed | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/lib/cartRules.ts:7 | degraded | unchanged |
| R-5 | Adding a book already in the cart adds the quantity to the one existing row (no second row) | derived | aspect:shopping cart | yes | — | expected-contract:MyBooks/src/lib/openapi/spec.ts:512 | degraded | unchanged |
| R-6 | POST /api/cart accepts quantity integer 1..999 and positive integer bookId; invalid input is rejected with the stable { error, code } shape | derived | aspect:API contract and errors | yes | — | current-code:MyBooks/src/lib/validation/schemas.ts:41 | degraded | unchanged |
| R-7 | A guest owns a cart by cookie bookstore_session_id, a signed-in user by account; a user never sees guest rows until merge | derived | aspect:roles and permissions | yes | — | current-code:MyBooks/src/lib/cartOwner.ts:6 | access | unchanged |
| R-8 | Sign-in merges the guest cart into the user's cart: same book keeps the higher quantity (not the sum), capped at stock; stock 0 drops the row | derived | aspect:sign-in and user accounts | yes | — | expected-contract:MyBooks/docs/AUTH.md:8 | data-loss | unchanged |
| R-9 | Registration does not call merge and does not sign in; what happens to the guest cart after register-then-login is not stated by any source | derived | aspect:sign-in and user accounts | no | — | current-code:MyBooks/src/components/pages/LoginPage.tsx:35 | data-loss | unchanged |
| R-10 | Cart badge shows the sum of item quantities and refreshes on mount, add and session change | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/components/providers/AppProviders.tsx:35 | degraded | unchanged |
| R-11 | Changing quantity (PUT /api/cart/:id) sets the quantity, rejects above stock with 400 INSUFFICIENT_STOCK, removing deletes the row | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:69 | degraded | unchanged |
| R-12 | Another owner's cart item id answers 404 CART_ITEM_NOT_FOUND on PUT and DELETE (never changes the foreign cart) | derived | aspect:roles and permissions | yes | — | current-code:MyBooks/src/app/api/cart/[id]/route.ts:8 | access | unchanged |
| R-13 | Cart page with an emptied quantity input or a failed cart/book fetch: expected behaviour is not stated (code sends NaN, no response.ok check) | derived | bug:candidate-defect | no | — | current-code:MyBooks/src/components/pages/CartPage.tsx:65 | degraded | unchanged |
| R-14 | Wishlist "move to cart" adds one copy then removes the wishlist item; a failed removal is ignored by the page | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/components/pages/WishlistPage.tsx:58 | degraded | unchanged |
| R-15 | Checkout quote reads the owner's cart (empty or over-stock is rejected) and a successful order clears the cart | derived | aspect:checkout and payment | yes | — | current-code:MyBooks/src/lib/services/orderService.ts:57 | money | unchanged |
| R-16 | Concurrent adds of the same book must not create duplicate rows or exceed stock (findFirst then create/update is not atomic) | derived | aspect:shopping cart | no | — | none | data-loss | unchanged |

## Contradiction matrix

| R | parent story/feature | comments & notes (ticket + parent) | area cases | area open bugs |
|---|---|---|---|---|
| R-1 | n/a:no parent feature in the pasted ticket | silent | silent | n/a:tracker unreachable |
| R-2 | n/a:no parent feature in the pasted ticket | silent | silent | n/a:tracker unreachable |
| R-3 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-4 | n/a:no parent feature | silent | ok:CAND-1 src/lib/cartRules.test.ts:9 | n/a:tracker unreachable |
| R-5 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-6 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-7 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-8 | ok:MyBooks/docs/AUTH.md:8 | silent | ok:CAND-1 src/lib/cartRules.test.ts:5 | n/a:tracker unreachable |
| R-9 | silent | silent | silent | n/a:tracker unreachable |
| R-10 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-11 | ok:MyBooks/src/lib/openapi/spec.ts:512 | silent | silent | n/a:tracker unreachable |
| R-12 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-13 | silent | silent | silent | n/a:tracker unreachable |
| R-14 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-15 | n/a:no parent feature | silent | silent | n/a:tracker unreachable |
| R-16 | silent | silent | silent | n/a:tracker unreachable |

## Behaviour claims

| R | before | before_ref | now | now_ref | differs | question | origin |
|---|---|---|---|---|---|---|---|

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-9 | Guest cart is lost or must be re-added after registration | Guest cart should reach the new account after register then login | Guest items vanish vs survive | question at gate A |
| R-13 | Current handling is acceptable | Empty input or failed fetch must be guarded and show an error | NaN request / blank page vs clear message | question at gate A |

## Source completeness

| source | relation | relevance | assessment receipt | full-read receipt | revision/hash | status | gap or exclusion reason |
|---|---|---|---|---|---|---|---|
| qa-factory/tickets/CART-1.md | task | relevant | work/source-inventory.json | work/ticket-snapshot.json | unknown | read | person's pasted text; Jira CART-1 returns 404 (placeholder key) |
| https://example.invalid/2 | referenced | unknown | work/source-inventory.json | none | unknown | unavailable | tracker not reachable; stories, cases, bugs not read |
| MyBooks (a25b0801669b97d76f96f5a981fdc9ad4525d63d) | subject | relevant | work/context-bundle.json | work/context-bundle.json | a25b0801669b97d76f96f5a981fdc9ad4525d63d | read | current code only; no diff for this task |
