import type { Page } from "@playwright/test";

export async function openLiveTools(page: Page) {
  for (const selector of [
    "#table-setup",
    "#study-tools",
    "#observation-tools",
    "#connection-tools",
  ]) {
    await page.locator(selector).evaluate((node) => {
      (node as HTMLDetailsElement).open = true;
    });
  }
}
