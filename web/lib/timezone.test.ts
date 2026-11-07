// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { FALLBACK_TIMEZONE, browserTimezone, resolveTimezone } from "./timezone.ts";

test("a stored timezone always wins", () => {
  assert.equal(resolveTimezone(" Europe/Berlin ", () => "Asia/Tokyo"), "Europe/Berlin");
});

test("no stored zone: the browser's zone", () => {
  assert.equal(resolveTimezone(null, () => "Asia/Tokyo"), "Asia/Tokyo");
  assert.equal(resolveTimezone(undefined, () => "Asia/Tokyo"), "Asia/Tokyo");
  assert.equal(resolveTimezone("  ", () => "Asia/Tokyo"), "Asia/Tokyo");
});

test("no stored zone and no usable browser zone: UTC", () => {
  assert.equal(FALLBACK_TIMEZONE, "UTC");
  assert.equal(resolveTimezone(null, () => undefined), "UTC");
  assert.equal(resolveTimezone(null, () => ""), "UTC");
  assert.equal(resolveTimezone(null, () => {
    throw new Error("Intl unavailable");
  }), "UTC");
});

test("browserTimezone reads Intl and never throws", () => {
  const zone = browserTimezone();
  assert.ok(zone === undefined || (typeof zone === "string" && zone.length > 0));
});
