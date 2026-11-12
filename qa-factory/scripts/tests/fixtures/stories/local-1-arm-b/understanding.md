# LOCAL-1 — understanding

## Why this change

No change is made: the task is to check "Add to Cart" on the current code, every path a book takes into the cart and the rules around it, for shoppers and guests.

## Size

L (7 functions) · cap 28 · budget 36 · overage 8 · unverifiable 0

## What we verify

- R-1 — add from a catalog card: success message and badge
- R-2 — add from the book page with a quantity; out-of-stock button
- R-3 — Move to cart from the wishlist
- R-4 — guest cart merged at sign-in: higher quantity wins, capped at stock
- R-5 — adding an existing book sums the quantity
- R-6 — quantity 1..999 whole, bookId positive
- R-7 — OUT_OF_STOCK and INSUFFICIENT_STOCK, counting what is in the cart
- R-8 — unknown book gives 404 BOOK_NOT_FOUND
- R-9 — guest and user carts stay separate
- R-10 — quantity change on the cart page never exceeds stock
- R-11 — cart badge and total follow the cart
- R-12, R-13, R-14 — a failed call is not shown as success (merge, wishlist move, cart page)

## What we do not verify, and why

- Clearing the cart, removing an item, orders and checkout — not ways into the cart.
- Existing stories, cases and bugs of REF-1 — not reachable; you said they are not needed.

## What else the change may touch

- Cart badge in the header (AppProviders) — re-read after each add.
- Wishlist — Move to cart also deletes the wishlist entry.
- Sign-in — merge runs right after login.
- Stock shown on the catalog and book page.

## Questions without which testing is pointless

- No blockers. Three minor questions are in the readiness file (Q1 failed-call norm, Q2 PUT or PATCH, Q3 moving a book already in the cart); testing goes on with the default readings.
