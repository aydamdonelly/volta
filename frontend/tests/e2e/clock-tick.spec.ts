import { test, expect } from "@playwright/test";

test("clock +1h advances and renders updated time", async ({ page }) => {
  await page.goto("/");
  const before = await page.locator('[data-testid="clock-time"]').textContent();
  await page.getByRole("button", { name: /Step \+1 hour/i }).click();
  // Time text should change
  await expect(page.locator('[data-testid="clock-time"]')).not.toHaveText(before || "", { timeout: 5000 });
});
