import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./screenshots",
  testMatch: "screenshots.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL: "http://127.0.0.1:4173",
    locale: "en-GB",
    timezoneId: "Europe/Berlin",
    reducedMotion: "reduce",
    serviceWorkers: "block",
    channel: "chromium",
    launchOptions: {
      args: ["--hide-scrollbars"],
    },
  },
  webServer: {
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
