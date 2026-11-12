---
id: LOCAL-1_TC_013
title: Badge equals the sum of quantities and the total equals the sum of price x quantity
area: cart
priority: P0
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-05
task: LOCAL-1
covers: [R-11]
defect_class: state
basis: consistency:work/requirements-register.md Behaviour claims R-11 (before unknown, now badge is the sum of quantities)
preconditions: [{"id": "PC-1", "kind": "service", "what": "the stand UI is reachable", "check": {"stand_frontend": "the case reads badge and cart page"}}, {"id": "PC-2", "kind": "data", "what": "two marked books with known prices and stock >= 4", "check": {"case_seeds": "the case seeds books A and B with distinct prices and its own guest session"}}]
then_oracles: [{"then": 1, "source": "unknown", "ref": "Q4"}, {"then": 2, "source": "unknown", "ref": "Q4"}, {"then": 3, "source": "unknown", "ref": "Q4"}]
question_thens: [{"question": "Q4", "then": 1, "readings": {"now": "badge 3 and total 2*priceA + priceB after adding 2 of A and 1 of B", "before": "the badge and total the person names"}, "not_needed": ""}, {"question": "Q4", "then": 2, "readings": {"now": "badge 4 and total updated after adding A again", "before": "the badge and total the person names"}, "not_needed": ""}, {"question": "Q4", "then": 3, "readings": {"now": "after a quantity change and a line removal the badge and total follow the stored cart", "before": "the badge and total the person names"}, "not_needed": ""}]
---

Requirements: R-11
Plan row: TS-13

## Given
A guest with an empty cart; books A and B with known prices (marked records).

## Steps
1. Add 2 of A and 1 of B. Read the badge and the cart page total; compute the expected sum from the prices set by the case and GET /api/cart.
2. Add A again.
3. On the cart page change a quantity, then remove one line.

## Then
1. P-lines-vs-units: the badge and total after step 1 equal the values Q4 gives, computed from the seeded prices (a badge counting lines gives 2 and fails).
2. After adding A again the badge and total equal the values Q4 gives.
3. After the quantity change and the removal the badge and the total equal the values Q4 gives, and both agree with GET /api/cart.

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-13 | badge | Q4 | units vs lines | 1-3 | rounding of totals not stated |
| OB-13 | total | Q4 | price x quantity | 1-3 | |
