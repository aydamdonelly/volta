import { test, expect } from "@playwright/test";

test("raw data modal shows Apr-5 price rows", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /price crash on April 5th/i }).click();
  await page.waitForSelector('body[data-last-op="done"]', { timeout: 15000 });
  await page.getByRole("button", { name: /View raw data/i }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const rows = page.locator(".modal .data-table tbody tr");
  await expect(rows.first()).toBeVisible({ timeout: 5000 });
  const count = await rows.count();
  expect(count).toBeGreaterThanOrEqual(20);
});
