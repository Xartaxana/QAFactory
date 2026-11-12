---
id: LOCAL-1_TC_014
title: Walk - sign in with a guest cart, change it, sign out and in again
area: cart
priority: P0
status: Draft
channel: manual-agent
reuse_decision: new
updated: 2026-11-05
task: LOCAL-1
covers: [R-4]
defect_class: state
basis: requirement:R-4
preconditions: [{"id": "PC-1", "kind": "account", "what": "a stand user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI is reachable", "check": {"stand_frontend": "the walk drives the live stand"}}, {"id": "PC-3", "kind": "data", "what": "the stand user's account cart is empty before the walk", "check": {"case_seeds": "the walk empties the account cart of the stand user first"}}]
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-4"}, {"then": 2, "source": "requirement", "ref": "R-4"}, {"then": 3, "source": "requirement", "ref": "R-4"}]
---

Requirements: R-4
Plan row: TS-14

Evidence policy: ui; before/after captures of the cart page and badge at each step, plus the actual steps taken.

## Given
Account cart of the stand user empty. A guest with 2 marked books A (quantity 1) and B (quantity 2) in the cart; the stand user signed out. Level: UI sign-in path (merge rules are api-tested in TC_005; failed merge R-12 is TC_006).

## Steps
1. Sign in; read the cart page and the badge.
2. Change A to quantity 3; sign out; sign in again; read the cart and the badge.
3. Sign out, with an empty guest cart sign in again; read the cart.

## Then
1. After the first sign-in the account cart holds A with 1 and B with 2 (both guest books) and the badge is 3.
2. P-second-signin: after sign-out and sign-in the account cart holds A with 3 and B with 2 (nothing doubled: not 6/4), badge 5; the guest cart after sign-out holds neither book.
3. P-emptyguest: sign-in with an empty guest cart leaves the account cart as it was (A 3, B 2).

## Obligation coverage
| OB | part | oracle | boundary | Then | residual gap |
|---|---|---|---|---|---|
| OB-14 | walk of sign-in | R-4 | second sign-in | 1-3 | failure of merge (R-12) is TC_006 |
