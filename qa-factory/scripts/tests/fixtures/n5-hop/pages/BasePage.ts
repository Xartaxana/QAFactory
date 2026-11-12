import { Page, Locator, expect } from '@playwright/test';
export class BasePage {
  constructor(protected readonly page: Page) {}
  byId(id: string): Locator { return this.page.getByTestId(id); }
  async expectUrl(pathPart: string) { await expect(this.page).toHaveURL(new RegExp(pathPart)); }
}


