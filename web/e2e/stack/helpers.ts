// SPDX-License-Identifier: Apache-2.0

import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { type APIRequestContext, type Page, test as base, expect } from "@playwright/test";

// Full-stack e2e helpers. The suite targets a running compose stack (see
// scripts/e2e-stack.sh); nothing here mocks the backend except where a spec
// says so explicitly.

function required(name: string): string {
  const v = process.env[name]?.trim();
  if (!v) throw new Error(`${name} is not set (see scripts/e2e-stack.sh up)`);
  return v.replace(/\/+$/, "");
}

export const env = {
  get web() {
    return required("E2E_BASE_URL");
  },
  get edge() {
    return required("E2E_EDGE_URL");
  },
  get controlPlane() {
    return required("E2E_CONTROL_PLANE_URL");
  },
  get setupToken() {
    return required("E2E_SETUP_TOKEN");
  },
};

export const FIXTURE_PDF = path.join(__dirname, "fixtures", "raggie-e2e-handbook.pdf");
export const FIXTURE_NAME = "raggie-e2e-handbook.pdf";

/** A policy-compliant (12+ chars) random password. */
export function strongPassword(): string {
  return `E2e-${randomBytes(12).toString("base64url")}`;
}

export function uniqueEmail(prefix: string): string {
  return `${prefix}+${Date.now().toString(36)}${randomBytes(3).toString("hex")}@e2e.raggie.test`;
}

// ── Shared state written by the onboarding setup project ────────────────────
export type StackState = {
  adminEmail: string;
  adminPassword: string;
  orgId: string;
  workspaceId: string;
  workspaceName: string;
};

const STATE_DIR = path.join(__dirname, ".state");
const STATE_FILE = path.join(STATE_DIR, "stack.json");

export function saveState(state: StackState): void {
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

export function loadState(): StackState | null {
  return existsSync(STATE_FILE) ? (JSON.parse(readFileSync(STATE_FILE, "utf8")) as StackState) : null;
}

// ── Control-plane API (setup + negative checks) ─────────────────────────────
export async function cpLogin(request: APIRequestContext, email: string, password: string): Promise<string> {
  const res = await request.post(`${env.controlPlane}/api/v1/auth/login`, { data: { email, password } });
  expect(res.status(), await res.text()).toBe(200);
  return ((await res.json()) as { access_token: string }).access_token;
}

export function bearer(token: string) {
  return { Authorization: `Bearer ${token}` };
}

/** Upload the fixture straight to the control plane (direct upload path). */
export async function cpUploadFixture(request: APIRequestContext, token: string, workspaceId: string) {
  const res = await request.post(`${env.controlPlane}/api/v1/admin/workspaces/${workspaceId}/documents`, {
    headers: bearer(token),
    multipart: {
      file: { name: FIXTURE_NAME, mimeType: "application/pdf", buffer: readFileSync(FIXTURE_PDF) },
    },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}

type Doc = { filename: string; status: string };

/** Poll until the fixture is READY in the workspace (fails fast on FAILED). */
export async function waitForFixtureReady(fetchDocs: () => Promise<Doc[]>) {
  await expect
    .poll(
      async () => {
        const doc = (await fetchDocs()).find((d) => d.filename === FIXTURE_NAME);
        if (doc?.status === "FAILED") throw new Error("fixture ingestion FAILED");
        return doc?.status ?? "MISSING";
      },
      { timeout: 180_000, intervals: [1_000, 2_000, 5_000] },
    )
    .toBe("READY");
}

export async function cpDocs(request: APIRequestContext, token: string, workspaceId: string): Promise<Doc[]> {
  const res = await request.get(`${env.controlPlane}/api/v1/admin/workspaces/${workspaceId}/documents`, {
    headers: bearer(token),
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as Doc[];
}

// ── UI helpers ───────────────────────────────────────────────────────────────
export async function uiLogin(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** `test` with the English UI (NEXT_LOCALE=en) so role/name locators are stable,
 *  plus the onboarding state (skips when the setup project did not run). */
export const test = base.extend<{ englishUi: void; stack: StackState }>({
  englishUi: [
    async ({ context }, provide) => {
      const url = new URL(env.web);
      await context.addCookies([{ name: "NEXT_LOCALE", value: "en", domain: url.hostname, path: "/" }]);
      await provide();
    },
    { auto: true },
  ],
  // (The fixture callback is named `provide`, not `use`, so the React hooks
  // lint rule does not mistake it for a hook.)
  stack: async ({}, provide) => {
    const state = loadState();
    if (!state) throw new Error("no stack state — run the full e2e:stack suite (setup project) first");
    await provide(state);
  },
});

export { expect };
