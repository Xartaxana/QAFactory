import { test, expect } from '@playwright/test';
import { CartPage } from './pages/CartPage';

let tabA: CartPage;

// verbatim from tests/e2e/cart/cart-stale-tab.spec.ts:40-44 (there it stands inside the test body)
const addOne = async (id: number) => {
      await tabA.openBook(id);
      await tabA.addFromDetail(1);
      await expect(tabA.toast('Book added to cart'), `precondition: book ${id} added`).toBeVisible();
    };

test('TC-012 stale tab adds two books', async ({ page }) => {
  tabA = new CartPage(page);
  await addOne(1);
  await addOne(2);
});
