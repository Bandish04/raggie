// SPDX-License-Identifier: Apache-2.0

import { defineConfig, devices } from "@playwright/test";

/**
 * Chat characterization suite (e2e/chat): the real production build of the web
 * app against a Node stub of the control plane + edge (e2e/chat/stub-server.mjs)
 * that plays scripted SSE streams. No Docker, no backend.
 *
 *   pnpm build                                  # once (uses .next)
 *   pnpm test:chat                              # starts the stub + `next start`
 */
const STUB_PORT = Number(process.env.CHAT_STUB_PORT ?? 58130);
const WEB_PORT = Number(process.env.CHAT_WEB_PORT ?? 3315);
const stub = `http://127.0.0.1:${STUB_PORT}`;

export default defineConfig({
  testDir: "./e2e/chat",
  outputDir: "./test-results/chat",
  // One stub with a shared request log: keep specs sequential.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: "node e2e/chat/stub-server.mjs",
      url: `${stub}/healthz`,
      env: { CHAT_STUB_PORT: String(STUB_PORT) },
      reuseExistingServer: false,
    },
    {
      command: `pnpm exec next start -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/healthz`,
      env: {
        CONTROL_PLANE_URL: stub,
        EDGE_URL: stub,
        // Shows the composer's image attachment control.
        VISION_MODELS: "model-a",
        PORT: String(WEB_PORT),
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
