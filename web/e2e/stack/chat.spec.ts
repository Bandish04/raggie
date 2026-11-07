// SPDX-License-Identifier: Apache-2.0

import { FIXTURE_NAME, expect, test, uiLogin, waitForFixtureReady } from "./helpers";

// (c) The fixture uploaded during onboarding becomes READY, and a question about
// it streams back an answer that cites the document (the mock LLM answers
// "… <file> kaynağında yer alıyor [1]." from the retrieved sources).
test("uploaded PDF becomes READY and the chat answer cites it", async ({ page, stack }) => {
  await uiLogin(page, stack.adminEmail, stack.adminPassword);
  await expect(page).toHaveURL(/\/dashboard/);

  // Poll ingestion through the web API with the browser's own session.
  await waitForFixtureReady(async () => {
    const res = await page.request.get(`/api/admin/workspaces/${stack.workspaceId}/documents`);
    expect(res.ok()).toBeTruthy();
    return (await res.json()) as { filename: string; status: string }[];
  });

  await page.goto("/chat");
  const composer = page.getByPlaceholder("Ask something…");
  await expect(composer).toBeVisible();
  // With several workspaces the top bar is a picker; pick the onboarding one.
  const picker = page.getByRole("button", { name: "Workspace" });
  if (await picker.isVisible()) {
    await picker.click();
    await page.getByRole("option", { name: stack.workspaceName }).click();
  }

  const answerStream = page.waitForResponse(
    (r) => r.url().endsWith("/api/chat") && r.request().method() === "POST",
  );
  await composer.fill("How many days of annual leave do employees get?");
  await page.getByRole("button", { name: "Send" }).click();

  const res = await answerStream;
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toContain("text/event-stream");

  // The answer names the document, and its [1] marker became a citation link
  // pointing at the source card for this message.
  const citation = page.locator('a[href^="#src-"]').first();
  await expect(citation).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(FIXTURE_NAME).first()).toBeVisible();

  await page.getByRole("button", { name: /Sources/ }).first().click();
  const target = (await citation.getAttribute("href"))!.slice(1);
  await expect(page.locator(`[id="${target}"]`)).toContainText(FIXTURE_NAME);
});
