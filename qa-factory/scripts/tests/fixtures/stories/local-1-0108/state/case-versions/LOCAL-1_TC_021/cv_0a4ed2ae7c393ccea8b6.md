---
id: LOCAL-1_TC_021
title: A guest cart is merged at sign-in without losing items
area: cart
priority: P0
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-02
task: LOCAL-1
covers: [R-22]
defect_class: data-loss
basis: "requirement:R-6"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-6"}, {"then": 2, "source": "unknown", "ref": "Q6"}, {"then": 3, "source": "unknown", "ref": "Q6"}]
question_thens: [{"question": "Q6", "then": 2, "readings": {"a": "for a book in both carts the higher quantity wins", "b": "the quantities are summed or another rule the owner names"}, "not_needed": ""}, {"question": "Q6", "then": 3, "readings": {"a": "the merged quantity is capped at stock and a no-stock item is dropped", "b": "another cap rule the owner names"}, "not_needed": ""}]
plan_row: TS-22
reuse_reason: grep cart in tests/, core/, test-cases/ finds no file; new
preconditions: [{"id": "PC-1", "kind": "account", "what": "a seed user to sign in as", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI address", "check": {"stand_frontend": "the login page is driven in the browser"}}, {"id": "PC-3", "kind": "data", "what": "books G (guest-only), H (in both carts) and Z (will lose all stock), created by the case", "check": {"case_seeds": "three uniquely marked books"}}]
---
Requirements: R-22
Plan row: TS-22

## Given
- PC-1, PC-2, PC-3. As a guest: G x1, H x2, Z x1 added. The signed-in user's cart already holds H x4 (stock of H is 10). Z's stock is then set to 0 by the case before the login.

## When
Sign in as the user through the UI login page (the guest cookie still present), then open the cart.

## Then
1. G is in the user's cart (the guest item is not lost) at quantity 1; `GET /api/cart` as the signed-in user shows it.
2. Under reading a of Q6, H has quantity 4 (higher of 2 and 4 wins, not 6); reading b follows the owner's answer.
3. Under reading a of Q6, Z is absent (no stock, dropped) and no line has a quantity above its stock.

## Notes (self-probe)
- 2 and 4 are chosen so max (4), sum (6) and replace-by-guest (2) differ.
- Then 1 is the data-loss floor; it rests on R-6 (cart persists across login). Rules of winner and cap are code claims awaiting Q6.
- Only the three marked books are read.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-22 guest item kept | R-6 | GET /api/cart after login | Then 1 | none |
| OB-22 winner rule | Q6 | GET /api/cart | Then 2 | oracle unknown |
| OB-22 cap and drop | Q6 | GET /api/cart | Then 3 | oracle unknown |
