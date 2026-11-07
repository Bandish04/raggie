// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { isSameOriginRequest, withSameOrigin } from "./origin.ts";

const URL_ = "http://web:3000/api/chat";

function h(init: Record<string, string>): Headers {
  return new Headers(init);
}

describe("isSameOriginRequest", () => {
  test("safe methods are always allowed", () => {
    for (const method of ["GET", "HEAD", "OPTIONS"]) {
      assert.equal(isSameOriginRequest(method, URL_, h({ origin: "https://evil.tld" })), true);
    }
  });

  test("allows a mutating request whose Origin matches Host", () => {
    const headers = h({ host: "raggie.local:3000", origin: "http://raggie.local:3000" });
    assert.equal(isSameOriginRequest("POST", URL_, headers), true);
  });

  test("prefers X-Forwarded-Host (reverse proxy / TLS terminator)", () => {
    const headers = h({
      host: "web:3000",
      "x-forwarded-host": "chat.example.com, web:3000",
      origin: "https://chat.example.com",
    });
    assert.equal(isSameOriginRequest("DELETE", URL_, headers), true);
  });

  test("rejects a cross-site Origin for every mutating method", () => {
    for (const method of ["POST", "PUT", "PATCH", "DELETE", "post"]) {
      const headers = h({ host: "raggie.local:3000", origin: "https://evil.tld" });
      assert.equal(isSameOriginRequest(method, URL_, headers), false, method);
    }
  });

  test("rejects a look-alike host (suffix / port mismatch)", () => {
    assert.equal(
      isSameOriginRequest("POST", URL_, h({ host: "raggie.local", origin: "http://raggie.local.evil.tld" })),
      false,
    );
    assert.equal(
      isSameOriginRequest("POST", URL_, h({ host: "raggie.local:3000", origin: "http://raggie.local:4000" })),
      false,
    );
  });

  test("rejects the opaque 'null' Origin (sandboxed iframes, data: pages)", () => {
    assert.equal(isSameOriginRequest("POST", URL_, h({ host: "raggie.local", origin: "null" })), false);
  });

  test("falls back to Referer when Origin is absent", () => {
    assert.equal(
      isSameOriginRequest("POST", URL_, h({ host: "raggie.local", referer: "http://raggie.local/chat?x=1" })),
      true,
    );
    assert.equal(
      isSameOriginRequest("POST", URL_, h({ host: "raggie.local", referer: "https://evil.tld/raggie.local" })),
      false,
    );
  });

  test("rejects a mutating request with neither Origin nor Referer", () => {
    assert.equal(isSameOriginRequest("POST", URL_, h({ host: "raggie.local" })), false);
  });

  test("uses the request URL host when no Host header is present", () => {
    assert.equal(isSameOriginRequest("POST", URL_, h({ origin: "http://web:3000" })), true);
  });

  test("accepts origins listed in PUBLIC_WEB_URL (comma-separated)", () => {
    const headers = h({ host: "web:3000", origin: "https://chat.example.com" });
    assert.equal(isSameOriginRequest("POST", URL_, headers), false);
    assert.equal(
      isSameOriginRequest("POST", URL_, headers, "https://other.example.com, https://chat.example.com/"),
      true,
    );
  });
});

describe("withSameOrigin", () => {
  test("returns 403 JSON without invoking the handler on a cross-site request", async () => {
    let called = false;
    const handler = withSameOrigin(async () => {
      called = true;
      return new Response("ok");
    });
    const req = new Request("http://raggie.local/api/conversations", {
      method: "DELETE",
      headers: { origin: "https://evil.tld" },
    });
    const res = await handler(req);
    assert.equal(res.status, 403);
    assert.equal(called, false);
    assert.equal(res.headers.get("content-type")?.startsWith("application/json"), true);
  });

  test("passes the request and route context through on a same-origin request", async () => {
    const handler = withSameOrigin(async (req: Request, ctx: { params: Promise<{ id: string }> }) => {
      const { id } = await ctx.params;
      return new Response(`${req.method}:${id}`);
    });
    const req = new Request("http://raggie.local/api/conversations/42", {
      method: "DELETE",
      headers: { origin: "http://raggie.local" },
    });
    const res = await handler(req, { params: Promise.resolve({ id: "42" }) });
    assert.equal(res.status, 200);
    assert.equal(await res.text(), "DELETE:42");
  });
});
