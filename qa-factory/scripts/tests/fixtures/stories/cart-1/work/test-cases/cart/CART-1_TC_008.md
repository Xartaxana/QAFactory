---
id: CART-1_TC_008
title: Another owner's cart item cannot be changed or removed and the owner's cart stays unchanged
area: cart
priority: P0
status: Draft
channel: auto
reuse_decision: new
updated: 2026-10-31
task: CART-1
covers: [R-12]
defect_class: permission
basis: "requirement:R-12"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-12"}, {"then": 2, "source": "requirement", "ref": "R-12"}, {"then": 3, "source": "requirement", "ref": "R-12"}, {"then": 4, "source": "requirement", "ref": "R-12"}, {"then": 5, "source": "requirement", "ref": "R-12"}]
plan_row: TS-8
reuse_reason: grep cart in tests/ 0 hits; no existing case in the store
preconditions: [{"id": "PC-1", "kind": "data", "what": "own book with stock 10 and two own registered users A and B, created by the case", "check": {"case_seeds": "own book, users A and B"}}]
---
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
