// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { withDefaultLocale } from "@/lib/chat-request";
import { forwardedHeaders } from "@/lib/security/forwarded";
import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";
import { uiLocale } from "@/lib/ui-locale";

// SSE proxy: the browser streams from same-origin /api/chat; we forward to the Go
// edge server-side (attaching the session token) and pipe the event stream back.
// At scale the Ingress routes /api/v1/chat/* straight to the edge (browser ->
// edge) to keep Next.js off the 50k-SSE path; proxying keeps the dev flow simple.
//
// STREAMING CORRECTNESS: the answer must arrive token-by-token, not all at once.
// Two things would otherwise buffer it: (1) Next compressing the response (gzip
// holds bytes until its buffer fills) — defeated by `compress: false` in
// next.config + `Cache-Control: no-transform`; (2) Next buffering a piped fetch
// body — defeated by re-streaming each chunk through an explicit ReadableStream
// `pull` as it arrives. `X-Accel-Buffering: no` covers any nginx/ingress in front.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const fetchCache = "force-no-store";

const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

// Failures raised here (before reaching the edge) use the edge's error
// envelope, so the chat UI handles every error the same way.
function proxyError(status: number, code: "unauthorized" | "internal_error"): Response {
  return Response.json({ error: code, code }, { status });
}

export const POST = withSameOrigin(async function POST(req: NextRequest) {
  const token = await getFreshAccessToken();
  if (!token) return proxyError(401, "unauthorized");
  // UI locale → Accept-Language (edge error `message` language) and the body's
  // `locale` when the client omitted it (prompt template).
  const locale = uiLocale(req.cookies.get("NEXT_LOCALE")?.value);
  const body = withDefaultLocale(await req.text(), locale);
  const idempotencyKey = req.headers.get("idempotency-key");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
    "Accept-Language": locale,
    // End-user IP/proto for edge's per-client limits and logs.
    ...forwardedHeaders(req.headers),
  };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  let edgeRes: Response;
  try {
    edgeRes = await fetch(`${EDGE_URL}/api/v1/chat/stream`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    // Edge unreachable (restart, network): a JSON error, not an HTML 500 page.
    return proxyError(502, "internal_error");
  }

  // A non-2xx (e.g. a pre-stream 503 shed or 401) returns its JSON error
  // envelope ({error, code, message}) as-is.
  if (!edgeRes.ok || !edgeRes.body) {
    const headers: Record<string, string> = {
      "Content-Type": edgeRes.headers.get("Content-Type") ?? "application/json",
    };
    // 429 rate_limited / 503 draining: the UI shows (or waits for) Retry-After.
    const retryAfter = edgeRes.headers.get("Retry-After");
    if (retryAfter) headers["Retry-After"] = retryAfter;
    return new Response(edgeRes.body, { status: edgeRes.status, headers });
  }

  // Re-stream: enqueue each upstream chunk the instant it arrives (no
  // accumulate-then-flush), so deltas reach the browser as the model emits them.
  const reader = edgeRes.body.getReader();
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await reader.read();
      if (done) {
        controller.close();
        return;
      }
      controller.enqueue(value);
    },
    cancel(reason) {
      void reader.cancel(reason);
    },
  });

  return new Response(stream, {
    status: edgeRes.status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
});
