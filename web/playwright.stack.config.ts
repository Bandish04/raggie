// SPDX-License-Identifier: Apache-2.0

import { defineConfig, devices } from "@playwright/test";

/**
 * Full-stack e2e suite (e2e/stack). Runs against a live compose stack — never
 * part of `test:unit` or the default Playwright config.
 *
 *   eval "$(../scripts/e2e-stack.sh up)"   # fresh stack + E2E_* exports
 *   pnpm exec playwright install chromium   # once
 *   pnpm e2e:stack
 *   ../scripts/e2e-stack.sh down            # tear down (volumes included)
 *
 * The `setup` project onboards the fresh stack (first admin, first workspace)
 * and saves the credentials to e2e/stack/.state/; every other spec depends on it.
 */
export default defineConfig({
  testDir: "./e2e/stack",
  outputDir: "./test-results/stack",
  // Specs share one stack; keep them sequential for deterministic state.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    { name: "setup", testMatch: /onboarding\.setup\.ts/ },
    { name: "stack", testMatch: /.*\.spec\.ts/, dependencies: ["setup"] },
  ],
});
