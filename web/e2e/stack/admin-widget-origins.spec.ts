// SPDX-License-Identifier: Apache-2.0

import { bearer, cpLogin, env, expect, test, uiLogin } from "./helpers";

// The admin manages an EXTERNAL workspace's widget allowed origins from the
// Workspaces page; the saved list is what the edge enforces for widget tokens.
test("admin edits widget allowed origins and the edge honors them", async ({ page, request, stack }) => {
  const token = await cpLogin(request, stack.adminEmail, stack.adminPassword);
  const name = `E2E Origins ${Date.now().toString(36)}`;
  const created = await request.post(`${env.controlPlane}/api/v1/admin/orgs/${stack.orgId}/workspaces`, {
    headers: bearer(token),
    data: { name, type: "EXTERNAL" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const workspaceId = ((await created.json()) as { id: string }).id;

  await uiLogin(page, stack.adminEmail, stack.adminPassword);
  await page.goto("/admin/workspaces");
  const row = page.getByRole("row").filter({ hasText: name });
  await row.getByRole("button", { name: "Add sites" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: `Widget sites for ${name}` })).toBeVisible();
  const input = dialog.getByLabel("Add an origin");

  // Client-side validation: nothing invalid reaches the draft list.
  for (const [value, message] of [
    ["https://*.example.com", "Wildcards are not allowed"],
    ["shop.example.com", "Start with http:// or https://"],
    ["https://shop.example.com/cart", "no path, query or #fragment"],
  ] as const) {
    await input.fill(value);
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText(message);
  }

  // Normalized to the browser's Origin serialization; duplicates refused.
  await input.fill("HTTPS://Shop.Example.com:443/");
  await input.press("Enter");
  await expect(dialog.getByText("https://shop.example.com", { exact: true })).toBeVisible();
  await input.fill("https://shop.example.com");
  await input.press("Enter");
  await expect(dialog.getByRole("alert")).toContainText("already in the list");

  await input.fill("http://localhost:4100");
  await input.press("Enter");
  await dialog.getByRole("button", { name: "Remove http://localhost:4100" }).click();
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
  await expect(row.getByRole("button", { name: "1 site" })).toBeVisible();

  const config = await request.get(`${env.controlPlane}/api/v1/admin/workspaces/${workspaceId}/widget`, {
    headers: bearer(token),
  });
  expect(((await config.json()) as { cors_allowed_origins: string[] }).cors_allowed_origins).toEqual([
    "https://shop.example.com",
  ]);

  const issue = (origin: string) =>
    request.post(`${env.edge}/api/v1/widget/token`, {
      headers: { Origin: origin },
      data: { workspace_id: workspaceId },
    });
  expect((await issue("https://shop.example.com")).status()).toBe(200);
  expect((await issue("http://localhost:4100")).status()).toBe(403);

  // Removing every site closes the widget again.
  await row.getByRole("button", { name: "1 site" }).click();
  await dialog.getByRole("button", { name: "Remove https://shop.example.com" }).click();
  await expect(dialog.getByText("No sites yet")).toBeVisible();
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(row.getByRole("button", { name: "Add sites" })).toBeVisible();
  expect((await issue("https://shop.example.com")).status()).toBe(403);
});
