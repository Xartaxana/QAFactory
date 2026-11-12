---
id: CART-1_TC_006
title: Guest cart merge keeps the higher quantity, caps at stock and drops stock 0 rows
area: cart
priority: P0
status: Draft
channel: auto
reuse_decision: new
updated: 2026-10-31
task: CART-1
covers: [R-8]
defect_class: data-loss
basis: "requirement:R-8"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-8"}, {"then": 2, "source": "requirement", "ref": "R-8"}, {"then": 3, "source": "requirement", "ref": "R-8"}, {"then": 4, "source": "requirement", "ref": "R-8"}, {"then": 5, "source": "requirement", "ref": "R-8"}, {"then": 6, "source": "requirement", "ref": "R-8"}]
plan_row: TS-6
reuse_reason: CAND-1 src/lib/cartRules.test.ts:5 covers mergedQuantity arithmetic only (partial); route and transaction undefended; grep cart in tests/ 0 hits
preconditions: [{"id": "PC-1", "kind": "data", "what": "own books and an own registered user created by the case; one book later set to stock 0 through the test seed endpoint", "partitions": ["P-soldout"], "check": {"case_seeds": "own books, own user"}}, {"id": "PC-2", "kind": "env", "what": "test seed endpoint secret (x-test-secret) needed to lower stock after the guest rows exist", "partitions": ["P-cap", "P-soldout"], "check": {"env": "TEST_SECRET"}}]
---
Requirements: R-8
Plan row: TS-6

Obligation: OB-6

## Given
- Own user U (registered, own cookie jar, signed in). Guest jar G.
- Own books, all created with stock 10: B1, B2, B3, B4, B5.
- U's cart already holds: B1 x5, B2 x1.
- G's cart holds: B1 x2, B2 x4, B3 x6, B4 x1, B5 x2 (all added while stock is 10). Then, through the test seed endpoint (x-test-secret from TEST_SECRET, PC-2), B3 stock is lowered from 10 to 3 and B4 stock from 10 to 0.
  Note: if the seed endpoint cannot lower stock, the case is `blocked_by_env`.

## When
1. Call POST /api/cart/merge with U's session and the guest cookie of G.
2. GET /api/cart as U.
3. POST /api/cart/merge with no session (guest only).

## Then
1. P-overlap-higher-guest: B2 in U's cart has quantity 4 (guest 4 over user 1: max, not sum 5).
2. P-overlap-higher-user: B1 in U's cart has quantity 5 (user 5 over guest 2: max, not sum 7).
3. P-cap: B3 in U's cart has quantity 3 (guest 6 capped at stock 3).
4. P-soldout: U's cart has no row for B4.
5. P-disjoint: B5 is in U's cart with quantity 2; U's cart contains exactly the rows B1 x5, B2 x4, B3 x3, B5 x2 (and no row for B4).
6. P-unauth: the merge without a session answers 401.

## Self-probe notes
- Data distinguishes max from sum from replace in both directions; the stock cap and drop are separate partitions.
- Read-back is a fresh GET /api/cart as U, independent of the merge response; completion = merge responded before the read.
- Seed is not precomputed: stock changes are applied after the guest rows exist, so the merge, not the add path, enforces the cap.
- CAND-1 only proves arithmetic; transaction and persistence are what this case defends.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-6 higher quantity not sum | R-8 | merge then GET /api/cart | Then 1, 2 | none |
| OB-6 cap at stock | R-8 | merge then GET /api/cart | Then 3 | none |
| OB-6 stock 0 dropped | R-8 | merge then GET /api/cart | Then 4 | none |
| OB-6 disjoint kept | R-8 | merge then GET /api/cart | Then 5 | none |
| OB-6 auth | R-8 | merge response | Then 6 | none |
