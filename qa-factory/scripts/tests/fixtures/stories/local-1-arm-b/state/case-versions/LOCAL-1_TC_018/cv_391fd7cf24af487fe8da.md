---
id: LOCAL-1_TC_018
title: Wishlist move under failed DELETE, POST and GET calls (likely red)
area: cart
priority: P2
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-05
task: LOCAL-1
covers: [R-13]
defect_class: error-path
basis: consistency:work/requirements-register.md Behaviour claims R-13 (before unknown, now delete answer ignored, Moved to cart shown)
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in stand user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI is reachable", "check": {"stand_frontend": "the case intercepts routes in the browser"}}, {"id": "PC-3", "kind": "data", "what": "a marked book on the wishlist", "check": {"case_seeds": "the case seeds a marked book and wishlists it"}}]
then_oracles: [{"then": 1, "source": "unknown", "ref": "Q4"}, {"then": 2, "source": "unknown", "ref": "Q4"}, {"then": 3, "source": "unknown", "ref": "Q4"}, {"then": 4, "source": "unknown", "ref": "Q4"}]
question_thens: [{"question": "Q4", "then": 1, "readings": {"now": "Moved to cart is shown although the wishlist delete failed", "before": "no success message, the person is told and the book is not left in both places unannounced"}, "not_needed": ""}, {"question": "Q4", "then": 2, "readings": {"now": "the page behaviour of a failed add to cart is as in the code today", "before": "the book stays in the wishlist and the person is told in words"}, "not_needed": ""}, {"question": "Q4", "then": 3, "readings": {"now": "a failed remove button delete is as in the code today", "before": "the line stays and a message shows"}, "not_needed": ""}, {"question": "Q4", "then": 4, "readings": {"now": "a failed wishlist read is as in the code today", "before": "the page stays alive with a message"}, "not_needed": ""}]
---

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
1. P-deletefail: the message and the two lists after a failed wishlist delete are as Q4 gives; a book in both places with only a success message fails.
2. P-postfail: after a failed add the wishlist and cart are as Q4 gives.
3. P-removefail: the remove button failure shows what Q4 gives and the stored wishlist still holds the book.
4. P-getfail: the page with a failed wishlist read is as Q4 gives.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-18 | move under failed calls | Q4, Q1 norm | DELETE, POST failing | 1, 2 | success path is TC_003 |
| OB-18 | remove and read failures | Q4 | DELETE, GET failing | 3, 4 | |
