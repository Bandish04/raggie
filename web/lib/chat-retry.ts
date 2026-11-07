// SPDX-License-Identifier: Apache-2.0

// Retry rules for the chat stream when an edge replica drains (rolling deploy,
// scale-down). Two signals, each handled at most ONCE per turn:
//   - pre-stream: 503 {code:"draining"} with Retry-After (seconds) — nothing
//     was persisted, so the identical request is re-sent;
//   - mid-stream: SSE `event: reconnect` {reason:"server_shutdown",
//     retry_after_ms, code:"draining", message, conversation_id, message_id} —
//     the partial answer is persisted, so the turn is RESUMED by message id.
// A 429 {code:"rate_limited"} is never auto-retried; the UI shows the hint.

const DEFAULT_RETRY_MS = 2000;
const MAX_RETRY_MS = 10_000;

const clampDelay = (ms: number) => Math.min(Math.max(ms, 0), MAX_RETRY_MS);

/** Retry-After as whole seconds (delta-seconds or an HTTP date), else null. */
export function retryAfterSeconds(header: string | null, nowMs = Date.now()): number | null {
  const v = header?.trim();
  if (!v) return null;
  if (/^\d+$/.test(v)) return Number(v);
  // HTTP-date form ("Wed, 04 Nov 2026 10:00:05 GMT"); Date.parse alone would
  // also accept junk like "-3" as a year.
  if (!/[a-z]/i.test(v)) return null;
  const at = Date.parse(v);
  if (Number.isNaN(at)) return null;
  return Math.max(1, Math.ceil((at - nowMs) / 1000));
}

/** Delay before re-sending a turn whose request was refused, or null when it
 *  must not be retried (only a draining replica, only on the first attempt). */
export function preStreamRetryDelayMs(
  status: number,
  code: string | null,
  retryAfter: string | null,
  attempt: number,
): number | null {
  if (attempt > 0 || status !== 503 || code !== "draining") return null;
  const secs = retryAfterSeconds(retryAfter);
  return clampDelay(secs !== null ? secs * 1000 : DEFAULT_RETRY_MS);
}

export type Reconnect = {
  delayMs: number;
  message: string | null;
  conversationId: string | null;
  messageId: string | null;
};

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

/** The SSE `reconnect` payload: how long to wait, the edge's message, and the
 *  interrupted turn (conversation + assistant message id) to resume. */
export function parseReconnect(data: string): Reconnect {
  try {
    const d = JSON.parse(data) as Record<string, unknown>;
    const ms = typeof d.retry_after_ms === "number" && Number.isFinite(d.retry_after_ms) ? d.retry_after_ms : null;
    return {
      delayMs: clampDelay(ms ?? DEFAULT_RETRY_MS),
      message: str(d.message),
      conversationId: str(d.conversation_id),
      messageId: str(d.message_id),
    };
  } catch {
    return { delayMs: DEFAULT_RETRY_MS, message: null, conversationId: null, messageId: null };
  }
}

/** The edge resume request for an interrupted turn: same endpoint, no
 *  `message` (so no second user turn is stored), the assistant message id from
 *  `reconnect`/`meta`. Null when the turn cannot be identified. The edge answers
 *  400 (not resumable / already resumed) or 404 (unknown / foreign); callers
 *  then stop and keep the partial answer. */
export function buildResumeRequest(
  reconnect: Reconnect,
  turn: { workspaceId: string; conversationId: string | null; locale: string },
): { workspace_id: string; conversation_id: string; resume_message_id: string; locale: string } | null {
  const conversationId = reconnect.conversationId ?? turn.conversationId;
  if (!reconnect.messageId || !conversationId) return null;
  return {
    workspace_id: turn.workspaceId,
    conversation_id: conversationId,
    resume_message_id: reconnect.messageId,
    locale: turn.locale,
  };
}

/** setTimeout as a promise that rejects with an AbortError when `signal` aborts
 *  (the Stop button), so a pending retry is cancelled with the turn. */
export function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("Aborted", "AbortError"));
    if (signal?.aborted) return abort();
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      abort();
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
