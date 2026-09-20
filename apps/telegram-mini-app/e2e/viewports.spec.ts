import { expect, test } from "@playwright/test";

const widths = [320, 360, 390, 430];

test("no horizontal page overflow at mobile widths", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByRole("button", { name: "Dev login" }).click();
  await expect(page.getByTestId("create-cta")).toBeVisible();
  for (const width of widths) {
    await page.setViewportSize({ width, height: 720 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `width ${width}`).toBeLessThanOrEqual(1);
  }
  await page.getByTestId("create-cta").click();
  await page.setViewportSize({ width: 320, height: 720 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
