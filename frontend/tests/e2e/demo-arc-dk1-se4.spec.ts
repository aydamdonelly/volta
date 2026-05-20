import { test, expect } from "@playwright/test";

test("DK1 to SE4 spread thesis pulls Optimeering counter", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /DK1 to SE4/i }).click();
  await page.waitForSelector('body[data-last-op="done"]', { timeout: 15000 });
  await expect(page.locator(".theme-section__kicker", { hasText: "dk1_se4_spread" })).toBeVisible();
  // Counter window should reference Optimeering source curves
  const counterBody = page.locator(".window-card--counter").first();
  await expect(counterBody).toContainText(/optimeering/i);
});
