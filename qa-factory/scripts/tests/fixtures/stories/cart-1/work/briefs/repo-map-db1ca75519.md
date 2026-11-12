# Repo map - cart (CART-1_TC_005, CART-1_TC_006, CART-1_TC_007, CART-1_TC_008)

Test roots: `tests`. Nouns from the cases' Given/When: cart, cookie, session, r_a, stock, guest, bookstore, bookstore_session_id, quantity, bookid, holds, sessionid, blocked_by_env, book, delete, merge.

## Existing tests of the area

- `tests/api/cart/cart-merge.spec.ts` (1,981 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/cart-isolation.spec.ts` (1,147 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/cart-update-delete.spec.ts` (1,425 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-stock-limit.spec.ts` (1,211 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-rejections.spec.ts` (1,124 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-boundaries.spec.ts` (2,488 B, matched by area): not a Python file: its test names are not listed

## Fixtures (conftest) - 0 of 0, ranked by the nouns

- no conftest.py fixture found under the test roots

## Utils, page objects and test data, ranked

- no helper module matched the nouns

## How a test is written here - `tests/api/cart/cart-merge.spec.ts`, first 50 lines

```typescript
import { test, expect } from '../../../core/fixtures/cartApi.fixture';

// qa(case=CART-1_TC_006, then=[1,2,3,4,5,6], obligations=[OB-6], shape=new)
test('@api @regression CART-1_TC_006 guest cart merge on login', async ({ ownBooks, guest, account }) => {
  const [b1, b2, b3, b4, b5] = [
    await ownBooks.create(10),
    await ownBooks.create(10),
    await ownBooks.create(10),
    await ownBooks.create(10),
    await ownBooks.create(10),
  ];
  const u = await account();
  await u.api.add({ bookId: b1, quantity: 5 });
  await u.api.add({ bookId: b2, quantity: 1 });

  const g = await guest();
  await g.add({ bookId: b1, quantity: 2 });
  await g.add({ bookId: b2, quantity: 4 });
  await g.add({ bookId: b3, quantity: 6 });
  await g.add({ bookId: b4, quantity: 1 });
  await g.add({ bookId: b5, quantity: 2 });
  await ownBooks.setStock(b3, 3);
  await ownBooks.setStock(b4, 0);

  // Unauthenticated merge: the guest jar before sign-in.
  const unauth = await g.merge();

  // Guest jar signs in as U (guest cookie kept) and merges.
  await g.signIn(u.email, u.password);
  const merged = await g.merge();
  expect(merged.status, 'merge as U succeeds').toBe(200);
  const mine = new Map((await u.api.rows()).map((r) => [r.bookId, r.quantity]));

  // Then 1
  expect(mine.get(b2), 'Then 1: B2 = 4 (max of guest 4 and user 1)').toBe(4);
  // Then 2
  expect(mine.get(b1), 'Then 2: B1 = 5 (max of user 5 and guest 2)').toBe(5);
  // Then 3
  expect(mine.get(b3), 'Then 3: B3 = 3 (guest 6 capped at stock 3)').toBe(3);
  // Then 4
  expect(mine.has(b4), 'Then 4: no row for sold-out B4').toBe(false);
  // Then 5
  expect(mine.get(b5), 'Then 5: B5 = 2 (disjoint row kept)').toBe(2);
  expect(
    [...mine.entries()].sort((a, c) => a[0] - c[0]),
    'Then 5: exactly B1 x5, B2 x4, B3 x3, B5 x2'
  ).toEqual([[b1, 5], [b2, 4], [b3, 3], [b5, 2]].sort((a, c) => a[0] - c[0]));
  // Then 6
  expect(unauth.status, 'Then 6: merge without a session answers 401').toBe(401);
});
```

Read what is named here with `offset`/`limit`; search the repository only when this map is empty.
