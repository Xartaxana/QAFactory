---
id: LOCAL-1_TC_006
title: A signed-in cart survives logout and login
area: cart
priority: P2
status: Draft
channel: auto
reuse_decision: new
updated: 2026-11-02
task: LOCAL-1
covers: [R-6]
defect_class: state
basis: "requirement:R-6"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-6"}, {"then": 2, "source": "requirement", "ref": "R-6"}]
plan_row: TS-6
reuse_reason: grep cart in tests/, core/, test-cases/ finds no file; login specs exist but none touch the cart; new
preconditions: [{"id": "PC-1", "kind": "account", "what": "a seed user to sign in as", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI address", "check": {"stand_frontend": "login and logout are driven in the browser"}}, {"id": "PC-3", "kind": "data", "what": "an in-stock book, created by the case", "check": {"case_seeds": "one uniquely marked in-stock book"}}]
---
Requirements: R-6
Plan row: TS-6

## Given
- PC-1, PC-2, PC-3. The user is signed in; the case first removes any line of its own book.

## When
1. Add B with quantity 2 from the product page.
2. Log out through the UI, then log in again as the same user.
3. Open the cart page.

## Then
1. After login the cart page shows B with quantity 2.
2. `GET /api/cart` (signed in again) holds the line of B with quantity 2 and no second line for B.

## Notes (self-probe)
- Logout in between means a session-bound cart (owner = guest cookie) would lose the line: red when cart ownership is wrong.
- The user's other cart lines are ignored (shared seed user): only the marked B line is read.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-6 cart persists across logout/login | R-6 | cart page and GET /api/cart | Then 1, 2 | none |
