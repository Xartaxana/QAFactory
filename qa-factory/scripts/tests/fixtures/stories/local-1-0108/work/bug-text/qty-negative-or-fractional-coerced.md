# Quantity -1 and 1.5 are rewritten to a valid number and added instead of being rejected

Impact: degraded - priority P2

## Steps to see it
1. Sign in and open the product page of an in-stock book
2. Type the value into the quantity field
3. Click Add to Cart
4. Open the cart page and watch the message area and the quantity field

## Expected
-1 and 1.5 are rejected with a message, nothing is added, the field keeps the typed value

## What was seen
No message; a cart line with quantity 1 is added (field shows 11 for -1, 1 for 1.5)

## How sure the factory is
unconfirmed — nobody has reproduced it; it counts toward nothing
