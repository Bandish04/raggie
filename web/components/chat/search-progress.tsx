// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Icon } from "@/components/chat/chat-ui";
/* A single researched sub-query row: a search icon + the query text. Shared by
   the active panel and the collapsed recap so they read identically. Borderless
   and fill-free — a quiet text row, not a chip. */
export function DeepQueryRow({ query }: { query: string }) {
  return (
    <div className="flex items-start gap-2 py-0.5 text-xs leading-snug text-ink-muted">
      <Icon name="search" className="mt-px shrink-0 text-sm text-ink-muted/70" />
      <span className="min-w-0 break-words">{query}</span>
    </div>
  );
}

export function SearchProgressLine({
  status,
  fallbackKey,
}: {
  status?: string;
  fallbackKey: "searchingWeb" | "deepResearching";
}) {
  const t = useTranslations("chat");
  const label =
    status === "planning"
      ? t("searchProgressPlanning")
      : status === "searching"
        ? t("searchProgressSearching")
        : status === "reading"
          ? t("searchProgressReading")
          : status === "reranking"
            ? t("searchProgressReranking")
            : status === "reflecting"
              ? t("searchProgressReflecting")
              : status === "synthesizing"
                ? t("searchProgressSynthesizing")
                : t(fallbackKey);
  const icon = status === "synthesizing" ? "auto_awesome" : "travel_explore";

  return (
    <div className="flex items-center gap-2 py-1.5 text-sm text-ink-muted">
      <Icon name={icon} className="animate-pulse text-base text-brand" />
      <span>{label}</span>
    </div>
  );
}

/* Deep-research progress UI (Gemini-style). While `active`, a calm panel with a
   "Derin araştırma yapılıyor…" header (subtle animated indicator) lists the
   sub-queries being researched. Once the synthesis starts streaming, the same
   queries stay visible as a collapsible "Araştırılan sorgular" recap above the
   answer. Renders nothing without queries unless still actively researching. */
export function DeepResearchPanel({ queries, active, status }: { queries: string[]; active: boolean; status?: string }) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const hasQueries = queries.length > 0;

  // Active phase: a quiet borderless status — a subtly-pulsing header line and,
  // when present, the sub-queries as light text rows (no box/fill).
  if (active) {
    return (
      <div role="status" className="mb-1">
        <SearchProgressLine status={status} fallbackKey="deepResearching" />
        {hasQueries && (
          <div className="mt-1.5 pl-0.5">
            {queries.map((q, i) => (
              <DeepQueryRow key={i} query={q} />
            ))}
          </div>
        )}
      </div>
    );
  }

  // Recap phase (answer is streaming/done): nothing to show without queries.
  if (!hasQueries) return null;
  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="-ml-1 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium text-ink-muted transition hover:text-ink"
      >
        <Icon name="travel_explore" className="text-sm" />
        <span>
          {t("deepResearchedQueries")} · {queries.length}
        </span>
        <Icon name="expand_more" className={`text-sm transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2 pl-1">
          {queries.map((q, i) => (
            <DeepQueryRow key={i} query={q} />
          ))}
        </div>
      )}
    </div>
  );
}
