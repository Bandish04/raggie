// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { describe, test } from "node:test";

// widget/embed.js is a browser IIFE; loaded via require (no DOM) it exports its
// pure helpers instead of mounting, so the SSE/retry rules are testable here.
const require = createRequire(import.meta.url);
const widget = require(path.join(import.meta.dirname, "..", "..", "widget", "embed.js")) as {
  parseFrame(raw: string): { event: string; data: string } | null;
  retryAfterMs(header: string | null): number | null;
  reconnectDelayMs(data: string): number;
  errorText(body: unknown, fallback: string): string;
  pickLocale(lang: string | undefined): "tr" | "en";
  shouldRetryPreStream(status: number, body: unknown, attempt: number): boolean;
  resumeBody(
    workspaceId: string,
    reconnectData: string,
    fallbackConversationId: string | null,
    locale: string,
  ): Record<string, string> | null;
};

describe("widget parseFrame", () => {
  test("reads event + data, defaulting to the message event", () => {
    assert.deepEqual(widget.parseFrame('data: {"delta":"hi"}'), { event: "message", data: '{"delta":"hi"}' });
    assert.deepEqual(widget.parseFrame('event: reconnect\ndata: {"retry_after_ms":2000}'), {
      event: "reconnect",
      data: '{"retry_after_ms":2000}',
    });
  });

  test("skips empty frames and the [DONE] sentinel", () => {
    assert.equal(widget.parseFrame("event: meta"), null);
    assert.equal(widget.parseFrame("data: [DONE]"), null);
  });
});

describe("widget retry rules", () => {
  test("Retry-After seconds → ms, capped; absent/junk → null", () => {
    assert.equal(widget.retryAfterMs("2"), 2000);
    assert.equal(widget.retryAfterMs("120"), 10_000);
    assert.equal(widget.retryAfterMs(null), null);
    assert.equal(widget.retryAfterMs("soon"), null);
  });

  test("reconnect delay from the event, with a default and a cap", () => {
    assert.equal(widget.reconnectDelayMs('{"retry_after_ms":1500}'), 1500);
    assert.equal(widget.reconnectDelayMs('{"retry_after_ms":999999}'), 10_000);
    assert.equal(widget.reconnectDelayMs("{}"), 2000);
    assert.equal(widget.reconnectDelayMs("garbage"), 2000);
  });

  test("only a draining 503 is retried, and only once", () => {
    assert.equal(widget.shouldRetryPreStream(503, { code: "draining" }, 0), true);
    assert.equal(widget.shouldRetryPreStream(503, { error: "draining" }, 0), true);
    assert.equal(widget.shouldRetryPreStream(503, { code: "draining" }, 1), false);
    assert.equal(widget.shouldRetryPreStream(503, { code: "busy" }, 0), false);
    assert.equal(widget.shouldRetryPreStream(429, { code: "rate_limited" }, 0), false);
    assert.equal(widget.shouldRetryPreStream(503, null, 0), false);
  });
});

describe("widget messages", () => {
  test("shows the edge's localized message, else the fallback", () => {
    assert.equal(widget.errorText({ code: "rate_limited", message: "Çok hızlı." }, "x"), "Çok hızlı.");
    assert.equal(widget.errorText({ code: "busy" }, "fallback"), "fallback");
    assert.equal(widget.errorText(null, "fallback"), "fallback");
  });

  test("request locale follows the browser language (tr or en)", () => {
    assert.equal(widget.pickLocale("tr-TR"), "tr");
    assert.equal(widget.pickLocale("en-GB"), "en");
    assert.equal(widget.pickLocale("de-DE"), "en");
    assert.equal(widget.pickLocale(undefined), "en");
  });
});

describe("widget resume", () => {
  const reconnect = JSON.stringify({
    reason: "server_shutdown",
    retry_after_ms: 2000,
    code: "draining",
    message: "Restarting",
    conversation_id: "c-1",
    message_id: "m-9",
  });

  test("a reconnect resumes the interrupted message — no question re-sent", () => {
    const body = widget.resumeBody("ws-1", reconnect, null, "tr");
    assert.deepEqual(body, {
      workspace_id: "ws-1",
      conversation_id: "c-1",
      resume_message_id: "m-9",
      locale: "tr",
    });
    assert.equal("message" in body!, false);
  });

  test("uses the conversation from meta when the event lacks it", () => {
    const data = JSON.stringify({ retry_after_ms: 2000, message_id: "m-9" });
    assert.equal(widget.resumeBody("ws-1", data, "c-meta", "en")?.conversation_id, "c-meta");
  });

  test("no message id or conversation → cannot resume", () => {
    assert.equal(widget.resumeBody("ws-1", JSON.stringify({ conversation_id: "c" }), null, "en"), null);
    assert.equal(widget.resumeBody("ws-1", JSON.stringify({ message_id: "m" }), null, "en"), null);
    assert.equal(widget.resumeBody("ws-1", "garbage", "c", "en"), null);
  });
});
