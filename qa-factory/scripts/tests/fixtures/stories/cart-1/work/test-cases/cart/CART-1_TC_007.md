---
id: CART-1_TC_007
title: Changing a cart quantity sets it within stock, rejects above stock, and removing deletes the row
area: cart
priority: P2
status: Draft
channel: auto
reuse_decision: new
updated: 2026-10-31
task: CART-1
covers: [R-11]
defect_class: boundary
basis: "requirement:R-11"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-11"}, {"then": 2, "source": "requirement", "ref": "R-11"}, {"then": 3, "source": "requirement", "ref": "R-11"}, {"then": 4, "source": "requirement", "ref": "R-11"}]
plan_row: TS-7
reuse_reason: grep cart in tests/ 0 hits; no existing case in the store
preconditions: [{"id": "PC-1", "kind": "data", "what": "an own book with stock 5, created by the case", "check": {"case_seeds": "own book with stock 5"}}]
---
Requirements: R-11
Plan row: TS-7

Obligation: OB-7

## Given
- Guest jar with cart row for own book B (stock 5), quantity 1; the row id is read from GET /api/cart.

## When
1. PUT /api/cart/<row id> { quantity: 5 } (partition P-set-equal).
2. GET /api/cart.
3. PUT /api/cart/<row id> { quantity: 6 } (partition P-over).
4. GET /api/cart.
5. DELETE /api/cart/<row id> (partition P-delete).
6. GET /api/cart.

## Then
1. P-set-equal: PUT succeeds (2xx) and the read-back row for B has quantity 5 (set, not added to 1).
2. P-over: PUT answers 400 INSUFFICIENT_STOCK.
3. After P-over the read-back row for B still has quantity 5.
4. P-delete: DELETE succeeds and the final GET /api/cart has no row for B.

## Self-probe notes
- Boundary pair stock / stock+1; start quantity 1 distinguishes set from add (1+5 would be 6).
- All state Thens read via GET /api/cart, not the PUT/DELETE response. Oracle R-11; Q1 open.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-7 set within stock | R-11 | PUT + GET | Then 1 | none |
| OB-7 above stock rejected | R-11 | PUT + GET | Then 2, 3 | none |
| OB-7 delete | R-11 | DELETE + GET | Then 4 | none |
