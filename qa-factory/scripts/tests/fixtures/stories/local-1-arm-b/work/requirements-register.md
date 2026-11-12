---
task: LOCAL-1
created: 2026-11-05
ids: [R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-9, R-10, R-11, R-12, R-13, R-14]
by_source: {story: 4, feature: 0, assumption: 0, discussion: 0, ac: 0, derived: 10}
confidence: low
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact | delta | code_says |
|---|---|---|---|---|---|---|---|---|---|
| R-1 | A shopper adds a book to the cart from a catalog card (Add to cart button) with quantity 1 and sees a success message and an updated cart badge | story | — | yes | — | current-code:MyBooks/src/components/pages/HomePage.tsx:118 | blocked-flow | unchanged | meets: fact-5 |
| R-2 | A shopper adds a book from its detail page with a chosen quantity; the message differs for quantity above 1; the button is unusable when the book is out of stock | story | — | yes | — | current-code:MyBooks/src/components/pages/BookDetailPage.tsx:45 | blocked-flow | unchanged | meets: fact-6 |
| R-3 | "Move to cart" on the wishlist adds the book (quantity 1) to the cart and removes it from the wishlist | story | — | yes | — | current-code:MyBooks/src/components/pages/WishlistPage.tsx:47 | degraded | unchanged | meets: fact-7 |
| R-4 | After sign-in the guest cart moves into the account cart: for the same book the higher quantity wins, capped at stock; a book with no stock is dropped | story | — | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:118 | data-loss | unchanged | meets: fact-8 |
| R-5 | Adding a book already in the cart adds the quantity to the existing item (one item, summed quantity) and answers 201 | derived | norm:openapi POST /api/cart quantity is added to what is already in the cart | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:53 | money | unchanged | meets: fact-3 |
| R-6 | Quantity must be a whole number 1..999 and bookId a positive integer; anything else is refused with VALIDATION_ERROR and nothing is added | derived | norm:openapi POST /api/cart request schema | yes | — | current-code:MyBooks/src/lib/validation/schemas.ts:40 | degraded | unchanged | meets: fact-4 |
| R-7 | A book with stock 0 is refused as OUT_OF_STOCK; an amount that with what is already in the cart exceeds stock is refused as INSUFFICIENT_STOCK; the cart is unchanged | derived | norm:openapi 400 codes; invariant: stock is respected | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:35 | money | unchanged | meets: fact-2 |
| R-8 | Adding a book id that does not exist is refused as 404 BOOK_NOT_FOUND | derived | norm:openapi 404 BOOK_NOT_FOUND | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:33 | degraded | unchanged | meets: fact-12 |
| R-9 | A guest cart (session cookie) and a signed-in user cart are separate owners: an item added by one owner is never visible to or changed by another | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/app/api/cart/route.ts:15 | access | unchanged | meets: fact-1 |
| R-10 | Setting the quantity of a cart item on the cart page never exceeds stock (INSUFFICIENT_STOCK) and the cart page shows the result | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:80 | degraded | unchanged | meets: fact-11 |
| R-11 | The cart badge equals the sum of quantities and the cart total equals the sum of price x quantity, both re-read after every add | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/components/providers/AppProviders.tsx:35 | money | unchanged | meets: fact-10 |
| R-12 | A failed guest-cart merge at sign-in is not presented as success: the shopper is told or the guest items are not lost silently | derived | norm:a failed call is not shown as success | yes | — | current-code:MyBooks/src/components/pages/LoginPage.tsx:36 | data-loss | unchanged | contradicts: fact-9 |
| R-13 | "Move to cart" does not report success when removing the book from the wishlist failed, and does not leave the book in both places unannounced | derived | norm:a failed call is not shown as success | yes | — | current-code:MyBooks/src/components/pages/WishlistPage.tsx:58 | degraded | unchanged | unknown: no fact states the wishlist delete outcome; line 58 ignores the answer |
| R-14 | When reading the cart or changing a quantity fails, the cart page says so instead of showing an empty or stale cart | derived | norm:a failed call is not shown as success | yes | — | current-code:MyBooks/src/components/pages/CartPage.tsx:30 | degraded | unchanged | unknown: the scout flagged CartPage.tsx:30,36 as unchecked responses; no fact states the outcome |

## Functions

| Function | Requirements |
|---|---|
| Add from the catalog | R-1 |
| Add from the book page | R-2 |
| Move from the wishlist | R-3, R-13 |
| Carry the guest cart over at sign-in | R-4, R-12 |
| Stock and quantity rules of adding | R-5, R-6, R-7, R-8 |
| Guest and user carts | R-9 |
| See and change the cart | R-10, R-11, R-14 |

## Branches

| BN | R | kind | source_ref | text |
|---|---|---|---|---|
| BN-1 | R-1 | refusal | description | book out of stock or short of stock from the catalog card: error toast, badge unchanged |
| BN-2 | R-2 | partition | description | quantity 1 versus more than 1 (different message) |
| BN-3 | R-2 | refusal | description | out-of-stock book: button disabled |
| BN-4 | R-3 | variant | description | the book is already in the cart when it is moved |
| BN-5 | R-4 | partition | description | same book in both carts; book only in guest cart; guest book with no stock |
| BN-6 | R-4 | variant | description | empty guest cart at sign-in |
| BN-7 | R-6 | partition | description | quantity 0, 1, 999, 1000, non-integer; bookId 0 and negative |
| BN-8 | R-7 | partition | description | stock exactly met, one over, stock 0 |
| BN-9 | R-9 | partition | description | guest, USER; ADMIN uses the same cart rules |

## Source obligations

| unit | home |
|---|---|
| U-b08550b9b491, U-28c0ce76f332 | R-1 |
| U-b08550b9b491, U-28c0ce76f332 | R-2 |
| U-b08550b9b491, U-28c0ce76f332 | R-3 |
| U-b08550b9b491, U-28c0ce76f332 | R-4 |
| U-43094330aa2e, U-1183f159e0ef, U-3b4249237fbe, U-dcbcdf3e8f0c | not_obligation: pointer to context or stand, no behaviour stated |
| U-bb9b81e00e80, U-18ed71223418, U-bab619feda9e, U-6f97f1ca7e0e, U-e86ebddc19fd, U-7309fc27ab1c, U-c500d1b7b167, U-1d170e15c5fc, U-b7fd23937022, U-e393fe3cc218, U-028b56a68d21, U-25c36b19e0b8, U-d2a71dbff19a, U-fc88946cd533, U-94ab1000bcc1, U-910994c3e162 | R-9 |
| U-070bf82f16b1, U-9f34e69d5753, U-800cdd10105c, U-578b7fdc0fe3, U-75d5a96baec6, U-2ee516cbce75, U-8eafdb4061f4, U-5b2daa60e2b0, U-9fb7e42bd29f, U-562966516d43, U-89f0153096a8, U-c31c388ad2e3, U-df1c67746750, U-1344ebb40a9f, U-21d3c0c62657 | R-6 |
| U-97e77818bb81, U-8d1281dcd008, U-51af4321657e, U-1bc5d657b1df, U-25ef4271866d | R-5 |
| U-2ea2edb8ef18, U-c43db4a8cb7c, U-34cf02f2c851 | R-7 |
| U-d57309758c8f, U-2229c928b440 | R-8 |
| U-843fff4b27ff, U-65f882664219, U-6f01ff7ba2a0, U-3b4971d4f979, U-c06c8bd024ce, U-bb1af034b1bd | not_obligation: clearing the cart is not a way into the cart |
| U-b2d3080e42f3, U-83a17fcb9511, U-58ef9793448b, U-c9c31288f9f0, U-c97d8eccc630, U-3ff62996f2f8, U-809252b0f855, U-fbe8cd6a0652, U-cc42d40802c3, U-dcf1034e4a5e, U-4ee8a28e8183, U-28cd015fe5d7 | R-10 |
| U-c9ecf0be3365, U-e24e155dd1a4, U-080c1aff04e0, U-7689232c0950 | not_obligation: removing an item is not a way into the cart |
| U-e69e968dda14, U-f8ac185f5be1, U-2996f840620c, U-17b0d1f0c33f, U-22dc79853e42, U-f5f66591c9dd, U-ee2f6bdb9119 | R-11 |
| U-3b4b6b85fb3e, U-f5c23867b219, U-3f96332f7fe1, U-384f461a2cba, U-c59c9ecd7b31, U-ffd81f0502e9, U-e13fb202d934, U-f05a574f4ed5, U-69a63738a19b, U-2dfe26518883, U-f5f91a295d80 | R-4 |
| U-d67c17035548 | not_obligation: orders are outside add to cart |
| U-8fa6df566231 | not_obligation: provenance note of the scout |
| U-38ad887a4f2a | R-5 |
| U-38ad887a4f2a | R-6 |
| U-38ad887a4f2a | R-7 |
| U-38ad887a4f2a | R-10 |
| U-38ad887a4f2a | R-4 |

## Contradiction matrix

| R | parent story/feature | comments & notes (ticket + parent) | area cases | area open bugs |
|---|---|---|---|---|
| R-1 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-2 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-3 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-4 | silent | silent | ok:MyBooks/src/lib/cartRules.test.ts:5 | n/a: REF-1 unavailable, gap accepted by the person |
| R-5 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-6 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-7 | silent | silent | ok:MyBooks/src/lib/cartRules.test.ts:21 | n/a: REF-1 unavailable, gap accepted by the person |
| R-8 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-9 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-10 | silent | contradicts:"PATCH /api/cart/{id} capped at stock" (scout note U-38ad887a4f2a; contract and code say PUT) | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-11 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-12 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-13 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |
| R-14 | silent | silent | silent | n/a: REF-1 unavailable, gap accepted by the person |

## Behaviour claims

| R | before | before_ref | now | now_ref | differs | question | origin |
|---|---|---|---|---|---|---|---|
| R-5 | unknown | absent | adds the quantity to the existing item | current-code:MyBooks/src/lib/services/cartService.ts:53 | unknown | Q4 | |
| R-6 | unknown | absent | refuses quantity outside 1..999 | current-code:MyBooks/src/lib/validation/schemas.ts:40 | unknown | Q4 | |
| R-8 | unknown | absent | 404 BOOK_NOT_FOUND for unknown book | current-code:MyBooks/src/lib/services/cartService.ts:33 | unknown | Q4 | |
| R-9 | unknown | absent | cart separated by owner (user or session) | current-code:MyBooks/src/app/api/cart/route.ts:15 | unknown | Q4 | |
| R-11 | unknown | absent | badge is the sum of quantities | current-code:MyBooks/src/components/providers/AppProviders.tsx:35 | unknown | Q4 | |
| R-12 | unknown | absent | merge failure is only logged, login shown as success | current-code:MyBooks/src/components/pages/LoginPage.tsx:36 | unknown | Q4 | |
| R-13 | unknown | absent | wishlist delete answer ignored, Moved to cart shown | current-code:MyBooks/src/components/pages/WishlistPage.tsx:58 | unknown | Q4 | |
| R-14 | unknown | absent | cart page reads response without status | current-code:MyBooks/src/components/pages/CartPage.tsx:30 | unknown | Q4 | |

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-3 | Moving a book already in the cart adds 1 to its quantity | Moving a book already in the cart changes nothing in the cart | cart quantity after the move differs by 1 | Q3 a adopted until answered: the add rule R-5 applies, quantity is summed |
| R-10 | The quantity update verb is PUT (contract, code) | The verb is PATCH (scout note) | which call a test sends | Q2 a adopted until answered: PUT as in the contract and the code |

## Source completeness

| source | relation | relevance | assessment receipt | full-read receipt | revision/hash | status | gap or exclusion reason |
|---|---|---|---|---|---|---|---|
| LOCAL-1 | task | relevant | work/sources/SRC-5b289e26d85e2794df0a | work/sources/SRC-5b289e26d85e2794df0a/776ea5d1fe9f/ticket.json | sha256:776ea5d1fe9f | read | no comments, no attachments |
| MyBooks/docs/openapi.json | normative | relevant | work/sources/SRC-9b765c409c31488a634c | work/sources/SRC-9b765c409c31488a634c/4c438111734f/ticket.json | sha256:4c438111734f | read | |
| https://github.com/person-4/MyBooks | referenced | relevant | work/sources/SRC-7a03f1a608eb7f806360 | work/sources/SRC-7a03f1a608eb7f806360/bcabea6c1565/ticket.json | sha256:bcabea6c1565 | read | read from the local checkout at a25b0801669b |
| https://example.invalid/2/browse/REF-1 | referenced | unknown | work/source-inventory.json | none | unknown | unavailable | person: "not needed"; its stories, cases and bugs on the cart are unknown |
