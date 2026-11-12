# QA-1 — understanding

## Why this change

Checkout accepted any discount percentage and did not tell the shopper why a coupon was
refused.

## What we verify

- R-1 — a coupon above the cap is refused with DISCOUNT_TOO_LARGE
- R-2 — the refusal is shown without losing the cart
- R-3 — an expired coupon is refused with COUPON_EXPIRED

## What we do not verify, and why

- nothing else was cut

## What else the change may touch

- the refund calculation, which reads the discounted total
- the coupon admin screen, which shares the cap constant

## Questions without which testing is pointless

- Q1 — is the cap a product rule or a temporary guard?
