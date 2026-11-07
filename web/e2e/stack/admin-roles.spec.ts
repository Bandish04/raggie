// SPDX-License-Identifier: Apache-2.0

import { bearer, cpLogin, env, expect, strongPassword, test, uiLogin, uniqueEmail } from "./helpers";

const PLATFORM_PAGES = [
  { path: "/admin/branding", heading: "Branding" },
  { path: "/admin/ai", heading: "AI models" },
  { path: "/admin/updates", heading: "Updates" },
];

// (d) Platform-admin surfaces: visible and working for the platform admin,
// hidden and redirected for an org SUPER_ADMIN who joined via invite.
test("platform admin sees branding, AI config, updates and the platform-admin toggle", async ({ page, stack }) => {
  await uiLogin(page, stack.adminEmail, stack.adminPassword);
  await expect(page).toHaveURL(/\/dashboard/);

  for (const { path, heading } of PLATFORM_PAGES) {
    await page.goto(path);
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
  await expect(page.getByRole("link", { name: "Branding" }).filter({ visible: true })).toBeVisible();

  // People tab: the admin's own row carries the toggle (pressed = platform admin).
  await page.goto("/admin/organization?tab=people");
  const row = page.getByRole("row").filter({ hasText: stack.adminEmail });
  await expect(row.getByText("Platform admin")).toBeVisible();
  const toggle = row.getByRole("button", { name: "Remove platform admin" });
  await expect(toggle).toHaveAttribute("aria-pressed", "true");

  // Revoking the only platform admin is refused with the friendly 409 message.
  await toggle.click();
  await expect(page.getByRole("alert")).toContainText("last platform admin");
});

test("org super admin (invited) cannot see or open platform-only pages; password policy applies", async ({
  page,
  request,
  stack,
}) => {
  const adminToken = await cpLogin(request, stack.adminEmail, stack.adminPassword);
  const email = uniqueEmail("orgadmin");
  const invite = await request.post(`${env.controlPlane}/api/v1/auth/invites`, {
    headers: bearer(adminToken),
    data: { email, role: "SUPER_ADMIN", full_name: "Org Admin" },
  });
  expect(invite.status(), await invite.text()).toBe(201);
  const { accept_path: acceptPath } = (await invite.json()) as { accept_path: string };

  await page.goto(acceptPath);
  const password = page.getByLabel("Password", { exact: true });
  const confirm = page.getByLabel("Confirm password");
  const submit = page.getByRole("button", { name: "Create account" });

  // (e) 11 characters: the browser blocks the submit (minlength=12)…
  await password.fill("Elevenchar1");
  await confirm.fill("Elevenchar1");
  await submit.click();
  expect(await password.evaluate((el: HTMLInputElement) => el.validity.tooShort)).toBe(true);
  await expect(page).toHaveURL(/\/onboarding\/accept/);

  // …and with client validation stripped, the server rejects it too.
  await page.locator("form").evaluate((form: HTMLFormElement) => {
    form.noValidate = true;
  });
  await submit.click();
  await expect(page.getByText("Use at least 12 characters.")).toBeVisible();
  await expect(page).toHaveURL(/\/onboarding\/accept/);

  const good = strongPassword();
  await password.fill(good);
  await confirm.fill(good);
  await submit.click();
  await expect(page).toHaveURL(/\/dashboard/);

  // Not a platform admin: no nav entry, and the pages redirect away.
  await page.goto("/admin");
  await expect(page.getByRole("link", { name: "Organization" }).filter({ visible: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Branding" })).toHaveCount(0);
  for (const { path } of PLATFORM_PAGES) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/dashboard/);
  }

  // The control plane enforces the same boundary.
  const orgAdminToken = await cpLogin(request, email, good);
  const branding = await request.put(`${env.controlPlane}/api/v1/admin/branding`, {
    headers: bearer(orgAdminToken),
    data: { name: "Hijacked" },
  });
  expect(branding.status()).toBe(403);
});

test("password policy: the control plane answers 422 for an 11-character password", async ({ request, stack }) => {
  const token = await cpLogin(request, stack.adminEmail, stack.adminPassword);
  const res = await request.post(`${env.controlPlane}/api/v1/auth/change-password`, {
    headers: bearer(token),
    data: { current_password: stack.adminPassword, new_password: "Elevenchar1" },
  });
  expect(res.status()).toBe(422);
  const body = (await res.json()) as { detail: { loc: string[] }[] };
  expect(body.detail.some((d) => d.loc.at(-1) === "new_password")).toBe(true);
});
