# Quantity 0 is turned into 1 and added instead of being rejected

Impact: degraded - priority P2

## Steps to see it
1. Sign in and open the product page of an in-stock book
2. Type the value into the quantity field
3. Click Add to Cart
4. Open the cart page and watch the message area and the quantity field

## Expected
0 is rejected with a clear message, nothing is added, the field keeps 0

## What was seen
No message; the field shows 1 and the cart holds one line with quantity 1 (setQuantity(Math.max(1, parseInt(v) || 1)))

## How sure the factory is
unconfirmed — nobody has reproduced it; it counts toward nothing
