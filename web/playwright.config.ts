// SPDX-License-Identifier: Apache-2.0

import { defineConfig, devices } from "@playwright/test";

/**
 * Raggie web E2E + visual-audit config.
 *
 * Runs against a running web app on localhost:3000. If none is up, it starts
 * `pnpm dev` for you. For the authenticated screenshots (dashboard / chat /
 * admin) the full stack must be reachable (`make up-core`) and a bootstrapped
 * admin's credentials provided via E2E_EMAIL / E2E_PASSWORD — otherwise those
 * tests skip and only the public pages (login, landing) are captured.
 *
 *   pnpm exec playwright install chromium   # once
 *   E2E_EMAIL=admin@example.com E2E_PASSWORD=… pnpm test:e2e
 *   pnpm test:visual:update                 # (re)baseline screenshots
 */
export default defineConfig({
  testDir: "./e2e",
  // Full-stack specs need a live compose stack: playwright.stack.config.ts.
  // The chat characterization suite has its own stub servers: playwright.chat.config.ts.
  testIgnore: ["stack/**", "chat/**"],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    // Deterministic screenshots: freeze animations, hide the caret.
    screenshot: "only-on-failure",
  },
  expect: {
    toHaveScreenshot: { animations: "disabled", maxDiffPixelRatio: 0.01 },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["iPhone 14"] } },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
