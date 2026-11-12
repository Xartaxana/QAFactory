---
id: LOCAL-1_TC_007
title: Re-adding a book sums into one cart item and answers 201
area: cart
priority: P0
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-05
task: LOCAL-1
covers: [R-5]
defect_class: state
basis: external:MyBooks/docs/openapi.json
preconditions: [{"id": "PC-1", "kind": "data", "what": "a marked book with stock >= 5", "check": {"case_seeds": "the case seeds a marked book and its own guest session"}}]
then_oracles: [{"then": 1, "source": "unknown", "ref": "Q4"}, {"then": 2, "source": "unknown", "ref": "Q4"}, {"then": 3, "source": "unknown", "ref": "Q4"}]
question_thens: [{"question": "Q4", "then": 1, "readings": {"now": "the first add answers 201", "before": "the status the person names"}, "not_needed": ""}, {"question": "Q4", "then": 2, "readings": {"now": "the second add of the same book answers 201 (openapi: quantity is added to what is in the cart)", "before": "the status the person names"}, "not_needed": ""}, {"question": "Q4", "then": 3, "readings": {"now": "GET /api/cart holds one line for the book with quantity 5", "before": "the cart state the person names"}, "not_needed": ""}]
---

Requirements: R-5
Plan row: TS-7

## Given
A guest with an empty cart; book A with stock >= 5.

## Steps
1. POST /api/cart {bookId: A, quantity: 2}.
2. POST /api/cart {bookId: A, quantity: 3}.
3. GET /api/cart.

## Then
1. P-first: the first add answers the status that Q4 gives for a new cart line.
2. P-readd: the second add of the same book answers the status that Q4 gives for a re-add.
3. P-readback: GET /api/cart, read independently of both POST answers, holds the lines and quantities that Q4 gives for 2 then 3 of one book.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-7 | sum into one item, 201 | openapi POST /api/cart via Q4 | 2 then 3 | 1-3 | sum above stock is TC_009 |
