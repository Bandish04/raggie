// SPDX-License-Identifier: Apache-2.0

// Server-sent-event framing for the chat stream (/api/chat): frames are split
// on blank lines, then read as an `event:` name (default "message") plus the
// concatenated `data:` lines.

export type SseFrame = { event: string; data: string };

/** One frame, or null when it carries no data (comments, pings, `[DONE]`). */
export function parseSseFrame(frame: string): SseFrame | null {
  let event = "message";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data || data === "[DONE]") return null;
  return { event, data };
}

/** Read the response body to the end, calling `onFrame` with each raw frame
 *  (a trailing frame without the final blank line included). Rejects when the
 *  read fails, e.g. with an AbortError when the request is stopped. */
export async function readSseFrames(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: string) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const drainFrames = () => {
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      onFrame(buf.slice(0, idx));
      buf = buf.slice(idx + 2);
    }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    drainFrames();
  }
  buf += decoder.decode();
  drainFrames();
  if (buf.trim()) onFrame(buf);
}
