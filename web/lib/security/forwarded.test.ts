// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { forwardedHeaders } from "./forwarded.ts";

test("forwards the client IP Next recorded and the protocol", () => {
  const h = new Headers({ "x-forwarded-for": "203.0.113.7", "x-forwarded-proto": "https" });
  assert.deepEqual(forwardedHeaders(h), {
    "X-Forwarded-For": "203.0.113.7",
    "X-Forwarded-Proto": "https",
  });
});

test("preserves an upstream reverse-proxy chain in order", () => {
  const h = new Headers({ "x-forwarded-for": "198.51.100.1, 10.0.0.5", "x-forwarded-proto": "http" });
  assert.equal(forwardedHeaders(h)["X-Forwarded-For"], "198.51.100.1, 10.0.0.5");
});

test("normalises IPv6 brackets and IPv4 ports; keeps IPv4-mapped IPv6", () => {
  const h = new Headers({ "x-forwarded-for": "[2001:db8::1]:443, 203.0.113.9:51234, ::ffff:10.1.2.3" });
  assert.equal(forwardedHeaders(h)["X-Forwarded-For"], "2001:db8::1, 203.0.113.9, ::ffff:10.1.2.3");
});

test("drops non-IP entries (they would become arbitrary rate-limit keys)", () => {
  const h = new Headers({ "x-forwarded-for": "unknown, evil-key-123, , 203.0.113.7" });
  assert.equal(forwardedHeaders(h)["X-Forwarded-For"], "203.0.113.7");
});

test("caps the chain to the right-most (closest, most trusted) hops", () => {
  const many = Array.from({ length: 40 }, (_, i) => `198.51.100.${i + 1}`).join(", ");
  const chain = forwardedHeaders(new Headers({ "x-forwarded-for": many }))["X-Forwarded-For"].split(", ");
  assert.equal(chain.length, 16);
  assert.equal(chain.at(-1), "198.51.100.40");
});

test("omits headers that are absent or invalid", () => {
  assert.deepEqual(forwardedHeaders(new Headers()), {});
  assert.deepEqual(forwardedHeaders(new Headers({ "x-forwarded-for": "nope", "x-forwarded-proto": "gopher" })), {});
  assert.deepEqual(forwardedHeaders(new Headers({ "x-forwarded-proto": "HTTPS, http" })), {
    "X-Forwarded-Proto": "https",
  });
});
