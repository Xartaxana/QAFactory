# Non-numeric quantity (abc) becomes 1 and is added instead of being rejected

Impact: degraded - priority P2

## Steps to see it
1. Sign in and open the product page of an in-stock book
2. Type the value into the quantity field
3. Click Add to Cart
4. Open the cart page and watch the message area and the quantity field

## Expected
abc is rejected with an error, nothing is added

## What was seen
No message; a cart line with quantity 1 is added

## How sure the factory is
unconfirmed — nobody has reproduced it; it counts toward nothing
