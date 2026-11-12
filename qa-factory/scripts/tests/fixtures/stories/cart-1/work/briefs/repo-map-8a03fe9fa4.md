# Repo map - cart (CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004, CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008, CART-1_TC_009, CART-1_TC_010)

Test roots: `tests`. Nouns from the cases' Given/When: bookid, cart, quantity, stock, cookie, post, guest, session, book, r_a, bookstore, bookstore_session_id, empty, secret, signed, through.

## Existing tests of the area

- `tests/api/cart/cart-quote-order.spec.ts` (2,932 B, matched by area): not a Python file: its test names are not listed
- `tests/e2e/cart/add-to-cart.spec.ts` (1,945 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/cart-merge.spec.ts` (1,981 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/cart-isolation.spec.ts` (1,147 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-stock-limit.spec.ts` (1,211 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-boundaries.spec.ts` (2,488 B, matched by area): not a Python file: its test names are not listed

## Fixtures (conftest) - 0 of 0, ranked by the nouns

- no conftest.py fixture found under the test roots

## Utils, page objects and test data, ranked

- no helper module matched the nouns

## How a test is written here - `tests/api/cart/cart-quote-order.spec.ts`, first 54 lines

```typescript
import { test, expect } from '../../../core/fixtures/cartApi.fixture';

type Line = { bookId: number; quantity: number };
const linesOf = (body: any, key = 'items'): Line[] =>
  ((body?.[key] ?? []) as any[]).map((i) => ({ bookId: i.bookId ?? i.book?.id, quantity: i.quantity }));
const byBook = (a: Line, b: Line) => a.bookId - b.bookId;

// qa(case=CART-1_TC_009, then=[1,2,3,4,5], obligations=[OB-9], shape=new)
test('@api @regression CART-1_TC_009 quote and order from cart', async ({ ownBooks, verifiedUser }) => {
  const me = verifiedUser.api;
  const b1 = await ownBooks.create(5);
  const b2 = await ownBooks.create(5);
  const expected: Line[] = [
    { bookId: b1, quantity: 2 },
    { bookId: b2, quantity: 1 },
  ].sort(byBook);

  const empty = await me.quote();

  await me.add({ bookId: b1, quantity: 2 });
  await me.add({ bookId: b2, quantity: 1 });
  const cartRows = (await me.rows()).map((r) => ({ bookId: r.bookId, quantity: r.quantity })).sort(byBook);
  const quote = await me.quote();

  await ownBooks.setStock(b1, 1);
  const over = await me.quote();

  await ownBooks.setStock(b1, 5);
  const order = await me.order({ name: 'QA Cart', email: verifiedUser.email, address: '1 Test Street' });
  const afterOrder = (await me.rows()).filter((r) => r.bookId === b1 || r.bookId === b2);

  // Then 1
  expect.soft([400, 409, 422], 'Then 1: empty-cart quote is rejected 400/409/422').toContain(empty.status);
  expect.soft(empty.body?.error, 'Then 1: body carries error').toBeTruthy();
  expect.soft(empty.body?.code, 'Then 1: body carries code').toBeTruthy();
  expect.soft(linesOf(empty.body), 'Then 1: no quote items issued').toEqual([]);
  // Then 2
  expect.soft(quote.status, 'Then 2: quote of the filled cart succeeds').toBeLessThan(300);
  expect.soft(cartRows, 'Then 2: cart read holds B1 x2 and B2 x1').toEqual(expected);
  // Then 3
  expect.soft([400, 409, 422], 'Then 3: over-stock quote is rejected 400/409/422').toContain(over.status);
  expect.soft(over.body?.error, 'Then 3: body carries error').toBeTruthy();
  expect.soft(over.body?.code, 'Then 3: body carries code').toBeTruthy();
  expect.soft(JSON.stringify(over.body), 'Then 3: body identifies B1').toContain(ownBooks.titleOf(b1));
  expect.soft(linesOf(over.body), 'Then 3: no quote items issued').toEqual([]);
  // Then 4
  expect.soft(order.status, 'Then 4: order succeeds 2xx').toBeGreaterThanOrEqual(200);
  expect.soft(order.status, 'Then 4: order succeeds 2xx').toBeLessThan(300);
  expect.soft(linesOf(order.body, 'orderItems').sort(byBook), 'Then 4: order items B1 x2 and B2 x1').toEqual(expected);
  // Then 5
  expect.soft(afterOrder, 'Then 5: no cart row for B1 or B2 after the order').toEqual([]);
  // Then 2 (the red check last: soft asserts keep Thens 1, 3, 4 and 5 evaluated either way)
  expect.soft(linesOf(quote.body).sort(byBook), 'Then 2: quote lists B1 x2 and B2 x1, equal to the cart read').toEqual(cartRows);
});
```

Read what is named here with `offset`/`limit`; search the repository only when this map is empty.
