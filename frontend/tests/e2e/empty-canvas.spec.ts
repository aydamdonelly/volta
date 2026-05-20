import { test, expect } from "@playwright/test";

test("empty canvas renders only logo + hero + voice dot, no pre-baked suggestions", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /An empty canvas/i })).toBeVisible();
  await expect(page.getByAltText("Volta").first()).toBeVisible();
  await expect(page.getByLabel("Volta voice and text input")).toBeVisible();
  // The old POOL of 10 hardcoded thesis buttons is gone — composer is AI-driven now.
  await expect(page.getByRole("button", { name: /solar duck curve/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /price crash/i })).toHaveCount(0);
});
