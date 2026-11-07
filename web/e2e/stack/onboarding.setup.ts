// SPDX-License-Identifier: Apache-2.0

import {
  FIXTURE_PDF,
  bearer,
  cpLogin,
  env,
  expect,
  loadState,
  saveState,
  strongPassword,
  test,
  uniqueEmail,
} from "./helpers";

// (a) First-run onboarding on a fresh stack: setup token → first admin with a
// 12+ character password → first workspace (+ fixture upload). Every other spec
// depends on this project and reads the credentials it saves.
test("onboarding: setup token, first admin, first workspace", async ({ page, request }) => {
  const workspaceName = "E2E Team";
  await page.goto("/onboarding");

  // Re-running against a stack that is already onboarded: keep the saved state.
  if (!page.url().includes("/onboarding")) {
    const saved = loadState();
    test.skip(!saved, "stack is already onboarded and no saved e2e state exists — use a fresh stack");
    return;
  }

  const adminEmail = uniqueEmail("admin");
  const adminPassword = strongPassword();

  await page.getByLabel("Organization name").fill("E2E Org");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password", { exact: true }).fill(adminPassword);

  // A wrong setup token is rejected with the friendly message, not a crash.
  await page.getByLabel("Setup token").fill("not-the-real-token");
  await page.getByRole("button", { name: "Create & continue" }).click();
  await expect(page.getByRole("alert")).toContainText("setup token is not valid");

  await page.getByLabel("Setup token").fill(env.setupToken);
  await page.getByRole("button", { name: "Create & continue" }).click();

  // Wizard step 1: internal team chat workspace.
  await expect(page.getByText("How will you use Raggie?")).toBeVisible();
  await page.getByRole("button", { name: /Internal Team Chat/ }).click();
  await page.getByLabel("Workspace name").fill(workspaceName);
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 2: upload the fixture.
  await expect(page.getByText("Add your documents")).toBeVisible();
  await page.locator('input[type="file"][name="files"]').setInputFiles(FIXTURE_PDF);
  await page.getByRole("button", { name: "Choose files" }).click();
  await expect(page.getByText("Added 1 document(s).")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Skip for now" }).click();

  // Step 3 → dashboard.
  await page.getByRole("button", { name: "Go to dashboard" }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  // Resolve ids for the other specs via the control plane.
  const token = await cpLogin(request, adminEmail, adminPassword);
  const me = await (await request.get(`${env.controlPlane}/api/v1/auth/me`, { headers: bearer(token) })).json();
  const workspaces = (await (
    await request.get(`${env.controlPlane}/api/v1/workspaces`, { headers: bearer(token) })
  ).json()) as { id: string; name: string }[];
  const ws = workspaces.find((w) => w.name === workspaceName);
  expect(ws, `workspace ${workspaceName} not found`).toBeTruthy();
  expect(me.is_platform_admin).toBe(true);

  saveState({
    adminEmail,
    adminPassword,
    orgId: me.org_id,
    workspaceId: ws!.id,
    workspaceName,
  });
});
