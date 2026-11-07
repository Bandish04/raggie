// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  abortableSleep,
  buildResumeRequest,
  parseReconnect,
  preStreamRetryDelayMs,
  retryAfterSeconds,
} from "./chat-retry.ts";

describe("retryAfterSeconds", () => {
  test("reads delta-seconds", () => {
    assert.equal(retryAfterSeconds("2"), 2);
    assert.equal(retryAfterSeconds(" 30 "), 30);
  });

  test("reads an HTTP date relative to now (rounded up, at least 1s)", () => {
    const now = Date.parse("2026-11-04T10:00:00Z");
    assert.equal(retryAfterSeconds("Wed, 04 Nov 2026 10:00:05 GMT", now), 5);
    assert.equal(retryAfterSeconds("Wed, 04 Nov 2026 09:59:00 GMT", now), 1);
  });

  test("absent or junk → null", () => {
    assert.equal(retryAfterSeconds(null), null);
    assert.equal(retryAfterSeconds(""), null);
    assert.equal(retryAfterSeconds("soon"), null);
    assert.equal(retryAfterSeconds("-3"), null);
  });
});

describe("preStreamRetryDelayMs", () => {
  test("a draining replica is retried once, after Retry-After", () => {
    assert.equal(preStreamRetryDelayMs(503, "draining", "2", 0), 2000);
  });

  test("draining without Retry-After uses a short default; long hints are capped", () => {
    assert.equal(preStreamRetryDelayMs(503, "draining", null, 0), 2000);
    assert.equal(preStreamRetryDelayMs(503, "draining", "120", 0), 10_000);
  });

  test("never retries twice, and never retries other failures", () => {
    assert.equal(preStreamRetryDelayMs(503, "draining", "2", 1), null);
    assert.equal(preStreamRetryDelayMs(429, "rate_limited", "5", 0), null);
    assert.equal(preStreamRetryDelayMs(503, "busy", "1", 0), null);
    assert.equal(preStreamRetryDelayMs(502, null, null, 0), null);
  });
});

describe("parseReconnect", () => {
  test("reads the drain reconnect event, including the turn to resume", () => {
    const data = JSON.stringify({
      reason: "server_shutdown",
      retry_after_ms: 2000,
      code: "draining",
      message: "The service is restarting.",
      conversation_id: "c-1",
      message_id: "m-9",
    });
    assert.deepEqual(parseReconnect(data), {
      delayMs: 2000,
      message: "The service is restarting.",
      conversationId: "c-1",
      messageId: "m-9",
    });
  });

  test("clamps the delay and tolerates missing fields", () => {
    assert.deepEqual(parseReconnect(JSON.stringify({ retry_after_ms: 999_999 })), {
      delayMs: 10_000,
      message: null,
      conversationId: null,
      messageId: null,
    });
    assert.deepEqual(parseReconnect("not json"), {
      delayMs: 2000,
      message: null,
      conversationId: null,
      messageId: null,
    });
  });
});

describe("buildResumeRequest", () => {
  const reconnect = { delayMs: 2000, message: null, conversationId: "c-1", messageId: "m-9" };

  test("resumes the interrupted assistant message instead of re-sending the question", () => {
    const body = buildResumeRequest(reconnect, { workspaceId: "ws-1", conversationId: null, locale: "en" });
    assert.deepEqual(body, {
      workspace_id: "ws-1",
      conversation_id: "c-1",
      resume_message_id: "m-9",
      locale: "en",
    });
    // No `message`: the edge must not persist a second user turn.
    assert.equal("message" in body!, false);
  });

  test("falls back to the conversation id from the stream's meta event", () => {
    const body = buildResumeRequest(
      { ...reconnect, conversationId: null },
      { workspaceId: "ws-1", conversationId: "c-meta", locale: "tr" },
    );
    assert.equal(body?.conversation_id, "c-meta");
  });

  test("cannot resume without the message id or a conversation", () => {
    assert.equal(
      buildResumeRequest({ ...reconnect, messageId: null }, { workspaceId: "ws-1", conversationId: "c", locale: "en" }),
      null,
    );
    assert.equal(
      buildResumeRequest(
        { ...reconnect, conversationId: null },
        { workspaceId: "ws-1", conversationId: null, locale: "en" },
      ),
      null,
    );
  });
});

describe("abortableSleep", () => {
  test("resolves after the delay", async () => {
    const t0 = Date.now();
    await abortableSleep(20);
    assert.ok(Date.now() - t0 >= 15);
  });

  test("rejects with AbortError when aborted (the user pressed Stop)", async () => {
    const ac = new AbortController();
    const p = abortableSleep(10_000, ac.signal);
    ac.abort();
    await assert.rejects(p, { name: "AbortError" });
  });

  test("rejects immediately for an already-aborted signal", async () => {
    const ac = new AbortController();
    ac.abort();
    await assert.rejects(abortableSleep(10_000, ac.signal), { name: "AbortError" });
  });
});
