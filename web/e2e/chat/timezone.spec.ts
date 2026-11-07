// SPDX-License-Identifier: Apache-2.0

// Timezone fallback: a user without a stored zone gets the browser's zone in the
// scheduled-task form and in account settings (resolved on the client after
// hydration, never on the server). The browser zone is pinned per test so a
// pass cannot come from the UTC or Europe/Istanbul fallbacks.
import { type ConsoleMessage, expect, test } from "@playwright/test";

import { signIn } from "./helpers";

function watchHydration(messages: string[]) {
  return (msg: ConsoleMessage) => {
    const text = msg.text();
    if (/hydrat|did not match|server rendered/i.test(text)) messages.push(text);
  };
}

for (const zone of ["America/New_York", "UTC"]) {
  test.describe(`browser zone ${zone}`, () => {
    test.use({ timezoneId: zone });

    test("scheduled-task form and account settings default to the browser zone", async ({
      page,
      context,
      baseURL,
    }) => {
      const hydration: string[] = [];
      page.on("console", watchHydration(hydration));
      page.on("pageerror", (e) => hydration.push(String(e)));
      await signIn(context, baseURL!, "en", "tzless");

      await page.goto("/chat");
      await page.getByRole("button", { name: "Scheduled tasks" }).click();
      await page.getByRole("button", { name: "New task" }).click();
      const manual = page.getByRole("button", { name: "Fill in manually" });
      if (await manual.isVisible()) await manual.click();
      const taskZone = page.getByRole("button", { name: /^Timezone/ });
      await expect(taskZone).toContainText(zone);

      await page.goto("/account");
      await expect(page.locator('input[type="hidden"][name="timezone"]')).toHaveValue(zone);
      await expect(page.getByRole("button", { name: /^Timezone/ })).toContainText(zone);

      expect(hydration).toEqual([]);
    });
  });
}

test("a stored zone wins over the browser zone", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ timezoneId: "America/New_York" });
  const page = await context.newPage();
  await signIn(context, baseURL!, "en", "u1");
  await page.goto("/chat");
  await page.getByRole("button", { name: "Scheduled tasks" }).click();
  await page.getByRole("button", { name: "New task" }).click();
  const manual = page.getByRole("button", { name: "Fill in manually" });
  if (await manual.isVisible()) await manual.click();
  await expect(page.getByRole("button", { name: /^Timezone/ })).toContainText("Europe/Istanbul");
  await context.close();
});
