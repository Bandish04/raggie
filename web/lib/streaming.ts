// SPDX-License-Identifier: Apache-2.0

export const ANSWER_STREAM_CHARS_PER_FRAME = 12;

// Split by Unicode code points so paced rendering never cuts an emoji or another
// surrogate pair in half. The remainder stays queued for the next animation frame.
export function takeStreamingPrefix(
  text: string,
  maxCodePoints = ANSWER_STREAM_CHARS_PER_FRAME,
): { chunk: string; rest: string } {
  if (!text || maxCodePoints <= 0) return { chunk: "", rest: text };

  let end = 0;
  let count = 0;
  while (end < text.length && count < maxCodePoints) {
    const codePoint = text.codePointAt(end);
    end += codePoint !== undefined && codePoint > 0xffff ? 2 : 1;
    count += 1;
  }
  return { chunk: text.slice(0, end), rest: text.slice(end) };
}
