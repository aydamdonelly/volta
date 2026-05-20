import { test, expect } from "@playwright/test";

test("DE solar duck curve thesis spawns correct layout", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /solar duck curve/i }).click();
  await page.waitForSelector('body[data-last-op="done"]', { timeout: 15000 });
  await expect(page.locator(".theme-section__kicker", { hasText: "de_duck_curve" })).toBeVisible();
  const windows = page.locator(".theme-section .window-card");
  await expect(windows).toHaveCount(4);
});
