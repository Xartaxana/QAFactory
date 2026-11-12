# QA-1 — understanding

## Why this change

Checkout accepted any discount percentage, so a mistyped coupon could zero an order. The
change adds a cap and recalculates the total for every accepted coupon.

## What we verify

- R-1 — a coupon above the cap is refused with DISCOUNT_TOO_LARGE, not silently clamped
- R-2 — the cart total after a coupon matches the recalculated value, read from the order

## What we do not verify, and why

- R-3 — focus behaviour after a rejected submit: cosmetic, and the change does not touch
  the form's focus handling

## What else the change may touch

- cart totals shown in the order summary — the same recalculation path
- the refund calculation, which reads the discounted total
- the coupon admin screen, which shares the cap constant

## Questions without which testing is pointless

- Q1 — is the cap 50 percent a product rule or a temporary guard? It decides whether the
  boundary row is permanent coverage or a throwaway check.
