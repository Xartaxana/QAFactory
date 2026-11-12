---
id: LOCAL-1_TC_004
title: Move to cart of a book already in the cart sums the quantity (until Q3 answered)
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
then_oracles: [{"then": 1, "source": "unknown", "ref": "raise"}, {"then": 2, "source": "requirement", "ref": "R-3"}]
raise_questions: [{"then": 1, "question": "When a wishlist book already in the cart (quantity 2) is moved to the cart, what quantity must the cart line read afterwards?", "source_says": [{"quote": "quantity is added to what is already in the cart", "where": "MyBooks/docs/openapi.json POST /api/cart; story silent (register Reading forks R-3, Q3)"}], "severity": "minor", "owner_role": "po_ba", "before": {"value": "unknown", "where": "no base revision; implementation_source is current-code"}, "now": {"value": "quantity grows by 1 (reading A)", "where": "MyBooks/src/components/pages/WishlistPage.tsx:48 posts quantity 1, summed by cartService.ts:53"}}]
question_thens: [{"question": "raise", "then": 1, "readings": {"now": "the cart line for A reads quantity 3 (2 plus 1)", "before": "the cart line for A reads what the person names, for example 2 (unchanged)"}, "not_needed": ""}]
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
1. P-incart: GET /api/cart holds ONE line for A and its quantity is the one the answer to Q3 gives (the quantity before the move was 2).
2. A is gone from GET /api/wishlist and the cart holds no second line for A.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-4 | already in cart | R-3, Q3 | quantity 2 before the move | 1, 2 | cap at stock on move left to TC_009 |
