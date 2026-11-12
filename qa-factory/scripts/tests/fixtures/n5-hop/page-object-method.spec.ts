import { test } from '@playwright/test';
import { BasePage } from './pages/BasePage';
import { CartPage } from './pages/CartPage';

test('cart page is open', async ({ page }) => {
  const cart = new CartPage(page);
  await cart.openCart();
  await cart.expectUrl('/cart');
});
