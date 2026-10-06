import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { installScreenshotApi } from "./fixtures";

const output = (...parts: string[]) => path.resolve(process.cwd(), "../docs/screenshots", ...parts);
const themes = ["dark", "light"] as const;
type ScreenshotTheme = (typeof themes)[number];

async function prepare(page: Page, route: string, viewport: { width: number; height: number }, theme: ScreenshotTheme) {
  await page.setViewportSize(viewport);
  await installScreenshotApi(page, theme);
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
    `,
  });
  await page.evaluate(() => document.fonts.ready);
}

for (const theme of themes) {
  test(`desktop overview · ${theme}`, async ({ page }) => {
    await prepare(page, "/", { width: 1440, height: 1000 }, theme);
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByText("€60,305.55")).toBeVisible();
    await page.screenshot({ path: output(`overview-desktop-${theme}.png`), animations: "disabled" });
  });

  test(`desktop transactions · ${theme}`, async ({ page }) => {
    await prepare(page, "/transactions", { width: 1440, height: 1000 }, theme);
    await expect(page.getByRole("heading", { name: "Transactions" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Northstar Labs/ }).first()).toBeVisible();
    await page.screenshot({ path: output(`transactions-desktop-${theme}.png`), animations: "disabled" });
  });

  test(`desktop assets · ${theme}`, async ({ page }) => {
    await prepare(page, "/assets", { width: 1440, height: 1000 }, theme);
    await expect(page.getByRole("heading", { name: "Assets" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Global equity ETF/ })).toBeVisible();
    await page.screenshot({ path: output(`assets-desktop-${theme}.png`), animations: "disabled" });
  });

  test(`desktop cashflow detail · ${theme}`, async ({ page }) => {
    await prepare(page, "/", { width: 1440, height: 1000 }, theme);
    const heading = page.getByRole("heading", { name: "Cashflow", exact: true });
    const section = heading.locator("xpath=ancestor::section[1]");
    await expect(section).toBeVisible();
    await section.screenshot({ path: output(`cashflow-desktop-${theme}.png`), animations: "disabled" });
  });

  test(`mobile overview · ${theme}`, async ({ page }) => {
    await prepare(page, "/", { width: 390, height: 844 }, theme);
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByRole("navigation").last()).toBeVisible();
    await page.screenshot({ path: output(`overview-mobile-${theme}.png`), animations: "disabled" });
  });

  test(`mobile local finance chat · ${theme}`, async ({ page }) => {
    await prepare(page, "/chat", { width: 390, height: 844 }, theme);
    await expect(page.getByRole("region", { name: "finsight agent" })).toBeVisible();
    await expect(page.getByText("Monthly wealth building", { exact: true })).toBeVisible();
    await page.screenshot({ path: output(`chat-mobile-${theme}.png`), animations: "disabled" });
  });
}
