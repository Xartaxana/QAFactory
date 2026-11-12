# Repo map - cart (CART-1_TC_010)

Test roots: `tests`. Nouns from the cases' Given/When: cart, catalog, open, through, badge, book, button, card, click, completion, emptied, first, listed, locate, page, seed.

## Existing tests of the area

- `tests/e2e/cart/add-to-cart.spec.ts` (1,945 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/cart-quote-order.spec.ts` (2,932 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-rejections.spec.ts` (1,124 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/cart-merge.spec.ts` (1,981 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/add-stock-limit.spec.ts` (1,211 B, matched by area): not a Python file: its test names are not listed
- `tests/api/cart/cart-update-delete.spec.ts` (1,538 B, matched by area): not a Python file: its test names are not listed

## Fixtures (conftest) - 0 of 0, ranked by the nouns

- no conftest.py fixture found under the test roots

## Utils, page objects and test data, ranked

- no helper module matched the nouns

## How a test is written here - `tests/e2e/cart/add-to-cart.spec.ts`, first 39 lines

```typescript
import { test, expect } from '../../../core/fixtures/cartApi.fixture';
import { HomePage } from '../../../core/pages/HomePage';
import { LoginPage } from '../../../core/pages/LoginPage';
import { CartPage } from '../../../core/pages/CartPage';
import { cfg } from '../../../core/config';

// A fresh browser session: the shopper signs in through the UI, not through the saved state.
test.use({ storageState: { cookies: [], origins: [] } });

// qa(case=CART-1_TC_010, then=[1,2,3], obligations=[OB-10], shape=new)
test('@regression CART-1_TC_010 add from catalog shows badge and cart page', async ({ page, ownBooks, verifiedUser }) => {
  const bookId = await ownBooks.create(5);
  const title = ownBooks.titleOf(bookId);
  const home = new HomePage(page);
  const login = new LoginPage(page);
  const cart = new CartPage(page);

  await home.open();
  await login.login(cfg.EMAIL_USER, cfg.EMAIL_PASS);
  await expect(home.navLogoutButton).toBeVisible();
  await home.searchFor(title);
  await expect(home.addToCartButton(bookId)).toBeVisible();
  const response = await home.addToCart(bookId);

  // Then 1
  expect.soft(response.status(), 'Then 1: the add call completes with 2xx').toBeGreaterThanOrEqual(200);
  expect.soft(response.status(), 'Then 1: the add call completes with 2xx').toBeLessThan(300);

  // Then 2: the badge equals the sum of quantities read back through GET /api/cart
  const rows = await verifiedUser.api.rows();
  const sum = rows.reduce((acc, r) => acc + r.quantity, 0);
  expect.soft(sum, 'Then 2: the cart holds quantity 1 in total').toBe(1);
  await expect.soft(home.cartBadge, 'Then 2: badge text equals the sum of quantities, 1').toHaveText(String(sum));

  // Then 3
  await home.openCart();
  await expect.soft(cart.itemByTitle(title), 'Then 3: the cart page lists B by its title').toHaveCount(1);
  await expect.soft(cart.quantityOf(title), 'Then 3: B has quantity 1 on the cart page').toHaveValue('1');
});
```

Read what is named here with `offset`/`limit`; search the repository only when this map is empty.
