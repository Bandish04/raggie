// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// The CSP's img-src is the backstop behind the markdown image allowlist: a
// remote <img> that slipped through must still not load. next.config.ts cannot
// be imported here (it is CommonJS-resolved by Next and uses __dirname), so its
// source is read; the served header is also checked end to end (e2e/chat/
// admin-markdown.spec.ts).
const CONFIG = readFileSync(path.join(import.meta.dirname, "..", "..", "next.config.ts"), "utf8");

test("img-src allows only this origin and inline data/blob images", () => {
  const directives = [...CONFIG.matchAll(/"img-src ([^"]*)"/g)].map((m) => m[1]);
  assert.deepEqual(directives, ["'self' data: blob:"]);
});

test("the app-wide CSP header is the csp built above", () => {
  assert.match(CONFIG, /\{ key: "Content-Security-Policy", value: csp \}/);
  assert.match(CONFIG, /source: "\/:path\*"/);
});
