// SPDX-License-Identifier: Apache-2.0

import { expect, test } from "@playwright/test";

import {
  ANSWER_STREAM_CHARS_PER_FRAME,
  takeStreamingPrefix,
} from "../lib/streaming";

test("burst answers are split into bounded render frames", () => {
  const answer = "API Gateway yanıtı ".repeat(20);
  const chunks: string[] = [];
  let rest = answer;

  while (rest) {
    const next = takeStreamingPrefix(rest);
    chunks.push(next.chunk);
    rest = next.rest;
  }

  expect(chunks.length).toBeGreaterThan(1);
  expect(chunks.join("")).toBe(answer);
  expect(chunks.every((chunk) => Array.from(chunk).length <= ANSWER_STREAM_CHARS_PER_FRAME)).toBe(
    true,
  );
});

test("paced rendering preserves Unicode code points", () => {
  const value = "Merhaba 👋🏽 dünya";
  const first = takeStreamingPrefix(value, 9);

  expect(first.chunk + first.rest).toBe(value);
  expect(first.chunk).not.toMatch(/\p{Surrogate}$/u);
});

test("burst reasoning is rendered across multiple visible frames", () => {
  const reasoning = "Önce kaynakları karşılaştırıyorum. ".repeat(30);
  const chunks: string[] = [];
  let rest = reasoning;

  while (rest) {
    const next = takeStreamingPrefix(rest);
    chunks.push(next.chunk);
    rest = next.rest;
  }

  expect(chunks.length).toBeGreaterThan(10);
  expect(chunks.join("")).toBe(reasoning);
});
