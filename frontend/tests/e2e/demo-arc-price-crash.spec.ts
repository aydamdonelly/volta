import { test, expect } from "@playwright/test";

test("DE price crash thesis spawns 4 windows with Sonnet narration citing -16", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /price crash on April 5th/i }).click();
  // Wait for the orchestrator done signal
  await page.waitForSelector('body[data-last-op="done"]', { timeout: 15000 });
  // Theme header with thesis_key kicker
  await expect(page.locator(".theme-section__kicker", { hasText: "de_price_crash" })).toBeVisible();
  // 4 window cards in this theme
  const windows = page.locator(".theme-section .window-card");
  await expect(windows).toHaveCount(4);
  // Counter badge
  await expect(page.locator(".label--warning-subtle", { hasText: /counter/i }).first()).toBeVisible();
  // News hedge label
  await expect(page.locator(".label--info-subtle", { hasText: /context, not proof/i }).first()).toBeVisible();
  // Sonnet narration: text window body contains "-16" or "16.34" or "16,34"
  const textBody = page.locator(".window-card--text .window-card__body");
  await expect(textBody).toContainText(/[-−]\s*€?\s*16([.,]\d+)?/);
});
