import { BasePage } from './BasePage';
import { Locator } from '@playwright/test';

/** Cart page (/cart) plus the nav cart badge and the catalog / detail add controls. */
export class CartPage extends BasePage {
  readonly badge: Locator = this.byId('cart-count-badge');
  readonly total: Locator = this.byId('cart-total');
  readonly emptyMessage: Locator = this.byId('empty-cart-message');
  /** Every cart row (ids are database row ids, so match the pattern). */
  readonly lines: Locator = this.page.getByTestId(/^cart-item-\d+$/);
  readonly detailQuantityInput: Locator = this.byId('book-detail-quantity-input');
  readonly detailAddButton: Locator = this.byId('book-detail-add-to-cart-button');

  async openCart(): Promise<void> {
    await this.page.goto('/cart');
  }

  async openCatalog(): Promise<void> {
    await this.page.goto('/');
  }

  async openBook(bookId: number): Promise<void> {
    await this.page.goto(`/books/${bookId}`);
  }

  async addFromCard(bookId: number): Promise<void> {
    await this.byId(`add-to-cart-button-${bookId}`).click();
  }

  async addFromDetail(quantity: number | string): Promise<void> {
    await this.detailQuantityInput.fill(String(quantity));
    await this.detailAddButton.click();
  }

  /** Transient notification; use as secondary evidence only. */
  toast(text: string): Locator {
    return this.page.getByText(text, { exact: true }).first();
  }

  lineTitled(title: string): Locator {
    return this.lines.filter({ hasText: title });
  }

  /** Row whose title text is exactly `title` (no substring ambiguity between generated titles). */
  lineWithExactTitle(title: string): Locator {
    return this.lines.filter({ has: this.page.getByText(title, { exact: true }) });
  }

  lineQuantityInput(line: Locator): Locator {
    return line.getByTestId(/^cart-item-quantity-\d+$/);
  }

  /**
   * Any visible user message that is not the "added to cart" toast: a sonner toast (li[data-sonner-toast],
   * the notification region of this app; no testid or role on it) or a non-empty role=alert element (the Next.js route announcer excluded).
   * Oracle for "the app refused / reported something" when the wording is unspecified.
   */
  get refusalMessage(): Locator {
    // the Next.js route announcer (#__next-route-announcer__, role=alert, empty text) is not a user message
    return this.page
      .locator('[data-sonner-toast], [role="alert"]:not(#__next-route-announcer__)')
      .filter({ hasText: /\S/ })
      .filter({ hasNotText: /added to cart/i });
  }

  /** Remove button of a cart row (testid remove-cart-item-{rowId}). */
  async removeLine(line: Locator): Promise<void> {
    await line.getByTestId(/^remove-cart-item-\d+$/).click();
  }

  /** The cart as the server lists it for this page's cookie jar (independent of what the page shows). */
  async readServerCart(): Promise<{ id: number; bookId: number; quantity: number }[]> {
    const r = await this.page.request.get('/api/cart');
    if (r.status() !== 200) throw new Error(`GET /api/cart answered ${r.status()}`);
    return (await r.json()) as { id: number; bookId: number; quantity: number }[];
  }

  /** Empty the cart of this page's cookie jar (cleanup). */
  async clearServerCart(): Promise<void> {
    const r = await this.page.request.delete('/api/cart');
    if (r.status() >= 400) throw new Error(`DELETE /api/cart answered ${r.status()}`);
  }
}
