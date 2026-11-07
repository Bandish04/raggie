// SPDX-License-Identifier: Apache-2.0

// HA chaos load driver (runs in-cluster as a pod; see scripts/ha/chaos.sh).
//
// MODE=bootstrap  create (or log into) the first admin, create a workspace and
//                 print one `STATE {...}` line for the following runs.
// MODE=load       mixed traffic for DURATION while chaos.sh breaks things:
//   chat    CHAT_VUS users streaming /api/v1/chat/stream through the edge
//   upload  UPLOAD_RATE documents/s into the workspace (ingestion path)
//   web     WEB_VUS users loading /login (web) and /api/v1/auth/me (control-plane)
//
// Every acknowledged write is logged so chaos.sh can verify it afterwards:
//   ACK_MSG <bot message id>   a chat turn that ended with `event: done`
//   ACK_DOC <document id>      an upload answered 201
// A stream a draining edge ends with `event: reconnect` is resumed like the web
// client does: wait retry_after_ms, then POST again with resume_message_id (the
// draining replica is unready, so another one answers) until `event: done`.
// Pass/fail (per run, set by chaos.sh): 5xx up to MAX_5XX, connection errors
// (status 0) up to MAX_CONN_ERRORS, in-stream `event: error` up to
// MAX_SSE_ERRORS and failed resumes up to MAX_RESUME_FAILED (all default 0). An edge 503 with Retry-After is graceful
// shedding, never a 5xx.
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const EDGE = __ENV.EDGE_URL;
const CP = __ENV.CP_URL;
const WEB = __ENV.WEB_URL;
const MODE = __ENV.MODE || "load";
const DURATION = __ENV.DURATION || "60s";
const CHAT_VUS = parseInt(__ENV.CHAT_VUS || "4", 10);
const WEB_VUS = parseInt(__ENV.WEB_VUS || "2", 10);
const UPLOAD_RATE = parseInt(__ENV.UPLOAD_RATE || "0", 10);
const UPLOAD_KB = parseInt(__ENV.UPLOAD_KB || "4", 10);
const MAX_5XX = parseInt(__ENV.MAX_5XX || "0", 10);
const MAX_CONN_ERRORS = parseInt(__ENV.MAX_CONN_ERRORS || "0", 10);
const MAX_SSE_ERRORS = parseInt(__ENV.MAX_SSE_ERRORS || "0", 10);
const MAX_RESUME_FAILED = parseInt(__ENV.MAX_RESUME_FAILED || "0", 10);
const MAX_RESUME_ATTEMPTS = 3;
const RUN_ID = __ENV.RUN_ID || `${Date.now()}`;

const fiveXX = new Counter("http_5xx");
const connErrors = new Counter("conn_errors");
const shed = new Counter("shed_503");
const reconnects = new Counter("sse_reconnect");
const resumed = new Counter("sse_resumed");
const resumeFailed = new Counter("resume_failed");
const sseErrors = new Counter("sse_errors");
const chatDone = new Counter("chat_done");
const uploadsAcked = new Counter("uploads_acked");

function scenarios() {
  if (MODE === "bootstrap") {
    return { bootstrap: { executor: "shared-iterations", vus: 1, iterations: 1, exec: "bootstrap" } };
  }
  const s = {};
  if (CHAT_VUS > 0) s.chat = { executor: "constant-vus", vus: CHAT_VUS, duration: DURATION, exec: "chat" };
  if (WEB_VUS > 0) s.web = { executor: "constant-vus", vus: WEB_VUS, duration: DURATION, exec: "web" };
  if (UPLOAD_RATE > 0) {
    s.upload = {
      executor: "constant-arrival-rate",
      rate: UPLOAD_RATE,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: Math.max(2, UPLOAD_RATE * 4),
      exec: "upload",
    };
  }
  return s;
}

export const options = {
  scenarios: scenarios(),
  thresholds:
    MODE === "bootstrap"
      ? {}
      : {
          http_5xx: [`count<=${MAX_5XX}`],
          conn_errors: [`count<=${MAX_CONN_ERRORS}`],
          sse_errors: [`count<=${MAX_SSE_ERRORS}`],
          resume_failed: [`count<=${MAX_RESUME_FAILED}`],
        },
  summaryTrendStats: ["avg", "p(95)", "max"],
};

function auth(token) {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

// Classify one response; returns true when it is a success for the caller.
function classify(res, { allowShed = false } = {}) {
  if (res.status === 0) {
    connErrors.add(1);
    console.warn(`conn error ${res.request.method} ${res.url}: ${res.error}`);
    return false;
  }
  if (res.status === 503 && allowShed && res.headers["Retry-After"]) {
    shed.add(1);
    return false;
  }
  if (res.status >= 500) {
    fiveXX.add(1);
    console.error(`5xx ${res.status} ${res.request.method} ${res.url}: ${String(res.body).slice(0, 200)}`);
    return false;
  }
  return true;
}

export function bootstrap() {
  const email = __ENV.ADMIN_EMAIL;
  const password = __ENV.ADMIN_PASSWORD;
  const st = http.get(`${CP}/api/v1/onboarding/state`);
  if (st.status !== 200) throw new Error(`onboarding state ${st.status}: ${st.body}`);
  let token;
  let orgId;
  if (!st.json("has_super_admin")) {
    const res = http.post(
      `${CP}/api/v1/onboarding/bootstrap`,
      JSON.stringify({ email, password, org_name: "Chaos Org", setup_token: __ENV.SETUP_TOKEN }),
      { headers: { "Content-Type": "application/json" } },
    );
    if (res.status !== 201) throw new Error(`bootstrap ${res.status}: ${res.body}`);
    token = res.json("access_token");
    orgId = res.json("org_id");
  } else {
    const res = http.post(`${CP}/api/v1/auth/login`, JSON.stringify({ email, password }), {
      headers: { "Content-Type": "application/json" },
    });
    if (res.status !== 200) throw new Error(`login ${res.status}: ${res.body}`);
    token = res.json("access_token");
    orgId = http.get(`${CP}/api/v1/auth/me`, { headers: auth(token) }).json("org_id");
  }
  let ws = http.post(
    `${CP}/api/v1/onboarding/workspace`,
    JSON.stringify({ type: "INTERNAL", name: `chaos-${RUN_ID}` }),
    { headers: auth(token) },
  );
  if (ws.status !== 201) {
    // Already onboarded: create through the admin API instead.
    ws = http.post(
      `${CP}/api/v1/admin/orgs/${orgId}/workspaces`,
      JSON.stringify({ type: "INTERNAL", name: `chaos-${RUN_ID}` }),
      { headers: auth(token) },
    );
  }
  if (ws.status !== 201) throw new Error(`workspace ${ws.status}: ${ws.body}`);
  const body = ws.json();
  const wsId = (body.workspace && body.workspace.id) || body.id;
  console.log(`STATE ${JSON.stringify({ token, workspace_id: wsId })}`);
}

const QUESTIONS = [
  "What does the chaos handbook say about failover drills?",
  "Summarize the replication policy.",
  "Which team owns the incident runbook?",
  "How long is the data retention window?",
];

function sseData(text, event) {
  const m = text.match(new RegExp(`event: ${event}\ndata: (\\{[^\n]*\\})`));
  return m ? JSON.parse(m[1]) : null;
}

function stream(body) {
  return http.post(`${EDGE}/api/v1/chat/stream`, JSON.stringify(body), { headers: auth(__ENV.TOKEN), timeout: "90s" });
}

// resume follows `event: reconnect` until the turn ends; returns the final body
// or null (counted in resume_failed).
function resume(text) {
  for (let attempt = 0; attempt < MAX_RESUME_ATTEMPTS && text.includes("event: reconnect"); attempt++) {
    const rc = sseData(text, "reconnect");
    if (!rc || !rc.message_id) break;
    sleep((rc.retry_after_ms || 2000) / 1000);
    const res = stream({
      workspace_id: __ENV.WS,
      conversation_id: rc.conversation_id,
      resume_message_id: rc.message_id,
    });
    if (!classify(res) || res.status !== 200) {
      console.error(`resume ${rc.message_id}: ${res.status} ${String(res.body || "").slice(0, 200)}`);
      break;
    }
    text = String(res.body || "");
  }
  if (text.includes("event: done")) {
    resumed.add(1);
    return text;
  }
  resumeFailed.add(1);
  return null;
}

export function chat() {
  const res = stream({
    workspace_id: __ENV.WS,
    message: `${QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)]} (${RUN_ID}-${__VU}-${__ITER})`,
  });
  if (!classify(res, { allowShed: true })) {
    sleep(1);
    return;
  }
  let text = String(res.body || "");
  if (text.includes("event: reconnect")) {
    // A draining replica interrupted the turn: graceful, but it must resume.
    reconnects.add(1);
    text = resume(text);
    if (text === null) return;
  }
  if (text.includes("event: error")) {
    sseErrors.add(1);
    const e = text.match(/event: error\ndata: ([^\n]*)/);
    console.error(`sse error: ${e ? e[1].slice(0, 200) : "?"}`);
    return;
  }
  const ok = check(res, {
    "chat 200": (r) => r.status === 200,
    "chat done": () => text.includes("event: done"),
  });
  if (ok) {
    chatDone.add(1);
    const meta = sseData(text, "meta");
    if (meta && meta.message_id) console.log(`ACK_MSG ${meta.message_id}`);
  }
}

export function upload() {
  const marker = `${RUN_ID}-${__VU}-${__ITER}`;
  const para = `Chaos handbook ${marker}: failover drills run weekly; replication keeps two copies; the incident runbook is owned by the platform team. `;
  const content = para.repeat(Math.max(1, Math.floor((UPLOAD_KB * 1024) / para.length)));
  const res = http.post(
    `${CP}/api/v1/admin/workspaces/${__ENV.WS}/documents`,
    { file: http.file(content, `chaos-${marker}.txt`, "text/plain") },
    { headers: { Authorization: `Bearer ${__ENV.TOKEN}` }, timeout: "60s" },
  );
  if (!classify(res)) return;
  if (check(res, { "upload 201": (r) => r.status === 201 })) {
    uploadsAcked.add(1);
    console.log(`ACK_DOC ${res.json("id")}`);
  }
}

export function web() {
  classify(http.get(`${WEB}/login`, { timeout: "30s" }));
  classify(http.get(`${CP}/api/v1/auth/me`, { headers: auth(__ENV.TOKEN), timeout: "30s" }));
  sleep(0.5);
}
