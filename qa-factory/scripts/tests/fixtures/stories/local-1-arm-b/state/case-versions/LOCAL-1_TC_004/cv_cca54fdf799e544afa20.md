---
id: LOCAL-1_TC_004
title: Move to cart of a book already in the cart sums the quantity (2 plus 1 gives 3)
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
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in stand user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "data", "what": "a marked book with stock >= 3", "check": {"case_seeds": "the case seeds a marked book, adds 2 to the cart and wishlists it"}}]
then_oracles: [{"then": 1, "source": "person", "ref": "Q6"}, {"then": 2, "source": "requirement", "ref": "R-3"}]
branches: [{"id": "BN-4", "then": 1}]
---

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
