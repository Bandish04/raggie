// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { decodeBrandIcon } from "./brand-icon.ts";

test("decodes a base64 raster icon with its content type", () => {
  const icon = decodeBrandIcon("data:image/png;base64,iVBORw0KGgo=");
  assert.ok(icon);
  assert.equal(icon.contentType, "image/png");
  assert.deepEqual([...icon.body.subarray(0, 4)], [0x89, 0x50, 0x4e, 0x47]);
});

test("accepts the common favicon raster types", () => {
  for (const t of ["image/jpeg", "image/gif", "image/webp", "image/x-icon", "image/vnd.microsoft.icon", "IMAGE/PNG"]) {
    assert.ok(decodeBrandIcon(`data:${t};base64,AAAA`), t);
  }
});

test("never serves SVG (script-capable when opened directly)", () => {
  assert.equal(decodeBrandIcon("data:image/svg+xml;base64,PHN2Zz48c2NyaXB0Lz48L3N2Zz4="), null);
  assert.equal(decodeBrandIcon("data:image/svg+xml,%3Csvg%3E%3C/svg%3E"), null);
  assert.equal(decodeBrandIcon("data:image/svg+xml;charset=utf-8;base64,PHN2Zz4="), null);
});

test("rejects non-image and untyped payloads", () => {
  assert.equal(decodeBrandIcon("data:text/html;base64,PHNjcmlwdD4="), null);
  assert.equal(decodeBrandIcon("data:,hello"), null);
  assert.equal(decodeBrandIcon("data:;base64,AAAA"), null);
  assert.equal(decodeBrandIcon("https://evil.tld/icon.png"), null);
  assert.equal(decodeBrandIcon(""), null);
});
