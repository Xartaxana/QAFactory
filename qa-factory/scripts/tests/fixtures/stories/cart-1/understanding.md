# CART-1 — understanding
## Why this change
No code changes: the requester asks for a verification of the whole "Add to Cart" functionality of MyBooks, finding every way a book gets into the cart and every scenario of its use, for shoppers (guest and signed-in) before checkout.
## Size
XXL · cap 28 · budget 32 · overage 4 · unverifiable 3 (R-9, R-13, R-16); budget above the XL cap, so splitting into several stories is recommended.
## What we verify
- R-1 — every entry path into the cart (card, detail, wishlist move, API, merge) works
- R-2 — every usage scenario (guest, signed-in, stock edges, quantity, remove, badge)
- R-3 — unknown book 404, out of stock 400, disabled buttons
- R-4 — quantity never exceeds stock; equal to stock allowed
- R-5 — repeat add increments the one row
- R-6 — quantity 1..999 and bookId validation, stable error shape
- R-7 — guest cookie cart separate from the account cart
- R-8 — merge at sign-in: higher quantity wins, capped at stock
- R-10 — cart badge equals the sum of quantities
- R-11 — change quantity respects stock; remove deletes
- R-12 — another owner's item answers 404 and stays untouched
- R-14 — wishlist move-to-cart adds and removes
- R-15 — checkout reads the cart; order clears it (read-side only)

## What we do not verify, and why
- R-9 — guest cart after registration: no source says what is expected (Q2)
- R-13 — cart page NaN and unchecked fetches: expected behaviour unconfirmed (Q3)
- R-16 — concurrent add race: no observable, needs the schema and a concurrency harness (Q4)

## What else the change may touch
- Checkout and orders — they read and clear the cart
- Login and registration — merge is called only from the login page
- Wishlist — move-to-cart shares the add path
- Book stock and admin editing — stock changes alter cart limits
- Session cookie bookstore_session_id — created even by a GET

## Questions without which testing is pointless
- Q1 — no requirements beyond two generic ACs: may current code plus AUTH.md and openapi be the oracle?
- Q2 — should a guest cart survive registration followed by login?
- Q3 — expected cart page behaviour for an emptied quantity input and a failed fetch?
- Q4 — is the concurrent-add race in scope, and what is expected?
