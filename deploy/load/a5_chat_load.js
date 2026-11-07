// SPDX-License-Identifier: Apache-2.0

// A5 load test — design target of 50k concurrent chat streams against the edge
// SSE hot path (a target, not a measured result).
//
// Models concurrent users streaming a RAG answer and asserts the A5 SLOs:
//   - TTFB p95 <= 1.5 s          (time to the first SSE byte)
//   - inter-token p95 <= 120 ms  (mean gap between streamed deltas)
//   - error rate < 0.5%
//   - graceful shedding: 503 + Retry-After at the bounded-pool ceiling (never 5xx storms)
//
// Run (against a cluster sized for 50k — never a laptop):
//   EDGE=https://chat.raggie.example WS=<workspace_id> TOKEN=<widget_or_admin_jwt> \
//     k6 run --vus 50000 --duration 5m deploy/load/a5_chat_load.js
//
// Scale the fleet from a CI env var so smaller smoke runs reuse the same script:
//   VUS=500 DURATION=1m k6 run -e VUS=500 deploy/load/a5_chat_load.js
import http from "k6/http";
import { check } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";

const EDGE = __ENV.EDGE || "http://localhost:8080";
const WS = __ENV.WS || "demo-workspace";
const TOKEN = __ENV.TOKEN || "";
const VUS = parseInt(__ENV.VUS || "50000", 10);
const DURATION = __ENV.DURATION || "5m";

const ttfb = new Trend("sse_ttfb", true);
const interToken = new Trend("sse_inter_token", true);
const shed = new Counter("shed_503");
const errors = new Rate("errors");

export const options = {
  scenarios: {
    chat: { executor: "constant-vus", vus: VUS, duration: DURATION },
  },
  thresholds: {
    sse_ttfb: ["p(95)<1500"],
    sse_inter_token: ["p(95)<120"],
    errors: ["rate<0.005"],
  },
};

const QUESTIONS = [
  "Summarize the onboarding policy.",
  "What is our refund window?",
  "List the supported file formats.",
  "How do I reset my password?",
];

export default function () {
  const headers = { "Content-Type": "application/json" };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;

  const body = JSON.stringify({
    workspace_id: WS,
    message: QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)],
  });

  const start = Date.now();
  // k6's http client buffers the body, but timings.waiting is the TTFB proxy and
  // the response body lets us measure inter-token cadence from the SSE frames.
  const res = http.post(`${EDGE}/api/v1/chat/stream`, body, { headers, timeout: "60s" });

  // Graceful shedding at the bounded-pool ceiling is success, not error.
  if (res.status === 503) {
    shed.add(1);
    check(res, { "shed has Retry-After": (r) => !!r.headers["Retry-After"] });
    return;
  }

  const ok = check(res, {
    "status 200": (r) => r.status === 200,
    "is event-stream": (r) => (r.headers["Content-Type"] || "").includes("text/event-stream"),
    "streamed deltas": (r) => r.body && r.body.indexOf('"delta"') !== -1,
  });
  errors.add(!ok);

  ttfb.add(res.timings.waiting);

  // Approximate inter-token latency: stream wall-time / number of delta frames.
  const deltas = (res.body.match(/"delta"/g) || []).length;
  if (deltas > 1) {
    interToken.add((Date.now() - start - res.timings.waiting) / deltas);
  }
}
