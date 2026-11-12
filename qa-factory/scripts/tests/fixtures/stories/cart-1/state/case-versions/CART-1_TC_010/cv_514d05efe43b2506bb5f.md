---
id: CART-1_TC_010
title: A signed-in shopper adds a book from the catalog card and sees it in the badge and on the cart page
area: cart
priority: P1
status: Draft
channel: auto
reuse_decision: new
updated: 2026-10-31
task: CART-1
covers: [R-1, R-2, R-10]
defect_class: seam
basis: "requirement:R-1"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-1"}, {"then": 2, "source": "requirement", "ref": "R-10"}, {"then": 3, "source": "requirement", "ref": "R-2"}]
plan_row: TS-10
reuse_reason: grep cart in tests/ 0 hits; no existing e2e case in the store
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in seed user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "data", "what": "an own in-stock book with a unique title visible in the catalog", "check": {"case_seeds": "own book with stock 5"}}]
---
Requirements: R-1, R-2, R-10
Plan row: TS-10

Obligation: OB-10

## Given
- Seed user U signed in through the UI, cart emptied through the API first. Own book B (stock 5, unique title) is listed in the catalog.

## When
1. Open the catalog and locate the card of B.
2. Click its add-to-cart-button once.
3. Wait for the add call response (completion).
4. Read the cart badge, then open the cart page.

## Then
1. The add call for B completes successfully (2xx) after the click.
2. The cart badge text equals the sum of quantities in the cart, 1.
3. The cart page lists B (by its unique title) with quantity 1; the content, not just the page visibility, is asserted.

## Self-probe notes
- Badge value is cross-read against the cart page rows, an independent channel. Cart cleaned first so the sum is not inherited from other data; rows read only for B's title.
- Oracle R-1 / R-10 / R-2 (current-code derived, Q1 open). Detail-page and wishlist paths are manual rows TS-11, TS-12.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-10 card add succeeds | R-1 | add call response | Then 1 | detail page, wishlist in TS-11, TS-12 |
| OB-10 badge sum | R-10 | UI badge | Then 2 | refresh on session change not covered |
| OB-10 cart page content | R-2 | cart page rows | Then 3 | none |
