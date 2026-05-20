import { test, expect } from "@playwright/test";

test("save + restore template roundtrip", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /price crash on April 5th/i }).click();
  await page.waitForSelector('body[data-last-op="done"]', { timeout: 15000 });

  // Save
  page.once("dialog", async (d) => { await d.accept("e2e_apr5"); });
  await page.getByRole("button", { name: /^Save…$/ }).click();
  // Wait for status
  await expect(page.locator("text=/Saved \"e2e_apr5\"/i")).toBeVisible({ timeout: 5000 });

  // Restore
  page.once("dialog", async (d) => { await d.accept("e2e_apr5"); });
  await page.getByRole("button", { name: /^Restore…$/ }).click();
  await expect(page.locator("text=/Restored \"e2e_apr5\"/i")).toBeVisible({ timeout: 5000 });
  // Windows should still be present
  await expect(page.locator(".window-card").first()).toBeVisible();
});
