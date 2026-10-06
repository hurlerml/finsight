import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { installScreenshotApi } from "./fixtures";

const output = (...parts: string[]) => path.resolve(process.cwd(), "../docs/screenshots", ...parts);

async function prepare(page: Page, route: string, viewport: { width: number; height: number }) {
  await page.setViewportSize(viewport);
  await installScreenshotApi(page);
  await page.goto(route);
  await page.waitForLoadState("networkidle");
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        caret-color: transparent !important;
      }
      html, body, * {
        scrollbar-width: none !important;
      }
      html::-webkit-scrollbar, body::-webkit-scrollbar, *::-webkit-scrollbar {
        display: none !important;
        width: 0 !important;
        height: 0 !important;
      }
    `,
  });
  await page.evaluate(() => document.fonts.ready);
}

test("desktop overview", async ({ page }) => {
  await prepare(page, "/", { width: 1440, height: 1000 });
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("€60,305.55")).toBeVisible();
  await page.screenshot({ path: output("overview-desktop-dark.png"), animations: "disabled" });
});

test("desktop transactions", async ({ page }) => {
  await prepare(page, "/transactions", { width: 1440, height: 1000 });
  await expect(page.getByRole("heading", { name: "Transactions" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Northstar Labs/ }).first()).toBeVisible();
  await page.screenshot({ path: output("transactions-desktop-dark.png"), animations: "disabled" });
});

test("mobile overview", async ({ page }) => {
  await prepare(page, "/", { width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByRole("navigation").last()).toBeVisible();
  await page.screenshot({ path: output("overview-mobile-dark.png"), animations: "disabled" });
});

test("mobile local finance chat", async ({ page }) => {
  await prepare(page, "/chat", { width: 390, height: 844 });
  await expect(page.getByRole("region", { name: "finsight agent" })).toBeVisible();
  await expect(page.getByText("Monthly wealth building", { exact: true })).toBeVisible();
  await page.screenshot({ path: output("chat-mobile-dark.png"), animations: "disabled" });
});
