# LOCAL-1 — understanding

## Why this change

No code changes: a requirements-driven check of "Add to Cart" in MyBooks for guests and signed-in shoppers; every add path and scenario. The requirement is the oracle, not the code.

## Size

L (6 functions) · cap 28 · budget 50 · overage 22 · unverifiable 4

## What we verify

- R-1, R-2, R-3 — AC: add qty 1, out-of-stock message, qty 3 with subtotal
- R-4 — cart price matches product page and backend
- R-5, R-6 — guest cart survives browser restart; user cart survives logout/login
- R-7 — success message and badge count after add
- R-8 — quantity 0 rejected (UI turns 0 into 1: bug candidate)
- R-9, R-10 — -1, 1.5, "abc" rejected, not coerced (bug candidates)
- R-11, R-12 — above stock rejected; stock check counts the cart
- R-13 — valid classes added exactly: 1, 10, 234, with zeros, multi-digit, = stock
- R-14, R-15, R-16, R-17 — maximum and huge quantity; same product twice; several products
- R-18 — unknown book refused (404)
- R-19, R-20, R-21 — catalog card and wishlist move obey the same rules
- R-22 — guest cart merge at sign-in (code behaviour, no requirement)

## What we do not verify, and why

- R-23 — quick view: no implementation, no steps; out of scope unless it adds to cart
- R-24, R-25, R-26 — price race, network cut, session expiry: steps not authored, no code observable

## What else the change may touch

- Cart page quantity edit (REF-9): excluded, a cart edit
- Checkout reads cart quantities and prices; login runs the guest cart merge

## Questions without which testing is pointless

- Q1 — UI turns 0, -1, 1.5, "abc" into 1; requirement says reject (person: requirement is the oracle)
- Q4 — expected results of quick view, price race, network and session cases are not authored
