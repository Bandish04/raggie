// SPDX-License-Identifier: Apache-2.0

// The admin conversation viewer shows widget-visitor threads: untrusted
// markdown. It must render through the chat's safe renderer, so opening a
// conversation never makes the admin's browser fetch a visitor-chosen URL.
// The CSP img-src is the backstop and is checked on the served header.
import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("admin conversation viewer never renders remote markdown images", async ({ page, context, baseURL }) => {
  const remote: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("evil.example")) remote.push(r.url());
  });
  await signIn(context, baseURL!, "en", "admin");
  await page.goto("/admin/conversations");
  await page.getByRole("button", { name: /Pricing question/ }).click();

  const thread = page.locator(".card").filter({ hasText: "Here you go" });
  await expect(thread.getByRole("link", { name: "beacon" })).toHaveAttribute("href", "https://evil.example/beacon.png?c=1");
  await expect(thread.locator('img[src*="evil.example"]')).toHaveCount(0);
  await expect(thread.locator('a[href^="javascript:"]')).toHaveCount(0);
  // Same-origin images still render; raw HTML stays text.
  await expect(thread.locator('img[src="/icon.svg"]')).toHaveCount(1);
  await expect(thread.getByText('<img src="https://evil.example/raw.png" onerror="alert(1)">')).toBeVisible();
  // The visitor's own turn is plain text.
  await expect(thread.getByText("![visitor](https://evil.example/visitor.png?who=admin) hi")).toBeVisible();
  expect(remote).toEqual([]);
});

test("served CSP keeps img-src to this origin and inline images", async ({ request }) => {
  const res = await request.get("/login");
  const csp = res.headers()["content-security-policy"] ?? "";
  const img = csp
    .split(";")
    .map((d) => d.trim())
    .find((d) => d.startsWith("img-src "));
  expect(img).toBe("img-src 'self' data: blob:");
});
