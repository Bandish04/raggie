// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";

import { AnswerBody } from "@/components/chat/answer-markdown";
import type { Msg } from "@/components/chat/chat-model";
import { Icon } from "@/components/chat/chat-ui";
import { MessageActions } from "@/components/chat/message-actions";
import { MessageSources } from "@/components/chat/message-sources";
import { DeepResearchPanel, SearchProgressLine } from "@/components/chat/search-progress";
import { ThinkingPanel } from "@/components/chat/thinking-panel";
import { ToolStepsPanel } from "@/components/chat/tool-steps";

/* One assistant turn in the transcript: reasoning, deep-research recap, tool
   steps, the answer (or the live search/thinking status), sources, the error
   note with retry, and the answer actions. `index`/`lastAssistantIdx` decide
   which turn is live and which one offers retry/regenerate. */
export function AssistantMessage({
  message: m,
  index: i,
  lastAssistantIdx,
  streaming,
  retry,
  onFeedback,
  onRegenerate,
}: {
  message: Msg;
  index: number;
  lastAssistantIdx: number;
  streaming: boolean;
  retry: () => void;
  onFeedback: (rating: "up" | "down") => void;
  onRegenerate: () => void;
}) {
  const t = useTranslations();
  return (
    <div className="flex animate-fade-up gap-3 sm:gap-4">
      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand">
        <Icon name="auto_awesome" className="text-base" />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        {/* Reasoning (chain-of-thought): expanded & streaming while
            the model thinks, then auto-collapses into a compact
            disclosure once the answer begins. Always above the
            answer; renders nothing without reasoning text. */}
        {m.thinking?.trim() && (
          <ThinkingPanel thinking={m.thinking} done={!!m.thinkingDone || !!m.content} />
        )}
        {/* Deep-research recap: once the synthesis is streaming/done,
            the researched sub-queries stay visible (collapsed) above
            the answer. */}
        {m.content && m.deepQueries && m.deepQueries.length > 0 && (
          <DeepResearchPanel queries={m.deepQueries} active={false} />
        )}
        {/* Agentic tool steps (MCP): expanded while any tool runs,
            collapsing to a quiet "Kullanılan araçlar" recap once the
            answer streams. Renders nothing without steps. */}
        {m.toolSteps && m.toolSteps.length > 0 && (
          <ToolStepsPanel steps={m.toolSteps} />
        )}
        {m.content ? (
          <AnswerBody message={m} streaming={streaming && i === lastAssistantIdx} />
        ) : m.deepSearching || (m.searchStatus && m.deepQueries && m.deepQueries.length > 0) ? (
          // Deep-research activity (Gemini-style): a calm panel with an
          // animated header and the sub-queries being researched.
          <DeepResearchPanel queries={m.deepQueries ?? []} active status={m.searchStatus} />
        ) : m.webSearching || m.searchStatus ? (
          // Web-search activity (Gemini-style): a clear "searching the
          // web" status before sources/tokens arrive.
          <SearchProgressLine status={m.searchStatus} fallbackKey="searchingWeb" />
        ) : m.error ? null : m.thinking?.trim() ? // The live reasoning panel above already shows an animated
        // "thinking" affordance — don't stack the generic dots on it.
        null : streaming && i === lastAssistantIdx ? (
          // Thinking dots only while this turn is actively streaming —
          // never leave an empty bubble spinning after the stream ends.
          <div className="flex items-center gap-2 py-1.5 text-sm text-ink-muted">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-muted [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-muted [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-muted" />
            </span>
            <span>{t("chat.thinking")}</span>
          </div>
        ) : null}
        {m.reconnecting && (
          // Edge replica draining: the partial answer above stays
          // while the turn is retried once.
          <div role="status" className="mt-2 flex items-center gap-2 text-sm text-ink-muted">
            <Icon name="sync" className="animate-spin text-base" />
            <span>{t("chat.reconnecting")}</span>
          </div>
        )}
        {m.sources && m.sources.length > 0 && (
          <MessageSources sources={m.sources} messageId={m.id ?? `i${i}`} />
        )}
        {/* Calm, distinct error state with a retry affordance (never
            a raw "(error)"). Applies to the last assistant turn. */}
        {m.error && (
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm">
            <span className="inline-flex items-center gap-2 text-ink">
              <Icon name="error" className="text-base text-danger" />
              {m.error}
            </span>
            {i === lastAssistantIdx && !streaming && (
              <button
                type="button"
                onClick={retry}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-surface px-3 py-1.5 text-xs font-semibold text-ink shadow-soft transition hover:bg-surface-2"
              >
                <Icon name="refresh" className="text-sm" /> {t("chat.errorRetry")}
              </button>
            )}
          </div>
        )}
        {m.content && !m.error && !(streaming && i === lastAssistantIdx) && (
          <MessageActions
            content={m.content}
            messageId={m.id}
            feedback={m.feedback}
            onFeedback={onFeedback}
            showRegenerate={i === lastAssistantIdx && !streaming}
            onRegenerate={onRegenerate}
          />
        )}
      </div>
    </div>
  );
}
