// SPDX-License-Identifier: Apache-2.0

import { bearer, cpLogin, env, expect, strongPassword, test, uiLogin, uniqueEmail } from "./helpers";

// (b) Sign-in, sign-out and the account lockout message.
test("admin signs in, lands on the dashboard and signs out", async ({ page, stack }) => {
  await uiLogin(page, stack.adminEmail, stack.adminPassword);
  await expect(page).toHaveURL(/\/dashboard/);

  // Sign out from the admin shell; the session is gone afterwards.
  await page.goto("/admin");
  await page.getByRole("button", { name: "Sign out" }).filter({ visible: true }).first().click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login/);
});

test("wrong password shows an error, then the lockout message", async ({ page, request, stack }) => {
  // A dedicated account so the lockout cannot affect other specs.
  const token = await cpLogin(request, stack.adminEmail, stack.adminPassword);
  const email = uniqueEmail("lockout");
  const created = await request.post(`${env.controlPlane}/api/v1/admin/orgs/${stack.orgId}/users`, {
    headers: bearer(token),
    data: { email, role: "STAFF", password: strongPassword() },
  });
  expect(created.ok(), await created.text()).toBeTruthy();

  await uiLogin(page, email, "definitely-not-the-password");
  await expect(page.getByRole("alert")).toHaveText("Invalid email or password.");

  // Keep failing until the control plane locks the account (threshold is
  // LOGIN_LOCKOUT_THRESHOLD, 5 by default); the form then says so instead of
  // claiming the password is wrong.
  await expect
    .poll(
      async () => {
        await page.getByLabel("Password").fill("definitely-not-the-password");
        await page.getByRole("button", { name: "Sign in" }).click();
        await expect(page.getByRole("alert")).toBeVisible();
        return (await page.getByRole("alert").textContent()) ?? "";
      },
      { timeout: 60_000, intervals: [250] },
    )
    .toContain("Too many sign-in attempts");
  await expect(page).toHaveURL(/\/login/);
});
