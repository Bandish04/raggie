// SPDX-License-Identifier: Apache-2.0

// Edge error contract (services/edge/internal/httpserver/errors.go): a failure
// before streaming is JSON {"error": code, "code": code, "message": text}; a
// failure mid-stream is an SSE `event: error` with {"code", "message"}. `code`
// is stable (translate it); `message` is the edge's user-safe default in the
// request locale (use it for codes this UI does not know yet).

export const EDGE_ERROR_CODES = [
  "busy",
  "retrieval_error",
  "upstream_error",
  "bad_request",
  "payload_too_large",
  "not_found",
  "unauthorized",
  "forbidden",
  "conflict",
  "rate_limited",
  "draining",
  "unavailable",
  "internal_error",
  "parse_failed",
  "stream_error",
] as const;

export type EdgeErrorCode = (typeof EDGE_ERROR_CODES)[number];

const KNOWN: ReadonlySet<string> = new Set(EDGE_ERROR_CODES);

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

/** `code` is a known code (else null, so callers fall back to `message`). */
export function parseEdgeError(body: unknown): { code: EdgeErrorCode | null; message: string | null } {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { code: null, message: null };
  const b = body as { code?: unknown; error?: unknown; message?: unknown };
  const raw = text(b.code) ?? text(b.error);
  return {
    code: raw && KNOWN.has(raw) ? (raw as EdgeErrorCode) : null,
    message: text(b.message),
  };
}
