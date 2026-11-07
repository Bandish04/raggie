// SPDX-License-Identifier: Apache-2.0

// Accessibility audit (axe-core, WCAG 2.1 A/AA) of the main surfaces in en and
// tr against the stub backend. Serious/critical violations fail; the rest is
// printed as a summary ([a11y] lines in the output).
import { expect, test } from "@playwright/test";

import { LOCALES, STUB, ask, audit, signIn } from "./helpers";

const SOURCES = { en: "Sources", tr: "Kaynaklar" } as const;
const TOOLS = { en: "Add & tools", tr: "Ekle ve araçlar" } as const;
const DEEP = { en: "Deep research", tr: "Derin araştırma" } as const;
const LIST_VIEW = { en: "List view", tr: "Liste görünümü" } as const;

test.afterAll(async () => {
  await fetch(`${STUB}/__onboarding`, { method: "POST", body: JSON.stringify({ has_super_admin: true }) });
});

for (const locale of LOCALES) {
  test.describe(`a11y ${locale}`, () => {
    test("public pages: landing and login", async ({ page, context, baseURL }) => {
      await signIn(context, baseURL!, locale, null);
      await page.goto("/");
      await audit(page, `${locale} landing`);
      await page.goto("/login");
      await expect(page.locator("form")).toBeVisible();
      await audit(page, `${locale} login`);
    });

    test("onboarding: first admin, workspace step and upload step", async ({ page, context, baseURL }) => {
      await fetch(`${STUB}/__onboarding`, { method: "POST", body: JSON.stringify({ has_super_admin: false }) });
      await signIn(context, baseURL!, locale, null);
      await page.goto("/onboarding");
      await expect(page.locator('input[type="password"]').first()).toBeVisible();
      await audit(page, `${locale} onboarding bootstrap`);

      await fetch(`${STUB}/__onboarding`, { method: "POST", body: JSON.stringify({ has_super_admin: true }) });
      await signIn(context, baseURL!, locale, "admin");
      await page.goto("/onboarding");
      await expect(page.locator("#workspaceName")).toBeVisible();
      await audit(page, `${locale} onboarding step 1`);
      await page.locator("#workspaceName").fill("Handbook");
      await page.locator('button[type="submit"]').first().click();
      await expect(page.locator('input[type="file"]').first()).toBeAttached();
      await audit(page, `${locale} onboarding step 2`);
    });

    test("chat: empty, deep-research progress, answer with sources", async ({ page, context, baseURL }) => {
      await signIn(context, baseURL!, locale, "u1");
      await page.goto("/chat");
      await expect(page.getByRole("textbox", { name: /Ask something|Bir şey sor/ })).toBeVisible();
      await audit(page, `${locale} chat empty`);

      await page.getByRole("button", { name: TOOLS[locale] }).click();
      await page.getByRole("menuitemcheckbox", { name: DEEP[locale] }).click();
      await page.keyboard.press("Escape");
      await ask(page, "scenario:deep compare leave rules");
      await expect(page.getByText("leave policy 2026")).toBeVisible();
      await audit(page, `${locale} chat deep-research progress`);
      await expect(page.getByText("Deep answer")).toBeVisible();

      await page.getByRole("button", { name: TOOLS[locale] }).click();
      await page.getByRole("menuitemcheckbox", { name: DEEP[locale] }).click();
      await page.keyboard.press("Escape");
      await ask(page, "How much leave do I get?");
      await page.getByRole("button", { name: `${SOURCES[locale]} · 2` }).click();
      await expect(page.locator("#src-msg-1-2")).toBeVisible();
      await audit(page, `${locale} chat answer with sources`);
    });

    test("knowledge base: grid and list", async ({ page, context, baseURL }) => {
      await signIn(context, baseURL!, locale, "admin");
      await page.goto("/admin/knowledge-base");
      await expect(page.getByTestId("doc-failure").first()).toBeVisible();
      await audit(page, `${locale} kb grid`);
      await page.getByRole("button", { name: LIST_VIEW[locale] }).click();
      await expect(page.getByTestId("doc-failure").first()).toBeVisible();
      await audit(page, `${locale} kb list`);
    });

    test("admin workspaces and account settings", async ({ page, context, baseURL }) => {
      await signIn(context, baseURL!, locale, "admin");
      await page.goto("/admin/workspaces");
      await expect(page.getByRole("table")).toBeVisible();
      await audit(page, `${locale} admin workspaces`);
      await page.goto("/account");
      await expect(page.locator("main, [role=main], form").first()).toBeVisible();
      await audit(page, `${locale} account settings`);
    });
  });
}
