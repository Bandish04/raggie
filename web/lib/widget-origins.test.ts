// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { addOrigin, normalizeOrigin, removeOrigin } from "./widget-origins.ts";

test("accepts scheme://host[:port] and returns the browser-serialized origin", () => {
  assert.deepEqual(normalizeOrigin("https://shop.example.com"), {
    ok: true,
    origin: "https://shop.example.com",
  });
  assert.deepEqual(normalizeOrigin("http://localhost:3000"), {
    ok: true,
    origin: "http://localhost:3000",
  });
  assert.deepEqual(normalizeOrigin("http://127.0.0.1:8080"), {
    ok: true,
    origin: "http://127.0.0.1:8080",
  });
});

// The edge compares the browser's Origin header byte-for-byte, so the stored
// value must be exactly what a browser sends.
test("normalizes case, a trailing slash, default ports and IDN hosts", () => {
  assert.deepEqual(normalizeOrigin("  HTTPS://Shop.Example.COM/  "), {
    ok: true,
    origin: "https://shop.example.com",
  });
  assert.deepEqual(normalizeOrigin("https://example.com:443"), {
    ok: true,
    origin: "https://example.com",
  });
  assert.deepEqual(normalizeOrigin("http://example.com:80"), {
    ok: true,
    origin: "http://example.com",
  });
  assert.deepEqual(normalizeOrigin("https://bücher.example"), {
    ok: true,
    origin: "https://xn--bcher-kva.example",
  });
});

test("rejects empty input", () => {
  assert.deepEqual(normalizeOrigin(""), { ok: false, reason: "empty" });
  assert.deepEqual(normalizeOrigin("   "), { ok: false, reason: "empty" });
});

test("rejects wildcards (the control plane refuses them too)", () => {
  assert.deepEqual(normalizeOrigin("*"), { ok: false, reason: "wildcard" });
  assert.deepEqual(normalizeOrigin("https://*.example.com"), { ok: false, reason: "wildcard" });
});

test("rejects a missing or non-http(s) scheme", () => {
  assert.deepEqual(normalizeOrigin("example.com"), { ok: false, reason: "scheme" });
  assert.deepEqual(normalizeOrigin("ftp://example.com"), { ok: false, reason: "scheme" });
  assert.deepEqual(normalizeOrigin("javascript:alert(1)"), { ok: false, reason: "scheme" });
});

test("rejects paths, queries and fragments", () => {
  assert.deepEqual(normalizeOrigin("https://example.com/shop"), { ok: false, reason: "path" });
  assert.deepEqual(normalizeOrigin("https://example.com/?a=1"), { ok: false, reason: "path" });
  assert.deepEqual(normalizeOrigin("https://example.com#top"), { ok: false, reason: "path" });
});

test("rejects credentials, IPv6 literals and malformed hosts", () => {
  assert.deepEqual(normalizeOrigin("https://user:pw@example.com"), { ok: false, reason: "invalid" });
  assert.deepEqual(normalizeOrigin("http://[::1]:3000"), { ok: false, reason: "invalid" });
  assert.deepEqual(normalizeOrigin("https://exa mple.com"), { ok: false, reason: "invalid" });
  assert.deepEqual(normalizeOrigin("https://"), { ok: false, reason: "invalid" });
});

test("addOrigin appends the normalized origin and refuses duplicates", () => {
  assert.deepEqual(addOrigin([], "https://a.example/"), {
    ok: true,
    origins: ["https://a.example"],
  });
  assert.deepEqual(addOrigin(["https://a.example"], "HTTPS://A.EXAMPLE:443"), {
    ok: false,
    reason: "duplicate",
  });
  assert.deepEqual(addOrigin(["https://a.example"], "a.example"), {
    ok: false,
    reason: "scheme",
  });
});

test("addOrigin does not mutate the input list", () => {
  const list = ["https://a.example"];
  addOrigin(list, "https://b.example");
  assert.deepEqual(list, ["https://a.example"]);
});

test("removeOrigin drops exactly that origin", () => {
  assert.deepEqual(removeOrigin(["https://a.example", "https://b.example"], "https://a.example"), [
    "https://b.example",
  ]);
  assert.deepEqual(removeOrigin(["https://a.example"], "https://c.example"), ["https://a.example"]);
});
