import { test, expect } from "@playwright/test";

test("slash hotkey focuses text input; Enter submits", async ({ page }) => {
  await page.goto("/");
  // Press "/" — should expand the voice dot and focus the text input
  await page.keyboard.press("/");
  const input = page.locator(".voice-dot__input");
  await expect(input).toBeFocused();
  await input.fill("Show me Germany's solar duck curve");
  await page.keyboard.press("Enter");
  await page.waitForSelector('body[data-last-op="done"]', { timeout: 15000 });
  await expect(page.locator(".theme-section__kicker", { hasText: "de_duck_curve" })).toBeVisible();
});
