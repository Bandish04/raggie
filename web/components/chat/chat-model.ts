// SPDX-License-Identifier: Apache-2.0
export type Source = {
  document_id?: string;
  filename?: string;
  text?: string;
  score?: number;
  type?: "web" | "doc";
  url?: string;
  title?: string;
  query?: string;
  retrieved_at?: string;
  excerpt?: string;
  read_status?: string;
};

export type Msg = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  id?: string; // BOT message id (from the SSE "done" event), for 👍/👎 feedback
  feedback?: "up" | "down";
  // A friendly, user-safe failure message (pre-stream JSON or mid-stream SSE
  // error). When set, the bubble renders in a calm error state with a retry.
  error?: string;
  // True while a web-search turn is retrieving from the web (before tokens).
  webSearching?: boolean;
  // Deep-research mode: the decomposed sub-queries (from the `deep_progress`
  // SSE event). Their presence drives the Gemini-style progress/recap panel.
  deepQueries?: string[];
  // True while a deep-research turn is decomposing/searching (before queries
  // arrive or before tokens stream) — drives the "Derin araştırma yapılıyor…"
  // header even if `deep_progress` hasn't landed yet.
  deepSearching?: boolean;
  // Live web/deep pipeline phase from `search_progress`: planning, searching,
  // reading, reranking, reflecting, synthesizing. Live-only.
  searchStatus?: string;
  // Live reasoning (chain-of-thought) streamed on the `thinking` SSE channel,
  // concatenated in arrival order. Live-only: never persisted, absent from
  // history. When unset the reasoning panel renders nothing.
  thinking?: string;
  // Flips true once the first answer token arrives, collapsing the reasoning
  // panel from its expanded live view into a compact disclosure.
  thinkingDone?: boolean;
  // True while the turn waits to be retried after an edge replica drained
  // (pre-stream 503 "draining" or a mid-stream `reconnect` event). Live-only.
  reconnecting?: boolean;
  // MCP tool steps for this turn, in arrival order. The edge emits `tool_call`
  // (a tool started) then `tool_result` (it finished); we render them as a calm
  // inline disclosure in the transcript so tool use is visible. Live-only.
  toolSteps?: ToolStep[];
};

// One agentic tool invocation surfaced in the transcript. Seeded by `tool_call`
// (status "running"), completed by the matching `tool_result` (→ "done"/"error").
export type ToolStep = {
  id: string; // edge-provided call id, used to match result→call
  name: string; // tool name (e.g. a Jira tool)
  status: "running" | "done" | "error";
};

export type Suggestion = { icon: string; title: string; desc: string; prompt: string };

export type ConvSummary = { id: string; title: string; created_at: string };

// How hard the model should reason before answering (sent as `reasoning_effort`).
export type ReasoningEffort = "low" | "medium" | "high";

export type StreamDelta = { kind: "thinking" | "answer"; text: string };

// Sentinel workspace value: search across ALL of the user's workspaces.
export const ALL_WORKSPACES = "__all__";

// How many conversations to fetch per page in the history sidebar. When the
// loaded count is a multiple of this, more may exist → show "load more". The
// edge endpoint only supports `limit` (no cursor), so we grow the limit.
export const CONV_PAGE = 10;

// Persist the active conversation id across reloads so context is never silently
// dropped (a ref alone resets on refresh, starting a fresh conversation).
export const ACTIVE_CONV_KEY = "raggie_active_conv";

// Persist the reasoning-effort choice across reloads (mirrors the sidebar-
// collapsed localStorage pattern). Defaults to "medium" when unset/invalid.
export const EFFORT_KEY = "raggie_reasoning_effort";

export const EFFORT_VALUES: ReasoningEffort[] = ["low", "medium", "high"];

export function parseSources(raw?: string): Source[] | undefined {
  if (!raw) return undefined;
  try {
    const a = JSON.parse(raw);
    return Array.isArray(a) ? (a as Source[]) : undefined;
  } catch {
    return undefined;
  }
}

export function sourceKey(source: Source): string {
  if (source.type === "web" || source.url) return `web:${source.url ?? source.title ?? ""}`;
  if (source.document_id) return `doc:${source.document_id}:${source.text ?? ""}`;
  return `doc:${source.filename ?? ""}:${source.text ?? ""}`;
}

export function mergeSources(current: Source[] | undefined, incoming: Source[]): Source[] {
  const merged = new Map<string, Source>();
  for (const source of current ?? []) merged.set(sourceKey(source), source);
  for (const source of incoming) merged.set(sourceKey(source), source);
  return [...merged.values()];
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// The page origin untrusted markdown URLs are resolved against. Answers only
// render client-side after a message arrives, but keep SSR safe: with no
// window, nothing counts as same-origin.
export function pageOrigin(): string {
  return typeof window !== "undefined" ? window.location.origin : "null:";
}

// An image the user attached to the next message (base64 data URL for the LLM).
export type Attachment = { dataUrl: string; mime: string; name: string };

/* Up to two initials from a display name, falling back to the email local-part.
   Used for the profile avatar (no photo upload in scope). */
export function initials(name?: string | null, email?: string): string {
  const src = (name && name.trim()) || (email ? email.split("@")[0] : "");
  if (!src) return "?";
  const parts = src.split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
