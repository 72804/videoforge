import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const prompt = "Two friends discover a mysterious box in their apartment.";

function jpeg(): Buffer {
  return readFileSync(path.join(__dirname, "alex.jpg"));
}

test("create video wizard through project ready", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByRole("button", { name: "Dev login" }).click();
  await page.getByTestId("create-cta").click();
  await page.getByTestId("prompt").fill(prompt);
  await page.getByTestId("continue-prompt").click();
  await page.getByTestId("char-name").fill("Alex");
  await page.getByTestId("char-desc").fill("curious roommate");
  await page.getByTestId("char-photo").setInputFiles({
    name: "alex.jpg",
    mimeType: "image/jpeg",
    buffer: jpeg(),
  });
  await page.getByTestId("add-character").click();
  await expect(page.getByText("Alex")).toBeVisible();
  await expect(page.getByTestId("add-character")).toHaveText("+ Add Character");
  await page.getByTestId("char-name").fill("Sam");
  await page.getByTestId("char-desc").fill("skeptical roommate");
  await page.getByTestId("char-photo").setInputFiles({
    name: "sam.jpg",
    mimeType: "image/jpeg",
    buffer: jpeg(),
  });
  await page.getByTestId("add-character").click();
  await expect(page.getByText("Sam")).toBeVisible();
  await page.getByTestId("continue-characters").click();
  await page.getByRole("button", { name: "Auto" }).click();
  await page.getByRole("button", { name: "9:16" }).click();
  await page.getByRole("button", { name: "Balanced" }).click();
  await page.getByTestId("continue-settings").click();
  await page.getByTestId("calculate-price").click();
  await expect(page.getByTestId("quote-card")).toContainText("Simulated payment");
  await page.getByTestId("generate").click();
  await page.waitForURL(/\/projects\//, { timeout: 30_000 });
  await expect(page.getByTestId("scene-strip")).toBeVisible();
  await page.locator(".scene-card").first().click();
  await page.getByTestId("visual-prompt").fill("A mysterious box on a kitchen table, cinematic lighting");
  await page.getByTestId("save-scene").click();
  await page.getByTestId("regen-video").click();
  await expect(page.getByTestId("regen-quote")).toContainText("Simulated payment");
  await page.getByTestId("confirm-regen").click();
  await page.waitForURL(/\/jobs\//);
  await page.waitForURL(/\/projects\//, { timeout: 30_000 });
  await expect(page.getByTestId("scene-strip")).toBeVisible();
  await page.locator(".scene-card").first().click();
  const restore = page.getByTestId("restore-version");
  if (await restore.count()) await restore.last().click();
  await page.getByTestId("back-project").click();
  await expect(page.getByTestId("scene-strip")).toBeVisible();
  await page.getByTestId("move-later").first().click();
  await page.getByTestId("render").click();
  await expect(page.getByTestId("render")).toContainText(/Ready|Render/);
});
