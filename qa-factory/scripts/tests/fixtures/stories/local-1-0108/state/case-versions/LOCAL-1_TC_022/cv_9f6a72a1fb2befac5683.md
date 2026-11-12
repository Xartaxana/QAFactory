---
id: LOCAL-1_TC_022
title: Adding a book while its price is updated charges the owner-defined price
area: cart
priority: P0
status: Draft
channel: manual-agent
reuse_decision: new
updated: 2026-11-02
task: LOCAL-1
covers: [R-24]
defect_class: concurrency
basis: "requirement:R-24"
then_oracles: [{"then": 1, "source": "unknown", "ref": "Q7"}, {"then": 2, "source": "requirement", "ref": "R-24"}]
question_thens: [{"question": "Q7", "then": 1, "readings": {"now": "the cart line and subtotal use the price shown on the page when the add was made (Q4 = a)", "before": "the cart line and subtotal use the updated price and the shopper is told of the change (Q4 = b)"}, "not_needed": ""}]
plan_row: TS-24
reuse_reason: grep cart in tests/, core/, test-cases/ finds no price-update case; new
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in seed user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI address", "check": {"stand_frontend": "the product page is opened in the browser"}}, {"id": "PC-3", "kind": "account", "what": "an admin account that can update a book price", "check": {"stand_account": "admin"}}, {"id": "PC-4", "kind": "data", "what": "an in-stock book with a known price, created by the case", "check": {"case_seeds": "one uniquely marked book at price 10.00"}}]
---
Requirements: R-24
Plan row: TS-24

Manual evidence policy (copied from the plan row, OB-24): `evidence_policy: api`; required phases before and after; completion condition: both actions settled (the add answered and the price update answered). Disposition applies once Q4 is answered (reading a or b settles the expected price); until then the row stays `unverifiable`.

## Given
- PC-1, PC-2, PC-3, PC-4. The marked book B costs 10.00; the user's cart holds no line for B.

## When
1. Before phase: record `GET /api/books/<B>` price and `GET /api/cart` (no line for B).
2. As the user open the product page of B (page shows 10.00).
3. As admin update the price of B to 12.00 through the API; wait for the answer.
4. As the user click "Add to Cart" on the still-open page.
5. After phase: record the add response, `GET /api/cart` and `GET /api/books/<B>`.
Actual steps and each request/response (secret-free) are captured as evidence.

## Then
1. If Q4 = a: the cart line for B is priced 10.00 (the price shown) and subtotal equals 10.00 x quantity; if Q4 = b: the line is priced 12.00 and the shopper is told of the change. No literal is asserted before Q4 is answered.
2. The add causes no error: the add response is a 2xx or a visible message, not an unhandled 5xx, and the line price equals one of the two prices (10.00 or 12.00), never a third value or zero. Cart is read from `GET /api/cart` after both actions settled, for B only.

## Notes (self-probe)
- The two prices differ (10.00 vs 12.00) so stale-price and fresh-price outcomes are distinguishable; the cart is read through the API, independent of the page.
- The update is sequenced before the click (a deterministic ordering of the race, not a true parallel race); a true simultaneous race is not claimed (residual gap).
- Evidence incomplete (missing before or after) is `inconclusive`, not pass.
- Cleanup: restore B's price, remove the line; only the marked book is touched.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-24 price charged | Q4 | cart and total after both actions | Then 1 | oracle unknown until Q4 |
| OB-24 no error | R-24 | add response, cart | Then 2 | true parallel race not staged |
