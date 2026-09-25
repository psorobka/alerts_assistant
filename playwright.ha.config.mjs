import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "ha-addon.e2e.spec.mjs",
  workers: 1,
  reporter: "list",
  use: {
    browserName: "chromium",
    headless: true,
    locale: "pl-PL",
  },
});
