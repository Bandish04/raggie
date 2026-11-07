// SPDX-License-Identifier: Apache-2.0

import { test, expect } from "@playwright/test";

import { LOCALES, expectScreenshot, loginIfConfigured, setLocale, shot } from "./fixtures";

/**
 * Visual audit + smoke E2E across TR/EN and desktop/mobile (viewport comes from
 * the Playwright project). Public pages run anywhere; authenticated pages run
 * only when E2E_EMAIL / E2E_PASSWORD are set against a live stack.
 *
 * Baselines are per platform and recorded on Linux (CI) with
 * `pnpm test:visual:update`; without a baseline for the current platform a
 * screenshot check skips with that hint (no local darwin/win32 baselines).
 * Once recorded, later runs fail on any visual regression.
 */
for (const locale of LOCALES) {
  test.describe(`locale: ${locale}`, () => {
    test.beforeEach(async ({ context, baseURL }) => {
      await setLocale(context, locale, baseURL ?? undefined);
    });

    test("login page", async ({ page }) => {
      await page.goto("/login");
      await expect(page.getByRole("button", { name: /sign in|giriş/i })).toBeVisible();
      await expectScreenshot(page, shot("login", locale));
    });

    test("landing page", async ({ page }) => {
      const res = await page.goto("/");
      // Landing may redirect to /login or /onboarding depending on state — that's fine.
      expect(res?.status()).toBeLessThan(400);
      await expectScreenshot(page, shot("landing", locale), { fullPage: true });
    });

    test("authenticated surfaces", async ({ page }) => {
      const authed = await loginIfConfigured(page);
      test.skip(!authed, "set E2E_EMAIL / E2E_PASSWORD against a live stack to capture these");

      await page.goto("/dashboard");
      await expectScreenshot(page, shot("dashboard", locale), { fullPage: true });

      await page.goto("/chat");
      await expect(page.getByPlaceholder(/ask something|bir şey sor/i)).toBeVisible();
      await expectScreenshot(page, shot("chat-empty", locale));

      await page.goto("/admin");
      await expectScreenshot(page, shot("admin-dashboard", locale), { fullPage: true });

      await page.goto("/admin/knowledge-base");
      await expectScreenshot(page, shot("admin-kb", locale), { fullPage: true });
    });
  });
}
