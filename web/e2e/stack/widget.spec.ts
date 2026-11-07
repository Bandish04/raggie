// SPDX-License-Identifier: Apache-2.0

import {
  FIXTURE_NAME,
  bearer,
  cpDocs,
  cpLogin,
  cpUploadFixture,
  env,
  expect,
  loadState,
  test,
  waitForFixtureReady,
} from "./helpers";

// A fake third-party site that embeds the widget. Playwright serves it, so its
// origin is real to the browser (and to the edge's CORS / origin allow-list).
const HOST_ORIGIN = "http://widget-host.e2e.test";

let externalWorkspaceId = "";

test.describe.configure({ mode: "serial" });

// An EXTERNAL (support widget) workspace with the fixture indexed and the host
// origin on its CORS allow-list.
test.beforeAll(async ({ playwright }) => {
  const state = loadState();
  if (!state) throw new Error("no stack state — run the setup project first");
  const request = await playwright.request.newContext();
  try {
    const token = await cpLogin(request, state.adminEmail, state.adminPassword);
    const created = await request.post(`${env.controlPlane}/api/v1/admin/orgs/${state.orgId}/workspaces`, {
      headers: bearer(token),
      data: { name: `E2E Support ${Date.now().toString(36)}`, type: "EXTERNAL" },
    });
    expect(created.status(), await created.text()).toBe(201);
    externalWorkspaceId = ((await created.json()) as { id: string }).id;

    const widget = await request.put(`${env.controlPlane}/api/v1/admin/workspaces/${externalWorkspaceId}/widget`, {
      headers: bearer(token),
      data: { cors_allowed_origins: [HOST_ORIGIN] },
    });
    expect(widget.ok(), await widget.text()).toBeTruthy();

    await cpUploadFixture(request, token, externalWorkspaceId);
    await waitForFixtureReady(() => cpDocs(request, token, externalWorkspaceId));
  } finally {
    await request.dispose();
  }
});

async function widgetToken(request: import("@playwright/test").APIRequestContext, origin: string) {
  return request.post(`${env.edge}/api/v1/widget/token`, {
    headers: { Origin: origin },
    data: { workspace_id: externalWorkspaceId },
  });
}

// (f / A4) A widget token never opens the admin surface.
test("widget token: issued only to allow-listed origins and rejected by admin APIs", async ({ request }) => {
  expect((await widgetToken(request, "https://evil.example")).status()).toBe(403);

  const res = await widgetToken(request, HOST_ORIGIN);
  expect(res.status(), await res.text()).toBe(200);
  const { token } = (await res.json()) as { token: string };

  for (const url of [
    `${env.edge}/api/v1/admin/conversations`,
    `${env.edge}/api/v1/admin/mcp/capabilities`,
    `${env.controlPlane}/api/v1/admin/orgs`,
    `${env.controlPlane}/api/v1/auth/me`,
  ]) {
    const admin = await request.get(url, { headers: bearer(token) });
    expect([401, 403], `${url} answered ${admin.status()}`).toContain(admin.status());
  }
});

// (g) The embed snippet on a third-party page loads embed.js from the front
// door (Caddy, as in production: the snippet's origin is also the widget API
// base) and the widget answers from the workspace's documents.
test("embedded widget loads through the front door and answers a question", async ({ page }) => {
  const snippet = `<script src="${env.web}/widgets/embed.js?id=${externalWorkspaceId}"></script>`;
  await page.route(`${HOST_ORIGIN}/**`, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><html><head><title>Host</title></head><body><h1>Host site</h1>${snippet}</body></html>`,
    }),
  );

  const embedLoaded = page.waitForResponse((r) => r.url().includes("/widgets/embed.js"));
  await page.goto(`${HOST_ORIGIN}/`);
  expect((await embedLoaded).status()).toBe(200);

  // The widget renders in an open shadow root; Playwright locators pierce it.
  await page.getByRole("button", { name: "Open chat" }).click();
  const input = page.getByPlaceholder("Type a message…");
  await input.fill("How many days of annual leave do employees get?");
  await input.press("Enter");

  await expect(page.locator("#raggie-widget-root").getByText(FIXTURE_NAME).first()).toBeVisible({
    timeout: 60_000,
  });
});
