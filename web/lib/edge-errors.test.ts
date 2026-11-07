// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

import { EDGE_ERROR_CODES, parseEdgeError } from "./edge-errors.ts";

test("knows every edge error code (services/edge/internal/httpserver/errors.go)", () => {
  assert.deepEqual([...EDGE_ERROR_CODES].sort(), [
    "bad_request",
    "busy",
    "conflict",
    "draining",
    "forbidden",
    "internal_error",
    "not_found",
    "parse_failed",
    "payload_too_large",
    "rate_limited",
    "retrieval_error",
    "stream_error",
    "unauthorized",
    "unavailable",
    "upstream_error",
  ]);
});

test("reads the stable code and the edge's default message", () => {
  assert.deepEqual(parseEdgeError({ error: "busy", code: "busy", message: "Busy, retry." }), {
    code: "busy",
    message: "Busy, retry.",
  });
});

test("falls back to the legacy `error` field when `code` is absent", () => {
  assert.deepEqual(parseEdgeError({ error: "rate_limited", message: "Slow down" }), {
    code: "rate_limited",
    message: "Slow down",
  });
});

test("unknown codes are kept out of the map but their message survives", () => {
  assert.deepEqual(parseEdgeError({ code: "brand_new_code", message: "Something new" }), {
    code: null,
    message: "Something new",
  });
});

test("tolerates junk: non-objects, wrong types, blank strings", () => {
  for (const junk of [null, undefined, "oops", 42, [], { code: 7, message: { x: 1 } }, { code: "", message: "  " }]) {
    assert.deepEqual(parseEdgeError(junk), { code: null, message: null });
  }
});

test("every known code has a chat.edgeErrors message in both locales", () => {
  for (const locale of ["en", "tr"]) {
    const file = path.join(import.meta.dirname, "..", "messages", `${locale}.json`);
    const messages = JSON.parse(readFileSync(file, "utf8")) as { chat: { edgeErrors?: Record<string, string> } };
    const missing = EDGE_ERROR_CODES.filter((c) => !messages.chat.edgeErrors?.[c]?.trim());
    assert.deepEqual(missing, [], `${locale}.json is missing chat.edgeErrors entries`);
  }
});
