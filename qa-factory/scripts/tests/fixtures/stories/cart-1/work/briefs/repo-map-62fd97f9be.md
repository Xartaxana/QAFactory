# Repo map - cart (CART-1_TC_001, CART-1_TC_002, CART-1_TC_003, CART-1_TC_004)

Test roots: `tests`. Nouns from the cases' Given/When: bookid, cart, quantity, post, stock, cookie, book, guest, empty, fraction, zero, equal, exist, existing, larger, marker.

## Existing tests of the area

- `tests/api/cart/add-stock-limit.spec.ts` (1,211 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-rejections.spec.ts` (1,124 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-boundaries.spec.ts` (2,488 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-accumulate.spec.ts` (639 B, matched by area): not a Python file: its test names are not listed

## Fixtures (conftest) - 0 of 0, ranked by the nouns

- no conftest.py fixture found under the test roots

## Utils, page objects and test data, ranked

- no helper module matched the nouns

## How a test is written here - `tests/api/cart/add-stock-limit.spec.ts`, first 25 lines

```typescript
import { test, expect } from '../../../core/fixtures/cartApi.fixture';

// qa(case=CART-1_TC_002, then=[1,2,3,4], obligations=[TS-2-O1], shape=new)
test('@api @regression CART-1_TC_002 add beyond stock rejected', async ({ ownBooks, guest }) => {
  const stock = 5;
  const cart = await guest();
  const book = await ownBooks.create(stock);

  await cart.add({ bookId: book, quantity: 3 });
  const equal = await cart.add({ bookId: book, quantity: 2 });
  const plusOne = await cart.add({ bookId: book, quantity: 1 });
  const rows = (await cart.rows()).filter((r) => r.bookId === book);

  // Then 1
  expect(equal.status, 'Then 1: add up to exactly stock is 2xx').toBeGreaterThanOrEqual(200);
  expect(equal.status, 'Then 1: add up to exactly stock is 2xx').toBeLessThan(300);
  // Then 2
  expect(plusOne.status, 'Then 2: stock + 1 answers 400').toBe(400);
  expect(plusOne.body.code, 'Then 2: code INSUFFICIENT_STOCK').toBe('INSUFFICIENT_STOCK');
  // Then 3
  expect(rows, 'Then 3: exactly one row for B').toHaveLength(1);
  expect(rows[0].quantity, 'Then 3: quantity 5, not 6').toBe(5);
  // Then 4
  expect(rows[0].quantity, 'Then 4: rejected add changed nothing, quantity equals stock').toBe(stock);
});
```

Read what is named here with `offset`/`limit`; search the repository only when this map is empty.
