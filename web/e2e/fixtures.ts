// SPDX-License-Identifier: Apache-2.0

import { existsSync } from "node:fs";
import path from "node:path";

import {
  type BrowserContext,
  type Page,
  type PageAssertionsToHaveScreenshotOptions,
  expect,
  test,
} from "@playwright/test";

export const LOCALES = ["tr", "en"] as const;
export type Locale = (typeof LOCALES)[number];

/** Set the UI locale via the NEXT_LOCALE cookie before navigation. */
export async function setLocale(context: BrowserContext, locale: Locale, baseURL = "http://localhost:3000") {
  const url = new URL(baseURL);
  await context.addCookies([
    { name: "NEXT_LOCALE", value: locale, domain: url.hostname, path: "/" },
  ]);
}

/**
 * Log in through the UI with credentials from the environment. Returns false
 * (so the caller can skip authenticated screenshots) when creds aren't set —
 * keeps the public-page audit runnable without a live backend.
 */
export async function loginIfConfigured(page: Page): Promise<boolean> {
  const email = process.env.E2E_EMAIL;
  const password = process.env.E2E_PASSWORD;
  if (!email || !password) return false;

  await page.goto("/login");
  await page.getByPlaceholder(/e-?mail|e-posta/i).fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole("button", { name: /sign in|giriş/i }).click();
  await expect(page).toHaveURL(/\/(dashboard|onboarding|chat)/, { timeout: 15_000 });
  return true;
}

/** Stable screenshot name: <page>-<locale>-<project>. */
export function shot(name: string, locale: Locale) {
  return `${name}-${locale}.png`;
}

/**
 * `toHaveScreenshot`, but only where a baseline exists for this platform.
 * Baselines are platform-specific (`*-linux.png`) and are recorded on Linux in
 * CI with `pnpm test:visual:update`; any other platform (or a fresh checkout)
 * skips with that hint instead of writing a local baseline.
 */
export async function expectScreenshot(
  page: Page,
  name: string,
  options?: PageAssertionsToHaveScreenshotOptions,
) {
  const info = test.info();
  const baseline = info.snapshotPath(name, { kind: "screenshot" });
  const updating = info.config.updateSnapshots === "all" || info.config.updateSnapshots === "changed";
  test.skip(
    !updating && !existsSync(baseline),
    `no ${process.platform} baseline ${path.basename(baseline)}: record Linux baselines in CI with \`pnpm test:visual:update\``,
  );
  await expect(page).toHaveScreenshot(name, options);
}
