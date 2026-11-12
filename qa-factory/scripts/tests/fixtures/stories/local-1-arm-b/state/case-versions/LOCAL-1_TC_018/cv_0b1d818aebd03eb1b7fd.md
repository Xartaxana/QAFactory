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
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-13"}, {"then": 2, "source": "requirement", "ref": "R-13"}, {"then": 3, "source": "requirement", "ref": "R-13"}, {"then": 4, "source": "requirement", "ref": "R-13"}]
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
1. P-deletefail: no "Moved to cart" success message is shown; an error text is shown instead, or the book is announced as left in both places; a book in both lists (GET /api/cart and GET /api/wishlist both hold it) with only a success message fails.
2. P-postfail: after a failed add the book is still in GET /api/wishlist, GET /api/cart holds no line for it, and the page shows an error text, not a success message.
3. P-removefail: the remove-button failure shows an error text and GET /api/wishlist still holds the book.
4. P-getfail: the page with a failed wishlist read shows an error text (not a blank page or the empty-wishlist text as the truth).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-18 | move under failed calls | R-13, Q1 a norm | DELETE, POST failing | 1, 2 | success path is TC_003 |
| OB-18 | remove and read failures | R-13, Q1 a norm | DELETE, GET failing | 3, 4 | message wording not stated |
