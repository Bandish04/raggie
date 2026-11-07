// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { parseSseFrame, readSseFrames } from "./chat-sse.ts";

describe("parseSseFrame", () => {
  test("reads the event name and joins data lines", () => {
    assert.deepEqual(parseSseFrame('event: sources\ndata: {"a":\ndata: 1}'), { event: "sources", data: '{"a":1}' });
  });
  test("defaults to the message event", () => {
    assert.deepEqual(parseSseFrame('data: {"delta":"hi"}'), { event: "message", data: '{"delta":"hi"}' });
  });
  test("skips frames without data and the [DONE] sentinel", () => {
    assert.equal(parseSseFrame("event: ping"), null);
    assert.equal(parseSseFrame(": comment"), null);
    assert.equal(parseSseFrame("data: [DONE]"), null);
  });
});

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const chunk of chunks) c.enqueue(enc.encode(chunk));
      c.close();
    },
  });
}

describe("readSseFrames", () => {
  test("splits on blank lines across chunk boundaries", async () => {
    const frames: string[] = [];
    await readSseFrames(streamOf(["data: a\n", "\ndata: b\n\nevent: x\nda", "ta: c\n\n"]), (f) => frames.push(f));
    assert.deepEqual(frames, ["data: a", "data: b", "event: x\ndata: c"]);
  });
  test("delivers a trailing frame without the final blank line", async () => {
    const frames: string[] = [];
    await readSseFrames(streamOf(["data: a\n\ndata: tail"]), (f) => frames.push(f));
    assert.deepEqual(frames, ["data: a", "data: tail"]);
  });
  test("decodes multi-byte characters split across chunks", async () => {
    const bytes = new TextEncoder().encode("data: ğü\n\n");
    const frames: string[] = [];
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(bytes.slice(0, 7));
        c.enqueue(bytes.slice(7));
        c.close();
      },
    });
    await readSseFrames(body, (f) => frames.push(f));
    assert.deepEqual(frames, ["data: ğü"]);
  });
});
