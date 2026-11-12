---
id: LOCAL-1_TC_003
title: Move to cart adds the book with quantity 1 and removes it from the wishlist
area: cart
priority: P2
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-05
task: LOCAL-1
covers: [R-3]
defect_class: state
basis: requirement:R-3
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in stand user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "data", "what": "one marked in-stock book created by the case", "check": {"case_seeds": "the case seeds a marked book and puts it on the wishlist"}}]
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-3"}, {"then": 2, "source": "requirement", "ref": "R-3"}, {"then": 3, "source": "requirement", "ref": "R-3"}]
---

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
