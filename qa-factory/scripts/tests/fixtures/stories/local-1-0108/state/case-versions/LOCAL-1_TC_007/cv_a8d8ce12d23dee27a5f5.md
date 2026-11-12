---
id: LOCAL-1_TC_007
title: Quantity 0 is rejected with a message and nothing is added
area: cart
priority: P2
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-02
task: LOCAL-1
covers: [R-8]
defect_class: boundary
basis: "requirement:R-8"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-8"}, {"then": 2, "source": "requirement", "ref": "R-8"}, {"then": 3, "source": "requirement", "ref": "R-8"}]
plan_row: TS-8
reuse_reason: grep cart in tests/, core/, test-cases/ finds no file; new. Instance of LOCAL-1_TC_012 (P-zero) kept as its own case for the bug REF-2
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in seed user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI address", "check": {"stand_frontend": "product page is driven in the browser"}}, {"id": "PC-3", "kind": "data", "what": "an in-stock book with stock 10, created by the case", "check": {"case_seeds": "one uniquely marked in-stock book"}}]
branches: [{"id": "BN-2", "then": 1, "partition": "P-zero"}]
---
Requirements: R-8
Plan row: TS-8

red_lock: expected red until the product page stops turning 0 into 1 (REF-2, owner-confirmed expected behaviour: 0 is rejected). Proof of the gap, not a broken case.

## Given
- PC-1, PC-2, PC-3. Empty cart (fresh user or the marked book absent).

## When
1. Open the product page of B.
2. Enter 0 into the quantity field as a whole value, click "Add to Cart".

## Then
1. P-zero: a visible message states that the quantity is invalid / must be at least 1.
2. `GET /api/cart` holds no line for B (nothing added), read after the click completes (message shown or request answered).
3. The quantity field still shows "0" whole (the UI did not turn it into 1) and keeps focus.

## Notes (self-probe)
- The discriminating input is 0; the observed code coerces it to 1 and adds a copy, so Then 2 fails there (seeded defect = current behaviour).
- Negative proof reads the API after completion, independent of the UI message.
- Oracle is the requirement, not the code; no title on the defective behaviour.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-8 message | R-8 | page text | Then 1 | exact wording not specified ("clear message") |
| OB-8 nothing added | R-8 | GET /api/cart | Then 2 | none |
| OB-8 no coercion | R-8 | input value | Then 3 | none |
