---
id: LOCAL-1_TC_020
title: Moving a wishlist item to the cart adds it and removes it from the wishlist
area: cart
priority: P0
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-02
task: LOCAL-1
covers: [R-21]
defect_class: data-loss
basis: "requirement:R-19"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-19"}, {"then": 2, "source": "unknown", "ref": "Q6"}, {"then": 3, "source": "unknown", "ref": "Q6"}]
question_thens: [{"question": "Q6", "then": 2, "readings": {"a": "the item is removed from the wishlist after a successful move", "b": "the item stays in the wishlist"}, "not_needed": ""}, {"question": "Q6", "then": 3, "readings": {"a": "when the add fails the item stays in the wishlist", "b": "when the add fails the item is removed"}, "not_needed": ""}]
plan_row: TS-21
reuse_reason: grep cart in tests/, core/, test-cases/ finds no file; new
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in seed user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI address", "check": {"stand_frontend": "the wishlist page is driven in the browser"}}, {"id": "PC-3", "kind": "data", "what": "two books on the wishlist: one in stock, one out of stock, created by the case", "check": {"case_seeds": "two uniquely marked books on the user's wishlist"}}]
---
Requirements: R-21
Plan row: TS-21

## Given
- PC-1, PC-2, PC-3. In-stock book W and out-of-stock book X are on the wishlist.

## When
1. Click "move to cart" for W.
2. Click "move to cart" for X (the add is refused).
3. Reload the wishlist page.

## Then
1. After step 1 `GET /api/cart` holds a line for W at its catalog price.
2. Under reading a of Q6, W is gone from the wishlist (read after reload, not from the page state before it); reading b follows the owner's answer.
3. Under reading a of Q6, X is still on the wishlist after the refused move and `GET /api/cart` holds no line for X: no item is lost.

## Notes (self-probe)
- Data-loss risk: the refused add must not delete the wishlist item; the refusal comes from the real stock rule, not a mocked failure.
- Wishlist state is read after a reload (independent of the click response). The wishlist API/page of the case's own user only.
- Thens 2 and 3 carry no literal until Q6 is answered.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-21 add on move | R-19 | GET /api/cart | Then 1 | none |
| OB-21 wishlist removal | Q6 | wishlist after reload | Then 2 | oracle unknown |
| OB-21 error keeps item | Q6 | wishlist + cart | Then 3 | oracle unknown |
