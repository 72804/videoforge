import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

function jpeg(): Buffer {
  return readFileSync(path.join(__dirname, "alex.jpg"));
}

test("friend group create reaches review", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dev login" }).click();
  await page.getByTestId("create-cta").click();
  await page.getByTestId("start-friend-group").click();
  await page.getByTestId("char-name").fill("Alex");
  await page.getByTestId("trait-chaotic").click();
  await page.getByTestId("char-photo").setInputFiles({
    name: "alex.jpg",
    mimeType: "image/jpeg",
    buffer: jpeg(),
  });
  await page.getByTestId("add-character").click();
  await expect(page.getByText("Alex")).toBeVisible();
  await page.getByTestId("continue-cast").click();
  await page.getByTestId("prompt").fill("Two friends argue over the last slice of pizza.");
  await page.getByTestId("continue-situation").click();
  await expect(page.getByTestId("calculate-price")).toBeVisible();
});
