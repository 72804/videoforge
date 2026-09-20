import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const apiPort = 8010;
const appPort = 3010;
const store = path.join(__dirname, ".e2e-store.json");
fs.rmSync(store, { force: true });
fs.rmSync(`${store}.blobs`, { recursive: true, force: true });

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  use: {
    baseURL: `http://127.0.0.1:${appPort}`,
    viewport: { width: 390, height: 844 },
  },
  projects: [{ name: "chromium", use: { ...devices["Pixel 7"] } }],
  webServer: [
    {
      command: `uv run docprod telegram-api-serve --host 127.0.0.1 --port ${apiPort}`,
      cwd: "../..",
      url: `http://127.0.0.1:${apiPort}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        ...process.env,
        PRODUCT_PERSISTENCE: "json",
        APP_ENV: "development",
        PRODUCT_STORE_PATH: store,
      },
    },
    {
      command: `npx next dev --port ${appPort}`,
      url: `http://127.0.0.1:${appPort}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        ...process.env,
        API_PROXY_TARGET: `http://127.0.0.1:${apiPort}`,
        NEXT_PUBLIC_APP_ENV: "development",
      },
    },
  ],
});
