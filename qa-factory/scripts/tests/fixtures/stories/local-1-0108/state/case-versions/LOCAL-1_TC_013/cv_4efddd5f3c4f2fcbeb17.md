---
id: LOCAL-1_TC_013
title: The maximum allowed quantity is added with the right subtotal
area: cart
priority: P2
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-02
task: LOCAL-1
covers: [R-14]
defect_class: boundary
basis: "requirement:R-14"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-14"}, {"then": 2, "source": "requirement", "ref": "R-14"}]
plan_row: TS-14
reuse_reason: grep cart in tests/, core/, test-cases/ finds no file; new
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in seed user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "data", "what": "a book with price P and stock 50 (below the 999 cap), created by the case", "check": {"case_seeds": "one uniquely marked book, stock 50"}}]
branches: [{"id": "BN-7", "then": 1}]
---
Requirements: R-14
Plan row: TS-14

## Given
- PC-1, PC-2. Empty cart for B (stock 50).

## When
1. `POST /api/cart` for B with quantity 50 (the stock level).
2. `GET /api/cart` and `GET /api/cart/total`.

## Then
1. The add is accepted and the line of B has quantity 50 (the stock boundary reading of "maximum allowed"; the 999 schema-cap reading is open question Q3 and is not asserted).
2. The unit price equals the catalog price P and the total equals 50 x P, computed in the test.

## Notes (self-probe)
- Stock 50 is below the 999 cap so stock and cap readings differ; this case asserts the stock boundary only.
- Quantity 999 with stock >= 999 is left for the owner's answer to Q3.
- Reads only the marked book's line and the fresh cart total.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-14 maximum accepted | R-14 | GET /api/cart | Then 1 | stock vs 999 cap (Q3, BN-7) |
| OB-14 price and subtotal | R-14 | cart + total | Then 2 | none |
