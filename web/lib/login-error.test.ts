// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { loginErrorFromResponse } from "./login-error.ts";

test("401 is invalid credentials", () => {
  assert.deepEqual(loginErrorFromResponse(401, null), { error: "invalid" });
});

test("429 (account lockout or per-IP limit) is 'locked' with whole minutes to wait", () => {
  assert.deepEqual(loginErrorFromResponse(429, "30"), { error: "locked", retryAfterMinutes: 1 });
  assert.deepEqual(loginErrorFromResponse(429, "61"), { error: "locked", retryAfterMinutes: 2 });
  assert.deepEqual(loginErrorFromResponse(429, "900"), { error: "locked", retryAfterMinutes: 15 });
});

test("429 without a usable Retry-After still reports 'locked'", () => {
  assert.deepEqual(loginErrorFromResponse(429, null), { error: "locked" });
  assert.deepEqual(loginErrorFromResponse(429, "soon"), { error: "locked" });
  assert.deepEqual(loginErrorFromResponse(429, "0"), { error: "locked" });
});

test("server errors and unreachable control plane are 'unavailable'", () => {
  assert.deepEqual(loginErrorFromResponse(503, null), { error: "unavailable" });
  assert.deepEqual(loginErrorFromResponse(0, null), { error: "unavailable" });
});

test("other client errors fall back to invalid credentials", () => {
  assert.deepEqual(loginErrorFromResponse(422, null), { error: "invalid" });
  assert.deepEqual(loginErrorFromResponse(403, null), { error: "invalid" });
});
