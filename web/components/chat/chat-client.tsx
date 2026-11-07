// SPDX-License-Identifier: Apache-2.0

"use client";

import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { signOutAction } from "@/app/actions/auth";
import { BrandLogo, BrandName } from "@/components/branding-provider";
import NotificationsInbox from "@/components/chat/notifications-inbox";
import ScheduledTasksModal from "@/components/chat/scheduled-tasks-modal";
import SettingsModal from "@/components/settings/settings-modal";
import { useResolvedTimezone } from "@/lib/use-resolved-timezone";
import type { SettingsTab } from "@/components/settings/account-settings";
import { Modal } from "@/components/ui/modal";
import Select from "@/components/ui/select";
import type {
  AnswerStyle,
  AvailableIntegration,
  MemoryItem,
  ModelsConfig,
  Notification,
  ProfileResponse,
  ScheduledTask,
  Skill,
  WorkspaceSummary,
} from "@/lib/api";
import {
  abortableSleep,
  buildResumeRequest,
  parseReconnect,
  preStreamRetryDelayMs,
  type Reconnect,
  retryAfterSeconds,
} from "@/lib/chat-retry";
import { parseSseFrame, readSseFrames } from "@/lib/chat-sse";
import { parseEdgeError } from "@/lib/edge-errors";

import {
  ACTIVE_CONV_KEY,
  ALL_WORKSPACES,
  type Attachment,
  CONV_PAGE,
  type ConvSummary,
  EFFORT_KEY,
  EFFORT_VALUES,
  mergeSources,
  type Msg,
  newIdempotencyKey,
  parseSources,
  type ReasoningEffort,
  type Source,
  type Suggestion,
} from "@/components/chat/chat-model";
import { Icon } from "@/components/chat/chat-ui";
import { AssistantMessage } from "@/components/chat/assistant-message";
import { useStreamPacing } from "@/components/chat/use-stream-pacing";
import {
  ComposerModelPicker,
  ComposerToolsMenu,
  SkillPicker,
} from "@/components/chat/composer-menus";
import { AccountMenu, SidebarSkillsMenu, SidebarToolsMenu } from "@/components/chat/sidebar-menus";
export default function ChatClient({
  workspaces,
  visionEnabled = false,
  userRole,
  userName = null,
  userEmail = "",
  answerStyle,
  models = { default_model: null, allowed_models: [] },
  preferredModel = null,
  skills = [],
  profile = null,
  memory = [],
  tasks = [],
  notifications = { items: [], unread: 0 },
  tools = [],
  timezone: storedTimezone = null,
}: {
  workspaces: WorkspaceSummary[];
  visionEnabled?: boolean;
  userRole?: string;
  userName?: string | null;
  userEmail?: string;
  answerStyle?: AnswerStyle;
  models?: ModelsConfig;
  preferredModel?: string | null;
  // The org's enabled skills (versioned execution policies) — the "/command"
  // picker + sidebar menu. The edge resolves policy from id + version.
  skills?: Skill[];
  // Data for the in-chat settings modal (full profile + remembered facts),
  // fetched server-side by the chat page alongside the rest.
  profile?: ProfileResponse | null;
  memory?: MemoryItem[];
  // Scheduled tasks (cron jobs) + the notifications inbox, fetched server-side.
  // The user's IANA timezone seeds new tasks (NL parse + create).
  tasks?: ScheduledTask[];
  notifications?: { items: Notification[]; unread: number };
  // The org's connected MCP integrations (no secrets) — the sidebar "Araçlar"
  // menu. Toggling them on seeds `mcp_tools` so the agent can call them this turn.
  tools?: AvailableIntegration[];
  // The user's stored zone; null = not set. The browser's zone (else UTC) is
  // resolved after mount, never during the server render.
  timezone?: string | null;
}) {
  const t = useTranslations();
  const timezone = useResolvedTimezone(storedTimezone);
  const locale = useLocale();
  const suggestions = t.raw("chat.suggestions") as Suggestion[];
  const [wsId, setWsId] = useState(workspaces[0]?.id ?? "");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  // Desktop-only: collapse the sidebar to reclaim space (persisted). Lazy
  // initializer reads localStorage once at mount — no setState-in-effect.
  const [collapsed, setCollapsed] = useState(() =>
    typeof window !== "undefined" &&
    localStorage.getItem("raggie_chat_sidebar_collapsed") === "1",
  );
  function toggleCollapsed() {
    setCollapsed((c) => {
      const next = !c;
      if (typeof window !== "undefined")
        localStorage.setItem("raggie_chat_sidebar_collapsed", next ? "1" : "0");
      return next;
    });
  }
  // Reasoning effort (low/medium/high) for this account, persisted across reloads.
  // Lazy initializer reads localStorage once at mount — no setState-in-effect.
  const [effort, setEffort] = useState<ReasoningEffort>(() => {
    if (typeof window === "undefined") return "medium";
    const saved = localStorage.getItem(EFFORT_KEY);
    return EFFORT_VALUES.includes(saved as ReasoningEffort) ? (saved as ReasoningEffort) : "medium";
  });
  function changeEffort(next: string) {
    if (!EFFORT_VALUES.includes(next as ReasoningEffort)) return;
    setEffort(next as ReasoningEffort);
    if (typeof window !== "undefined") localStorage.setItem(EFFORT_KEY, next);
  }
  const [atBottom, setAtBottom] = useState(true);
  const [conversations, setConversations] = useState<ConvSummary[]>([]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  // Client-side filter over the loaded recents ("Sohbetlerde ara"). Empty → the
  // normal recents (with load-more); non-empty → only title-matching rows.
  const [convQuery, setConvQuery] = useState("");
  // Web-search fallback: an offer surfaced by the edge when docs don't answer,
  // and a manual "always search the web" toggle (lives in the composer "+" menu).
  const [webOffer, setWebOffer] = useState<{ question: string } | null>(null);
  const [webMode, setWebMode] = useState(false);
  // Deep-research mode: a richer web turn that decomposes the question into
  // sub-queries and writes a sourced synthesis. Mutually exclusive with the
  // plain web toggle (you pick one mode).
  const [deepMode, setDeepMode] = useState(false);
  // Tools (MCP) mode: a per-turn opt-in to let the agent call the org's connected
  // MCP tools (e.g. Jira). NOT mutually exclusive with web/deep — they compose in
  // one turn. Sent as `mcp_tools`; only meaningful when tools exist for the org.
  const [toolsMode, setToolsMode] = useState(false);
  // The active skill (assistant preset) for this thread. Picked via "/command"
  // or the sidebar Skills menu; stays active across turns until the user removes
  // its chip. Applied at send time by mapping it onto the chat request fields.
  const [activeSkillId, setActiveSkillId] = useState<string | null>(null);
  const activeSkill = skills.find((skill) => skill.id === activeSkillId) ?? null;
  // The composer keeps focus while the "/" picker is open, so it forwards
  // arrow/enter/escape to the picker through this handle.
  const skillKeyHandler = useRef<((e: React.KeyboardEvent) => boolean) | null>(null);
  // Mutually-exclusive tool toggles (ChatGPT-style): turning one on clears the
  // other. Surfaced both in the "+" menu (checked) and as removable chips.
  function toggleWeb() {
    setWebMode((v) => {
      const next = !v;
      if (next) setDeepMode(false);
      return next;
    });
  }
  function toggleDeep() {
    setDeepMode((v) => {
      const next = !v;
      if (next) setWebMode(false);
      return next;
    });
  }
  // The edge emits `web_unavailable` when the web toggle was on but web search
  // is disabled for this workspace — we surface a calm note explaining why
  // nothing was searched (the answer still comes from documents).
  const [webUnavailable, setWebUnavailable] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  // History paging: current fetch limit + a flag while loading the next page.
  const [convLimit, setConvLimit] = useState(CONV_PAGE);
  const [loadingMore, setLoadingMore] = useState(false);
  // Whether the server may have MORE history than we've loaded. Set false the
  // moment a page comes back shorter than requested (the true end) — this is what
  // stops the loader instead of the old "length % PAGE === 0" guess, which never
  // terminated when the total was an exact multiple of the page size.
  const [hasMore, setHasMore] = useState(true);
  // Single-delete: the row awaiting an inline "Sil?" confirm, the id currently
  // being deleted (disables its controls), and a transient per-row error flag.
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteErrorId, setDeleteErrorId] = useState<string | null>(null);
  // Clear-all: a confirm modal, an in-flight flag, and a transient error.
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState(false);
  // Account/settings dialog (ChatGPT/Claude-style), opened from the profile menu
  // over the chat instead of navigating to /account. `settingsTab` chooses which
  // section it lands on (Profil from "Profil ayarları", Tercihler from "Tercihler").
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("profile");
  function openSettings(tab: SettingsTab) {
    setSettingsTab(tab);
    setSettingsOpen(true);
  }
  // Scheduled-tasks modal (cron jobs), opened from the sidebar entry.
  const [tasksOpen, setTasksOpen] = useState(false);
  // Server actions must run inside a transition when invoked programmatically.
  const [, startSignOut] = useTransition();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const conversationId = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const recentsRef = useRef<HTMLElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Set by an SSE `reconnect` event: the current stream ends and the turn is
  // resumed once (by assistant message id) after the delay.
  const reconnectRef = useRef<Reconnect | null>(null);
  // After a reconnect retry is accepted, the partial answer stays visible until
  // the first fresh token, which replaces it (no duplicated half-answer).
  const replaceAnswerRef = useRef(false);

  const noWorkspaces = workspaces.length === 0;
  const allMode = wsId === ALL_WORKSPACES;
  const activeWs = workspaces.find((w) => w.id === wsId);
  const empty = messages.length === 0;
  const lastAssistantIdx = messages.map((m) => m.role).lastIndexOf("assistant");
  // Screen-reader status for the turn asked in this session: announced at
  // start and end only (not per token), so the transcript itself is not live.
  const [liveTurn, setLiveTurn] = useState(false);
  const lastAssistant = lastAssistantIdx >= 0 ? messages[lastAssistantIdx] : undefined;
  const liveStatus = streaming
    ? t("chat.thinking")
    : liveTurn && lastAssistant
      ? lastAssistant.error
        ? t("chat.answerFailed")
        : t("chat.answerReady")
      : "";
  // Admin surfaces (Dashboard, Knowledge Base) are hidden from plain members.
  const isAdmin = !!userRole && userRole !== "STAFF";

  // "/command" skill picker: open while the composer text is just a slash query
  // (starts with "/", no spaces yet) and the org actually has skills to offer.
  const slashMatch = /^\/(\S*)$/.exec(input);
  const skillPickerOpen = skills.length > 0 && slashMatch !== null;
  const skillQuery = slashMatch?.[1] ?? "";

  // Activate a skill (from "/" or the sidebar menu): set it and clear any "/…"
  // text so the composer is ready for the actual question.
  const pickSkill = useCallback((skill: Skill) => {
    setActiveSkillId(skill.id);
    setInput((prev) => (/^\/\S*$/.test(prev) ? "" : prev));
    inputRef.current?.focus();
  }, []);

  // Model selection: when the deployment exposes allowed models we send the
  // chosen one as an override (`hasModel`). The PICKER, however, only appears
  // when there's an actual choice (>1) — a single fixed model needs no UI.
  // Initial value = user's preferred model ?? config default ?? first allowed.
  const allowedModels = models.allowed_models ?? [];
  const hasModel = allowedModels.length > 0;
  const showModelPicker = allowedModels.length > 1;
  const [model, setModel] = useState<string>(() => {
    if (preferredModel && allowedModels.includes(preferredModel)) return preferredModel;
    if (models.default_model && allowedModels.includes(models.default_model))
      return models.default_model;
    return allowedModels[0] ?? "";
  });

  // Recents shown in the sidebar: the full list, or — while searching — only the
  // conversations whose title matches the query (case-insensitive, client-side).
  const convFilter = convQuery.trim().toLowerCase();
  const filteredConversations = convFilter
    ? conversations.filter((c) => (c.title || "").toLowerCase().includes(convFilter))
    : conversations;

  // History "load more" is offered only while the server still has more (the last
  // page came back FULL). Hidden while searching (the filter runs over what's
  // already loaded). `hasMore` flips false on the first short page — so a user
  // with exactly 10 (or any multiple of 10) chats no longer loops forever.
  const canLoadMore = !convFilter && hasMore && conversations.length > 0;

  // Auto-grow the textarea with content (capped), and reset after send.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  // Smart autoscroll: follow the stream only while the user is at the bottom.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: streaming ? "auto" : "smooth" });
    }
  }, [messages, atBottom, streaming]);

  function onScroll() {
    const el = scrollRef.current;
    if (el) setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  }

  // If the recents list doesn't overflow its container yet but more pages may
  // exist, fetch the next page so infinite scroll can engage (otherwise the
  // user has nothing to scroll). No-ops while searching or already loading.
  useEffect(() => {
    if (!canLoadMore || loadingMore) return;
    const el = recentsRef.current;
    if (el && el.scrollHeight <= el.clientHeight) void loadMoreConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations, canLoadMore, loadingMore]);

  function jumpToLatest() {
    const el = scrollRef.current;
    el?.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setAtBottom(true);
  }

  function patchLast(fn: (m: Msg) => Msg) {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last?.role === "assistant") copy[copy.length - 1] = fn(last);
      return copy;
    });
  }

  const { enqueueStreamDelta, flushStreamDeltas, waitForStreamDrain } = useStreamPacing(patchLast);

  async function loadConversations(limit = convLimit) {
    try {
      const res = await fetch(`/api/conversations?limit=${limit}`, { cache: "no-store" });
      if (res.ok) {
        const list = (await res.json()) as ConvSummary[];
        setConversations(list);
        // A page shorter than requested means we've hit the end — stop offering more.
        setHasMore(list.length >= limit);
      }
    } catch {
      /* ignore — history is best-effort */
    }
  }

  // Grow the page and refetch (the edge has no cursor; we widen the limit).
  async function loadMoreConversations() {
    if (loadingMore) return;
    setLoadingMore(true);
    const next = convLimit + CONV_PAGE;
    setConvLimit(next);
    try {
      await loadConversations(next);
    } finally {
      setLoadingMore(false);
    }
  }

  // Infinite scroll for the recents list: when scrolled near the bottom of its
  // own container, auto-load the next page. No-ops while searching (the filter
  // runs over the already-loaded set) or when there's nothing more to load.
  function onRecentsScroll() {
    if (!canLoadMore || loadingMore) return;
    const el = recentsRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) {
      void loadMoreConversations();
    }
  }

  // Load chat history on mount. We intentionally do NOT auto-reopen the last
  // active conversation: every visit starts on a clean "new chat" welcome state,
  // and past chats remain one click away in the recent-history sidebar.
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch(`/api/conversations?limit=${CONV_PAGE}`, { cache: "no-store" });
        if (active && res.ok) {
          const list = (await res.json()) as ConvSummary[];
          setConversations(list);
          setHasMore(list.length >= CONV_PAGE);
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function openConversation(id: string) {
    if (streaming) return;
    try {
      const res = await fetch(`/api/conversations/${id}/messages`, { cache: "no-store" });
      if (!res.ok) return;
      const turns = (await res.json()) as { role: "user" | "assistant"; content: string; sources?: string }[];
      setMessages(
        turns.map((m) => ({
          role: m.role,
          content: m.content,
          sources: m.role === "assistant" ? parseSources(m.sources) : undefined,
        })),
      );
      conversationId.current = id;
      setLiveTurn(false);
      setActiveConv(id);
      if (typeof window !== "undefined") sessionStorage.setItem(ACTIVE_CONV_KEY, id);
      setNavOpen(false);
      setAtBottom(true);
      setWebOffer(null);
      setWebUnavailable(false);
      // Dismiss any half-started inline delete confirm on another row.
      setConfirmDeleteId(null);
      setDeleteErrorId(null);
    } catch {
      /* ignore */
    }
  }

  function newChat() {
    if (streaming) return;
    setLiveTurn(false);
    setMessages([]);
    conversationId.current = null;
    setActiveConv(null);
    if (typeof window !== "undefined") sessionStorage.removeItem(ACTIVE_CONV_KEY);
    setInput("");
    setNavOpen(false);
    setWebOffer(null);
    setWebUnavailable(false);
    inputRef.current?.focus();
  }

  // Delete a single conversation after the inline "Sil?" confirm. On success
  // drop it from the list; if it was open, reset the stage via newChat().
  async function deleteConversation(id: string) {
    if (deletingId) return;
    setDeletingId(id);
    setDeleteErrorId(null);
    try {
      const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
      // 204 on success, 404 if already gone/not owned — both mean "no longer here".
      if (res.ok || res.status === 404) {
        setConversations((prev) => prev.filter((c) => c.id !== id));
        setConfirmDeleteId(null);
        if (activeConv === id) newChat();
      } else {
        setDeleteErrorId(id);
      }
    } catch {
      setDeleteErrorId(id);
    } finally {
      setDeletingId(null);
    }
  }

  // Clear the user's entire chat history, then reset the stage.
  async function clearHistory() {
    if (clearing) return;
    setClearing(true);
    setClearError(false);
    try {
      const res = await fetch("/api/conversations", { method: "DELETE" });
      if (!res.ok) {
        setClearError(true);
        return;
      }
      setConversations([]);
      setClearOpen(false);
      newChat();
    } catch {
      setClearError(true);
    } finally {
      setClearing(false);
    }
  }

  // A known edge error code → its translation; otherwise the edge's own
  // (Accept-Language localized) message; otherwise the generic fallback.
  function edgeErrorText(body: unknown): string {
    const { code, message } = parseEdgeError(body);
    if (code) return t(`chat.edgeErrors.${code}`);
    return message ?? t("chat.errorGeneric");
  }

  // First streamed token of a reconnect retry: drop the previous attempt's
  // partial answer/reasoning so the fresh answer is not appended to it.
  function startFreshAttemptIfPending() {
    if (!replaceAnswerRef.current) return;
    replaceAnswerRef.current = false;
    flushStreamDeltas();
    patchLast((m) => ({ ...m, content: "", thinking: undefined, thinkingDone: undefined, error: undefined }));
  }

  function handleFrame(frame: string) {
    const parsed = parseSseFrame(frame);
    if (!parsed) return;
    const { event, data } = parsed;
    if (event === "deep_progress") {
      // Deep research: the question was decomposed into sub-queries (emitted once,
      // before searching). Store them on the in-flight bubble so the progress
      // panel can show — and later keep — what's being researched.
      try {
        const p = JSON.parse(data) as { queries?: string[] };
        const queries = Array.isArray(p.queries) ? p.queries.filter((q) => typeof q === "string") : [];
        patchLast((m) => ({ ...m, deepQueries: queries, deepSearching: true }));
      } catch {
        /* ignore malformed frame */
      }
    } else if (event === "search_progress") {
      try {
        const p = JSON.parse(data) as { status?: string };
        if (p.status) patchLast((m) => ({ ...m, searchStatus: p.status }));
      } catch {
        /* ignore malformed frame */
      }
    } else if (event === "tool_call") {
      // An MCP tool started this turn. Append a "running" step to the bubble (or
      // refresh an existing one by id) so tool use is visible in the transcript.
      try {
        const c = JSON.parse(data) as { id?: string; name?: string; tool?: string };
        const id = c.id ?? c.name ?? c.tool ?? `${Date.now()}`;
        const name = c.name ?? c.tool ?? id;
        patchLast((m) => {
          const steps = m.toolSteps ?? [];
          if (steps.some((s) => s.id === id)) return m;
          return { ...m, toolSteps: [...steps, { id, name, status: "running" }] };
        });
      } catch {
        /* ignore malformed frame */
      }
    } else if (event === "tool_result") {
      // The matching tool finished. Flip its step to done/error by id (fall back
      // to the last running step when the edge omits an id).
      try {
        const r = JSON.parse(data) as {
          id?: string;
          name?: string;
          tool?: string;
          ok?: boolean;
          error?: unknown;
        };
        const id = r.id ?? r.name ?? r.tool;
        const ok = typeof r.ok === "boolean" ? r.ok : !r.error;
        patchLast((m) => {
          const steps = m.toolSteps ?? [];
          if (steps.length === 0) return m;
          const idx = id
            ? steps.findIndex((s) => s.id === id)
            : steps.map((s) => s.status).lastIndexOf("running");
          if (idx < 0) return m;
          const next = steps.slice();
          next[idx] = { ...next[idx], status: ok ? "done" : "error" };
          return { ...m, toolSteps: next };
        });
      } catch {
        /* ignore malformed frame */
      }
    } else if (event === "sources") {
      try {
        const parsed = JSON.parse(data) as { sources?: Source[] };
        // Sources landed → the "searching"/"researching" phase is over.
        patchLast((m) => ({
          ...m,
          sources: mergeSources(m.sources, parsed.sources ?? []),
          webSearching: false,
          deepSearching: false,
        }));
      } catch {
        /* ignore malformed frame */
      }
    } else if (event === "reconnect") {
      // The edge replica is shutting down mid-answer (partial answer already
      // persisted). Keep what arrived, show "reconnecting…", resume once.
      flushStreamDeltas();
      reconnectRef.current = parseReconnect(data);
      patchLast((m) => ({
        ...m,
        reconnecting: true,
        webSearching: false,
        deepSearching: false,
        searchStatus: undefined,
      }));
    } else if (event === "thinking") {
      // Provider-supplied reasoning shares the same paced queue as answer text,
      // preserving event order even when the upstream sends a large burst.
      try {
        const d = JSON.parse(data) as { delta?: string };
        if (d.delta) {
          startFreshAttemptIfPending();
          enqueueStreamDelta("thinking", d.delta);
        }
      } catch {
        /* ignore malformed frame */
      }
    } else if (event === "error") {
      flushStreamDeltas();
      // Mid-stream failure: the edge sends {code, message} before the stream
      // closes. Render it gracefully and stop following tokens.
      try {
        const e: unknown = JSON.parse(data);
        patchLast((m) => ({
          ...m,
          error: edgeErrorText(e),
          webSearching: false,
          deepSearching: false,
          searchStatus: undefined,
        }));
      } catch {
        patchLast((m) => ({
          ...m,
          error: t("chat.errorGeneric"),
          webSearching: false,
          deepSearching: false,
          searchStatus: undefined,
        }));
      }
    } else if (event === "meta") {
      try {
        const meta = JSON.parse(data) as { conversation_id?: string; message_id?: string };
        // message_id = this turn's assistant message: the id a drain resume uses
        // (a resumed stream's meta repeats the same id) and the feedback target.
        if (meta.message_id) patchLast((m) => ({ ...m, id: meta.message_id }));
        if (meta.conversation_id) {
          conversationId.current = meta.conversation_id;
          setActiveConv(meta.conversation_id);
          if (typeof window !== "undefined")
            sessionStorage.setItem(ACTIVE_CONV_KEY, meta.conversation_id);
        }
      } catch {
        /* ignore */
      }
    } else if (event === "web_offer") {
      try {
        const o = JSON.parse(data) as { question?: string };
        if (o.question) setWebOffer({ question: o.question });
      } catch {
        /* ignore */
      }
    } else if (event === "web_unavailable") {
      // Web/deep toggle was on but web search is disabled for this workspace →
      // nothing searched. The bubble drops its searching/researching status; we
      // show a calm note (the answer still comes from documents).
      setWebUnavailable(true);
      patchLast((m) => ({
        ...m,
        webSearching: false,
        deepSearching: false,
        deepQueries: undefined,
        searchStatus: undefined,
      }));
    } else if (event === "done") {
      try {
        const d = JSON.parse(data) as { message_id?: string };
        patchLast((m) => ({ ...m, id: d.message_id ?? m.id, searchStatus: undefined }));
      } catch {
        /* ignore */
      }
    } else {
      try {
        const d = JSON.parse(data) as { delta?: string };
        // First token arriving ends the searching/researching phase. For deep
        // mode we keep `deepQueries` (they become the visible recap), only the
        // active `deepSearching` flag flips off. It also marks reasoning done,
        // auto-collapsing the thinking panel into its compact disclosure.
        if (d.delta) {
          startFreshAttemptIfPending();
          enqueueStreamDelta("answer", d.delta);
        }
      } catch {
        /* ignore */
      }
    }
  }

  async function onPickFiles(files: FileList | null) {
    if (!files) return;
    const picked: Attachment[] = [];
    for (const file of Array.from(files).slice(0, 4)) {
      if (!file.type.startsWith("image/") || file.size > 5 * 1024 * 1024) continue;
      const dataUrl = await new Promise<string>((resolve) => {
        const fr = new FileReader();
        fr.onload = () => resolve(String(fr.result ?? ""));
        fr.readAsDataURL(file);
      });
      if (dataUrl) picked.push({ dataUrl, mime: file.type, name: file.name });
    }
    if (picked.length) setAttachments((a) => [...a, ...picked].slice(0, 4));
    if (fileRef.current) fileRef.current.value = "";
  }

  async function send(question: string, opts?: { regenerate?: boolean; webSearch?: boolean }) {
    if (streaming || !wsId) return;
    setWebOffer(null); // a new turn supersedes any pending offer
    setWebUnavailable(false); // clear any prior "web disabled" note
    const sending = opts?.regenerate ? [] : attachments;
    // Deep research for this turn: the composer's deep toggle. A confirmed web
    // offer click (opts.webSearch) is a plain web turn, never deep.
    const useDeep = !opts?.webSearch && deepMode;
    // Web mode for this turn: a confirmed offer click or the composer toggle.
    // Deep mode is itself a (richer) web turn, so it implies web retrieval.
    const useWeb = !!opts?.webSearch || webMode || useDeep;
    // The fresh, empty assistant bubble — flagged as web-searching/deep-searching
    // when relevant so the UI can show "Web'de aranıyor…" / "Derin araştırma
    // yapılıyor…" before tokens/sources/queries arrive.
    const seed: Msg = {
      role: "assistant",
      content: "",
      webSearching: useWeb && !useDeep,
      deepSearching: useDeep,
      searchStatus: useDeep ? "planning" : useWeb ? "searching" : undefined,
    };

    let q: string;
    let history: { role: string; content: string }[];
    if (opts?.regenerate) {
      // Re-run the last user turn: drop the previous answer, keep prior turns.
      const lastUserIdx = messages.map((m) => m.role).lastIndexOf("user");
      if (lastUserIdx < 0) return;
      q = messages[lastUserIdx].content;
      history = messages.slice(0, lastUserIdx).map((m) => ({ role: m.role, content: m.content }));
      setMessages([...messages.slice(0, lastUserIdx + 1), seed]);
    } else {
      q = question.trim();
      if (!q && sending.length === 0) return;
      history = messages.map((m) => ({ role: m.role, content: m.content }));
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: q }, seed]);
      setAttachments([]);
    }
    setAtBottom(true);
    setStreaming(true);
    setLiveTurn(true);
    const ac = new AbortController();
    abortRef.current = ac;
    reconnectRef.current = null;
    replaceAnswerRef.current = false;
    // Built once: a pre-stream drain retry re-sends this identical turn; a
    // mid-stream drain resumes it instead. Fresh idempotency key per request.
    const payload = JSON.stringify({
      // "Genel": search across all workspaces (send the list + a primary id).
      workspace_id: allMode ? (workspaces[0]?.id ?? "") : wsId,
      workspace_ids: allMode ? workspaces.map((w) => w.id) : undefined,
      message: q,
      conversation_id: conversationId.current ?? undefined,
      // Once a conversation exists the edge replays authoritative history from
      // the DB; only send client history to seed the very first turn.
      history: conversationId.current ? [] : history,
      // Confirmed offer or the manual composer toggle both request a web answer.
      web_search: useWeb,
      // Deep research: decompose into sub-queries + sourced synthesis. Only
      // sent when on (the edge treats absence as off).
      deep_search: useDeep ? true : undefined,
      // Tools (MCP): when the "Araçlar" toggle is on, let the agent call the
      // org's connected MCP tools this turn. Only sent when on (absence = off).
      mcp_tools: toolsMode || undefined,
      // User preferences remain hints. Skill execution policy is never copied
      // into the request; edge resolves the current immutable snapshot.
      model: hasModel && model ? model : undefined,
      answer_style: answerStyle ?? undefined,
      skill_id: activeSkill?.id,
      skill_version: activeSkill?.version,
      // How hard the model should reason before answering (server default: medium).
      reasoning_effort: effort,
      attachments: sending.map((a) => ({ type: "image", data_url: a.dataUrl, mime: a.mime })),
      // Active UI locale: selects server-authored text and the prompt template.
      locale,
    });
    try {
      // Edge replica drains are handled transparently, each at most once:
      //  - pre-stream 503 "draining": nothing was stored, so the identical turn
      //    is re-sent after Retry-After;
      //  - mid-stream `reconnect`: the partial answer is stored, so the turn is
      //    RESUMED by its assistant message id (no `message`, so no duplicate
      //    user turn); the resumed stream's tokens replace the partial.
      // Stop (abort) cancels a pending retry too.
      let body = payload;
      let drainRetried = false;
      let resumed = false;
      for (;;) {
        reconnectRef.current = null;
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": newIdempotencyKey(),
          },
          signal: ac.signal,
          body,
        });
        if (!res.ok || !res.body) {
          // PRE-STREAM failure: the edge (or the /api/chat proxy) returns
          // {error, code, message} as JSON.
          let errBody: unknown = null;
          try {
            errBody = await res.json();
          } catch {
            /* non-JSON body — the generic friendly fallback applies */
          }
          if (resumed) {
            // 400 (not resumable / already resumed) or 404 (unknown/foreign):
            // stop; the partial answer stays with the draining note.
            patchLast((m) => ({ ...m, reconnecting: false, error: t("chat.edgeErrors.draining") }));
            return;
          }
          const { code } = parseEdgeError(errBody);
          const retryAfter = res.headers.get("retry-after");
          const delay = preStreamRetryDelayMs(res.status, code, retryAfter, drainRetried ? 1 : 0);
          if (delay !== null) {
            drainRetried = true;
            patchLast((m) => ({ ...m, reconnecting: true }));
            await abortableSleep(delay, ac.signal);
            continue;
          }
          // Rate limited / draining: tell the user when to try again.
          const secs = code === "rate_limited" || code === "draining" ? retryAfterSeconds(retryAfter) : null;
          const message = edgeErrorText(errBody);
          patchLast((m) => ({
            ...m,
            error: secs ? `${message} ${t("chat.retryAfterHint", { seconds: secs })}` : message,
            reconnecting: false,
            webSearching: false,
            deepSearching: false,
            searchStatus: undefined,
          }));
          return;
        }
        // Resume accepted: the partial answer stays until the first fresh token.
        if (resumed) replaceAnswerRef.current = true;
        patchLast((m) => (m.reconnecting ? { ...m, reconnecting: false } : m));
        await readSseFrames(res.body, handleFrame);
        await waitForStreamDrain();
        // (Cast: TS narrows the ref to null after the reset above, but the SSE
        // handler may have set it while the stream was read.)
        const reconnect = reconnectRef.current as Reconnect | null;
        if (!reconnect) break;
        const resume = resumed
          ? null
          : buildResumeRequest(reconnect, {
              workspaceId: allMode ? (workspaces[0]?.id ?? "") : wsId,
              conversationId: conversationId.current,
              locale,
            });
        if (!resume) {
          // Drained again after a resume, or the turn cannot be identified:
          // stop here; the partial answer stays.
          patchLast((m) => ({ ...m, reconnecting: false, error: t("chat.edgeErrors.draining") }));
          break;
        }
        await abortableSleep(reconnect.delayMs, ac.signal);
        body = JSON.stringify(resume);
        resumed = true;
      }
    } catch (err) {
      // Preserve any partial reasoning/answer immediately when the request fails
      // or the user stops it; pacing is useful only for a normal completion.
      flushStreamDeltas();
      // User cancel (Stop) is silent. Any other failure becomes a calm error
      // note on the assistant bubble with a retry affordance.
      if ((err as Error)?.name !== "AbortError") {
        patchLast((m) => ({
          ...m,
          error: t("chat.errorGeneric"),
          webSearching: false,
          deepSearching: false,
          searchStatus: undefined,
        }));
      }
    } finally {
      await waitForStreamDrain();
      // A Stop during a pending retry must not leave "reconnecting…" behind.
      patchLast((m) => (m.reconnecting ? { ...m, reconnecting: false } : m));
      setStreaming(false);
      abortRef.current = null;
      void loadConversations(); // surface the new conversation in history
    }
  }

  async function sendFeedback(index: number, rating: "up" | "down") {
    const m = messages[index];
    if (!m?.id || m.feedback === rating) return;
    setMessages((prev) => {
      const copy = [...prev];
      if (copy[index]) copy[index] = { ...copy[index], feedback: rating };
      return copy;
    });
    try {
      await fetch(`/api/messages/${m.id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
      });
    } catch {
      /* best-effort; the optimistic state stays */
    }
  }

  function onSuggestion(prompt: string) {
    if (prompt.endsWith(" ")) {
      setInput(prompt);
      inputRef.current?.focus();
    } else {
      void send(prompt);
    }
  }

  // Retry after a failure: re-run the last user turn (drops the errored answer).
  function retry() {
    if (streaming) return;
    void send("", { regenerate: true });
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // While the "/command" picker is open, let it claim Up/Down/Enter/Escape so
    // the keyboard drives the popover (and Enter never sends the raw "/query").
    if (skillPickerOpen && skillKeyHandler.current) {
      if (["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(e.key) && !e.nativeEvent.isComposing) {
        if (skillKeyHandler.current(e)) {
          e.preventDefault();
          return;
        }
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(input);
    }
  }

  // Account-block menu items, anchored at the sidebar bottom (relocated from the
  // old top-right avatar dropdown). "Ayarlar" opens the settings dialog over the
  // chat (ChatGPT/Claude-style, landing on Profile); the two destructive actions
  // (clear history, sign out) are grouped at the end and danger-tinted. Sign out
  // reuses the existing server action.
  const accountItems = [
    {
      key: "settings",
      label: t("chat.settings"),
      icon: "settings",
      onSelect: () => openSettings("profile"),
    },
    {
      key: "clear",
      label: t("chat.clearHistory"),
      icon: "delete_sweep",
      danger: true,
      onSelect: () => {
        setClearError(false);
        setClearOpen(true);
      },
    },
    {
      key: "signout",
      label: t("common.signOut"),
      icon: "logout",
      danger: true,
      onSelect: () => startSignOut(() => void signOutAction()),
    },
  ];

  const navItem =
    "flex items-center w-full px-4 py-3 gap-3 rounded-2xl text-ink-muted transition-colors hover:bg-surface-3/60 hover:text-ink";

  return (
    <div className="relative flex h-screen w-full overflow-hidden bg-bg text-ink">
      {/* ─────────────── Sidebar ─────────────── */}
      <aside
        className={`fixed z-50 flex h-full w-[280px] flex-col gap-1 overflow-hidden border-r border-border bg-surface p-3 transition-transform duration-300 md:relative md:translate-x-0 md:transition-none ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "md:w-0 md:border-0 md:p-0 md:opacity-0" : ""}`}
      >
        {/* Brand + desktop collapse toggle */}
        <div className="mb-2 flex items-center gap-3 px-2 py-4">
          <BrandLogo size={40} />
          <div className="min-w-0 flex-1 leading-tight">
            <h1 className="font-display text-[20px] font-bold tracking-tight">
              <BrandName />
            </h1>
            <p className="text-xs text-ink-muted">AI Assistant</p>
          </div>
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={t("chat.collapseSidebar")}
            title={t("chat.collapseSidebar")}
            className="hidden h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-2 hover:text-ink md:grid"
          >
            <Icon name="left_panel_close" className="text-lg" />
          </button>
        </div>

        {/* Fixed top: new chat + search + skills — these stay put (do NOT scroll). */}
        <div className="shrink-0 space-y-1">
          <button
            type="button"
            onClick={newChat}
            disabled={streaming}
            className="flex w-full items-center gap-3 rounded-2xl bg-brand px-4 py-3 font-semibold text-brand-contrast transition-colors hover:bg-brand-strong disabled:opacity-50"
          >
            <Icon name="add" />
            <span className="text-sm">{t("chat.newChat")}</span>
          </button>

          {/* "Sohbetlerde ara": filters the loaded recents by title, client-side. */}
          <div className="relative px-1 pt-1">
            <Icon
              name="search"
              className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-base text-ink-muted"
            />
            <input
              type="search"
              value={convQuery}
              onChange={(e) => setConvQuery(e.target.value)}
              placeholder={t("chat.search")}
              aria-label={t("chat.search")}
              className="w-full rounded-2xl bg-surface-2/60 py-2.5 pl-10 pr-3 text-sm text-ink outline-none transition placeholder:text-ink-muted/60 hover:bg-surface-2 focus:bg-surface-2"
            />
          </div>

          {/* Skills (ChatGPT-style): a top-of-sidebar entry opening a menu of the
              skill union (org-published + the caller's own personal). Always shown
              — anyone can create a personal skill; admins also reach the org
              builder via "Yönet". */}
          <SidebarSkillsMenu
            skills={skills}
            isAdmin={isAdmin}
            models={models}
            activeSkillId={activeSkill?.id ?? null}
            onPick={pickSkill}
          />

          {/* Araçlar (Tools/MCP): a calm sidebar entry under Skills listing the
              org's connected MCP integrations, with a per-turn "Use tools"
              toggle that drives toolsMode (sent as `mcp_tools`). */}
          <SidebarToolsMenu
            tools={tools}
            toolsMode={toolsMode}
            onToggle={() => setToolsMode((v) => !v)}
          />

          {/* Scheduled tasks (cron jobs): a calm sidebar entry under Skills that
              opens the tasks modal (list + conversational/manual create). */}
          <button
            type="button"
            onClick={() => setTasksOpen(true)}
            className="flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-ink-muted transition-colors hover:bg-surface-3/60 hover:text-ink"
          >
            <Icon name="schedule" />
            <span className="min-w-0 flex-1 truncate text-left text-sm">{t("chat.scheduledTasks")}</span>
          </button>
        </div>

        {/* Scrollable region: ONLY the recent-chats list scrolls. */}
        <nav
          ref={recentsRef}
          onScroll={onRecentsScroll}
          aria-label={t("chat.recent")}
          className="scrollbar-slim flex-1 min-h-0 space-y-1 overflow-y-auto"
        >
          <div className="px-3 pb-1 pt-5">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              {t("chat.recent")}
            </span>
          </div>
          {filteredConversations.length === 0 ? (
            <p className="px-4 py-2 text-sm text-ink-muted">
              {convFilter ? t("chat.searchEmpty") : t("chat.noRecent")}
            </p>
          ) : (
            <div className="space-y-0.5">
              {filteredConversations.map((c) => {
                const confirming = confirmDeleteId === c.id;
                const isDeleting = deletingId === c.id;
                const isActive = activeConv === c.id;
                return (
                  <div
                    key={c.id}
                    className={`group relative flex items-center rounded-2xl transition-colors ${
                      isActive ? "bg-surface-2" : "hover:bg-surface-2/60"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void openConversation(c.id)}
                      title={c.title || t("chat.untitled")}
                      className={`flex min-w-0 flex-1 items-center gap-3 rounded-2xl py-2.5 pl-4 pr-2 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-brand/30 ${
                        isActive ? "font-medium text-ink" : "text-ink-muted group-hover:text-ink"
                      }`}
                    >
                      <span className="truncate">{c.title || t("chat.untitled")}</span>
                    </button>
                    {/* Delete affordance: hidden until hover/focus; swaps to an
                        inline confirm/cancel pair on first click (no jarring
                        browser confirm()). Sits at the row's end. */}
                    <div
                      className={`flex shrink-0 items-center gap-0.5 pr-1.5 transition-opacity ${
                        confirming || deleteErrorId === c.id
                          ? "opacity-100"
                          : "opacity-0 focus-within:opacity-100 group-hover:opacity-100"
                      }`}
                    >
                      {confirming ? (
                        <>
                          <button
                            type="button"
                            onClick={() => void deleteConversation(c.id)}
                            disabled={isDeleting}
                            aria-label={t("chat.deleteChatConfirm")}
                            title={t("chat.deleteChatConfirm")}
                            className="grid h-6 w-6 place-items-center rounded-lg text-danger transition hover:bg-danger/10 disabled:opacity-50"
                          >
                            <Icon name={isDeleting ? "progress_activity" : "check"} className={`text-sm ${isDeleting ? "animate-spin" : ""}`} />
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setConfirmDeleteId(null);
                              setDeleteErrorId(null);
                            }}
                            disabled={isDeleting}
                            aria-label={t("chat.deleteChatCancel")}
                            title={t("chat.deleteChatCancel")}
                            className="grid h-6 w-6 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-3 hover:text-ink disabled:opacity-50"
                          >
                            <Icon name="close" className="text-sm" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setConfirmDeleteId(c.id);
                            setDeleteErrorId(null);
                          }}
                          aria-label={t("chat.deleteChat")}
                          title={deleteErrorId === c.id ? t("chat.deleteChatError") : t("chat.deleteChat")}
                          className={`grid h-6 w-6 place-items-center rounded-lg transition hover:bg-surface-3 ${
                            deleteErrorId === c.id ? "text-danger" : "text-ink-muted hover:text-ink"
                          }`}
                        >
                          <Icon name={deleteErrorId === c.id ? "error" : "delete"} className="text-[13px]" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
              {/* Infinite scroll: a quiet loading row while the next page loads.
                  Auto-triggered by onRecentsScroll; stops once canLoadMore is
                  false (the last page came back short). */}
              {canLoadMore && loadingMore && (
                <div
                  role="status"
                  className="flex items-center justify-center gap-2 px-4 py-3 text-xs font-medium text-ink-muted"
                >
                  <Icon name="progress_activity" className="animate-spin text-sm" />
                  {t("chat.loadingMore")}
                </div>
              )}
            </div>
          )}
        </nav>

        {/* Sidebar bottom: a single admin door (one entry to /admin, admins only)
            and the account block (relocated from the old top-right avatar menu).
            Both stay pinned below the scrolling recents. */}
        <div className="mt-1 shrink-0 space-y-1 border-t border-border pt-2">
          {isAdmin && (
            <a href="/admin" className={navItem}>
              <Icon name="admin_panel_settings" />
              <span className="text-sm">{t("chat.adminConsole")}</span>
            </a>
          )}
          <AccountMenu
            name={userName}
            email={userEmail}
            ariaLabel={t("chat.accountMenu")}
            items={accountItems}
          />
        </div>
      </aside>

      {navOpen && (
        <div
          className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-sm md:hidden"
          onClick={() => setNavOpen(false)}
          aria-hidden
        />
      )}

      {/* ─────────────── Main stage ─────────────── */}
      <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-bg">
        {/* Top bar */}
        <header className="z-10 flex w-full items-center justify-between gap-3 border-b border-border bg-surface/80 px-6 py-4 backdrop-blur">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            className="grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface-2 md:hidden"
            aria-label={t("chat.title")}
          >
            <Icon name="menu" />
          </button>
          {/* Desktop: reopen the collapsed sidebar */}
          {collapsed && (
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label={t("chat.expandSidebar")}
              title={t("chat.expandSidebar")}
              className="hidden h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface-2 md:grid"
            >
              <Icon name="left_panel_open" />
            </button>
          )}

          {/* The top bar now holds ONLY the workspace selector (or a tidy static
              name when there's just one) — minimal and calm. The model picker
              moved into the composer; the account menu moved to the sidebar
              bottom. */}
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {workspaces.length > 1 ? (
              <Select
                size="sm"
                value={wsId}
                onValueChange={setWsId}
                ariaLabel={t("chat.workspace")}
                options={[
                  { value: ALL_WORKSPACES, label: t("chat.allWorkspaces"), icon: "hub" },
                  ...workspaces.map((w) => ({ value: w.id, label: w.name, icon: "workspaces" })),
                ]}
              />
            ) : (
              activeWs && (
                <span className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border bg-surface px-3 text-sm text-ink-muted">
                  <Icon name="workspaces" className="text-base text-ink-muted" />
                  <span className="truncate">{activeWs.name}</span>
                </span>
              )
            )}
          </div>

          {/* Right side: the notifications inbox bell (unread badge → calm panel
              of scheduled-task results). */}
          <NotificationsInbox items={notifications.items} unread={notifications.unread} />
        </header>

        <p role="status" aria-live="polite" className="sr-only">
          {liveStatus}
        </p>
        {/* Conversation / welcome */}
        <div ref={scrollRef} onScroll={onScroll} className="scrollbar-slim flex-1 overflow-y-auto">
          {empty ? (
            <div className="mx-auto flex min-h-full max-w-2xl flex-col items-center justify-center px-4 py-16 text-center">
              <span className="mb-6 grid h-14 w-14 place-items-center rounded-2xl bg-brand/10 text-brand">
                <Icon name="auto_awesome" className="text-3xl" />
              </span>
              <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
                {t("chat.greeting").replace("👋", "").trim()}
              </h2>
              <p className="mt-3 max-w-md text-ink-muted">
                {noWorkspaces ? t("chat.noWorkspaces") : t("chat.greetingSub")}
              </p>
              {!noWorkspaces && (activeWs || allMode) && (
                <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1 text-xs text-ink-muted">
                  <Icon name={allMode ? "hub" : "workspaces"} className="text-sm text-brand" />
                  {t("chat.askingOver", {
                    workspace: allMode ? t("chat.allWorkspaces") : (activeWs?.name ?? ""),
                  })}
                </p>
              )}

              {!noWorkspaces && (
                <div className="mt-10 grid w-full grid-cols-1 gap-2.5 sm:grid-cols-3">
                  {suggestions.map((s) => (
                    <button
                      key={s.title}
                      type="button"
                      onClick={() => onSuggestion(s.prompt)}
                      className="card flex flex-col rounded-2xl px-4 py-4 text-left transition hover:-translate-y-0.5 hover:shadow-lift"
                    >
                      <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand/10 text-brand">
                        <Icon name={s.icon} className="text-lg" />
                      </span>
                      <span className="mt-3 block text-sm font-semibold text-ink">{s.title}</span>
                      <span className="mt-0.5 block text-xs leading-snug text-ink-muted">{s.desc}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-8 px-4 py-8 sm:px-6">
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <div key={i} className="flex animate-fade-up justify-end">
                    <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-3xl rounded-tr-md bg-surface-2 px-4 py-3 text-[15px] leading-relaxed text-ink">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <AssistantMessage
                    key={i}
                    message={m}
                    index={i}
                    lastAssistantIdx={lastAssistantIdx}
                    streaming={streaming}
                    retry={retry}
                    onFeedback={(rating) => void sendFeedback(i, rating)}
                    onRegenerate={() => void send("", { regenerate: true })}
                  />
                ),
              )}
            </div>
          )}
        </div>

        {/* Composer — auto-growing textarea + brand send / dark stop */}
        <div className="relative border-t border-border bg-surface px-4 pb-4 pt-3 sm:px-6">
          {webOffer && !streaming && (
            <div className="mx-auto mb-3 flex max-w-3xl items-start justify-between gap-3 rounded-2xl border border-brand/30 bg-brand/5 px-4 py-3 text-sm">
              <span className="flex min-w-0 items-start gap-2 text-ink-muted">
                <Icon name="travel_explore" className="mt-0.5 shrink-0 text-base text-brand" />
                <span>{t("chat.webOfferHint")}</span>
              </span>
              <button
                type="button"
                onClick={() => {
                  // Flip Web mode on (single web entry point) and re-send the last
                  // question as a web turn, rather than a separate offer flow.
                  setDeepMode(false);
                  setWebMode(true);
                  void send(webOffer.question, { webSearch: true });
                }}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-brand px-3 py-1.5 text-xs font-semibold text-brand-contrast transition hover:bg-brand-strong"
              >
                <Icon name="travel_explore" className="text-sm" /> {t("chat.searchWeb")}
              </button>
            </div>
          )}
          {/* Web toggle was on but disabled for this workspace: a calm, neutral
              note (not a call to action) — the answer still came from documents. */}
          {webUnavailable && (
            <div
              role="status"
              className="mx-auto mb-3 flex max-w-3xl items-start justify-between gap-3 rounded-2xl border border-border bg-surface-2 px-4 py-2.5 text-xs leading-relaxed text-ink-muted"
            >
              <span className="flex min-w-0 items-start gap-2">
                <Icon name="language" className="mt-0.5 shrink-0 text-sm text-ink-muted" />
                <span>{t("chat.webUnavailable")}</span>
              </span>
              <button
                type="button"
                onClick={() => setWebUnavailable(false)}
                aria-label={t("common.cancel")}
                className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-ink-muted transition hover:bg-surface-3 hover:text-ink"
              >
                <Icon name="close" className="text-sm" />
              </button>
            </div>
          )}
          {!atBottom && !empty && (
            <button
              type="button"
              onClick={jumpToLatest}
              aria-label={t("chat.jumpToLatest")}
              className="absolute -top-12 left-1/2 grid h-9 w-9 -translate-x-1/2 place-items-center rounded-full border border-border bg-surface text-ink shadow-lift transition hover:bg-surface-2"
            >
              <Icon name="arrow_downward" />
            </button>
          )}
          {/* "/command" skill picker, floating just above the composer. */}
          {skillPickerOpen && (
            <SkillPicker
              skills={skills}
              query={skillQuery}
              onPick={pickSkill}
              onDismiss={() => setInput("")}
              registerKeydown={(h) => {
                skillKeyHandler.current = h;
              }}
            />
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send(input);
            }}
            className="mx-auto w-full max-w-3xl"
          >
            {attachments.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-2">
                {attachments.map((a, i) => (
                  <div key={i} className="relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={a.dataUrl}
                      alt={a.name}
                      className="h-16 w-16 rounded-xl border border-border object-cover"
                    />
                    <button
                      type="button"
                      onClick={() => setAttachments((arr) => arr.filter((_, j) => j !== i))}
                      aria-label={t("chat.removeImage")}
                      className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-ink text-bg"
                    >
                      <Icon name="close" className="text-xs" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {/* Active-tool chips (ChatGPT-style): one-click removable, shown only
                when a tool is on. The hidden file input lives here so the "+"
                menu's "attach" can trigger it. */}
            {visionEnabled && (
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(e) => void onPickFiles(e.target.files)}
              />
            )}
            {(activeSkill || webMode || deepMode || toolsMode) && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {/* Active skill/mode chips — quiet status pills. Fixed height +
                    flex centering so the label and the remove "×" share one
                    vertical center, and the button stays inside the pill. */}
                {activeSkill && (
                  <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-surface-2 pl-2.5 pr-1 text-[11px] font-medium text-ink-muted">
                    <Icon name={activeSkill.icon?.trim() || "bolt"} className="text-[15px] leading-none" />
                    <span className="leading-none">{activeSkill.name}</span>
                    <button
                      type="button"
                      onClick={() => setActiveSkillId(null)}
                      aria-label={t("chat.skillRemove", { name: activeSkill.name })}
                      className="inline-flex h-4 w-4 items-center justify-center rounded-full text-ink-muted/45 transition hover:text-ink"
                    >
                      <Icon name="close" className="text-[11px] leading-none" />
                    </button>
                  </span>
                )}
                {webMode && (
                  <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-surface-2 pl-2.5 pr-1 text-[11px] font-medium text-ink-muted">
                    <Icon name="language" className="text-[15px] leading-none" />
                    <span className="leading-none">{t("chat.webMode")}</span>
                    <button
                      type="button"
                      onClick={() => setWebMode(false)}
                      aria-label={t("chat.activeToolRemove", { tool: t("chat.webMode") })}
                      className="inline-flex h-4 w-4 items-center justify-center rounded-full text-ink-muted/45 transition hover:text-ink"
                    >
                      <Icon name="close" className="text-[11px] leading-none" />
                    </button>
                  </span>
                )}
                {deepMode && (
                  <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-surface-2 pl-2.5 pr-1 text-[11px] font-medium text-ink-muted">
                    <Icon name="travel_explore" className="text-[15px] leading-none" />
                    <span className="leading-none">{t("chat.deepMode")}</span>
                    <button
                      type="button"
                      onClick={() => setDeepMode(false)}
                      aria-label={t("chat.activeToolRemove", { tool: t("chat.deepMode") })}
                      className="inline-flex h-4 w-4 items-center justify-center rounded-full text-ink-muted/45 transition hover:text-ink"
                    >
                      <Icon name="close" className="text-[11px] leading-none" />
                    </button>
                  </span>
                )}
                {toolsMode && (
                  <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-surface-2 pl-2.5 pr-1 text-[11px] font-medium text-ink-muted">
                    <Icon name="construction" className="text-[15px] leading-none" />
                    <span className="leading-none">{t("chat.toolsMode")}</span>
                    <button
                      type="button"
                      onClick={() => setToolsMode(false)}
                      aria-label={t("chat.activeToolRemove", { tool: t("chat.toolsMode") })}
                      className="inline-flex h-4 w-4 items-center justify-center rounded-full text-ink-muted/45 transition hover:text-ink"
                    >
                      <Icon name="close" className="text-[11px] leading-none" />
                    </button>
                  </span>
                )}
              </div>
            )}
            <div className="flex items-end gap-1.5 rounded-3xl border border-border/70 bg-surface p-1.5 shadow-[0_1px_2px_rgb(11_11_13_/_0.03)] transition focus-within:border-border">
              {/* The single "+" entry point: attach + tools + reasoning effort. */}
              <ComposerToolsMenu
                visionEnabled={visionEnabled}
                onAttach={() => fileRef.current?.click()}
                webMode={webMode}
                deepMode={deepMode}
                onToggleWeb={toggleWeb}
                onToggleDeep={toggleDeep}
                effort={effort}
                onChangeEffort={changeEffort}
              />
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={t("chat.placeholder")}
                disabled={noWorkspaces}
                className="max-h-[200px] min-h-[36px] flex-1 resize-none self-end bg-transparent px-1 py-2 text-[15px] leading-relaxed text-ink outline-none placeholder:text-ink-muted/60"
              />
              {/* Model picker (per the PO): compact, on the right of the input row,
                  just left of the send button. Only when there's a real choice
                  (>1 allowed model) — a single fixed model needs no picker. */}
              {showModelPicker && (
                <ComposerModelPicker
                  models={allowedModels}
                  value={model}
                  onChange={setModel}
                  label={t("chat.model")}
                  aliases={models.aliases}
                />
              )}
              {streaming ? (
                <button
                  type="button"
                  onClick={() => abortRef.current?.abort()}
                  aria-label={t("chat.stop")}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-bg transition hover:opacity-90 active:scale-95"
                >
                  <Icon name="stop" className="text-lg" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={noWorkspaces || (!input.trim() && attachments.length === 0)}
                  aria-label={t("chat.send")}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand text-brand-contrast shadow-soft transition hover:bg-brand-strong active:scale-95 disabled:opacity-30"
                >
                  <Icon name="arrow_upward" className="text-lg" />
                </button>
              )}
            </div>
            <p className="mt-2 text-center text-[11px] text-ink-muted">{t("chat.disclaimer")}</p>
          </form>
        </div>
      </main>

      {/* Clear-all-history confirm: a calm dialog (not a browser confirm). */}
      <Modal
        open={clearOpen}
        onClose={() => {
          if (!clearing) setClearOpen(false);
        }}
        size="sm"
        title={t("chat.clearHistoryTitle")}
        footer={
          <>
            <button
              type="button"
              onClick={() => setClearOpen(false)}
              disabled={clearing}
              className="inline-flex items-center justify-center gap-2 rounded-full border border-border bg-surface-2 px-5 py-2.5 text-sm font-medium text-ink transition-colors hover:bg-surface-3 active:scale-[0.98] disabled:opacity-40"
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              onClick={() => void clearHistory()}
              disabled={clearing}
              className="inline-flex items-center justify-center gap-2 rounded-full bg-danger px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-danger/90 active:scale-[0.98] disabled:opacity-40"
            >
              {clearing ? (
                <Icon name="progress_activity" className="animate-spin text-base" />
              ) : (
                <Icon name="delete_sweep" className="text-base" />
              )}
              {t("chat.clearHistoryCta")}
            </button>
          </>
        }
      >
        <div className="flex gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-danger/10 text-danger">
            <Icon name="delete_sweep" className="text-xl" />
          </span>
          <p className="pt-1 text-sm leading-relaxed text-ink-muted">{t("chat.clearHistoryConfirm")}</p>
        </div>
        {clearError && (
          <p className="mt-3 rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("chat.clearHistoryError")}
          </p>
        )}
      </Modal>

      {/* Account/settings dialog over the chat. After a successful mutation it
          calls router.refresh() → the chat page refetches profile/memory →
          fresh data flows back in through these props. */}
      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initialTab={settingsTab}
        profile={profile}
        email={userEmail}
        memory={memory}
        models={models}
      />

      {/* Scheduled tasks (cron jobs): list + conversational/manual create. After
          a create/edit/delete it calls router.refresh() → the chat page refetches
          tasks → fresh data flows back in through the `tasks` prop. */}
      <ScheduledTasksModal
        open={tasksOpen}
        onClose={() => setTasksOpen(false)}
        tasks={tasks}
        workspaces={workspaces}
        models={models}
        timezone={timezone}
      />
    </div>
  );
}
