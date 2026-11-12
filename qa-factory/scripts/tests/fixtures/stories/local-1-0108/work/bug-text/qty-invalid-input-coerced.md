# Invalid quantities (0, -1, 1.5, abc) are rewritten to a valid number and added to the cart instead of being rejected

Impact: degraded - priority P2

## Steps to see it
1. Sign in and open the product page of an in-stock book
2. Type 0 into the quantity field and click Add to Cart; then open the cart page and watch the message area and the quantity field
3. Repeat with -1
4. Repeat with 1.5
5. Repeat with abc (the field may only accept it as a number input; use paste or keyboard entry)

## Expected
R-8 (0), R-9 (-1, 1.5), R-10 (abc): each value is rejected with a clear message, nothing is added to the cart, the field keeps the typed value

## What was seen
One root cause, BookDetailPage.tsx:164 setQuantity(Math.max(1, parseInt(v) || 1)): the invalid input is rewritten and the add proceeds with no message. Observed per input: 0 -> field shows 1, cart line quantity 1; -1 -> field shows 11, cart line quantity 1; 1.5 -> field shows 1, cart line quantity 1; abc -> field shows 1, cart line quantity 1.

## How sure the factory is
unconfirmed — nobody has reproduced it; it counts toward nothing
