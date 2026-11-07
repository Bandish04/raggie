// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Icon } from "@/components/chat/chat-ui";
/* The model's provider-supplied reasoning panel — calm, text-forward, and
   visually secondary to the answer. Two phases, both borderless/fill-free:
   - Live (`done` false): the reasoning text streams below the activity label.
   - Collapsed (`done` true, i.e. the answer has started): a muted inline text
     toggle ("Düşünce süreci") with a chevron, collapsed by default; clicking
     reveals the full reasoning as plain muted text (no border/fill).
   Renders nothing without reasoning text. */
export function ThinkingPanel({ thinking, done }: { thinking: string; done: boolean }) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const liveTextRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!done && liveTextRef.current) {
      liveTextRef.current.scrollTop = liveTextRef.current.scrollHeight;
    }
  }, [done, thinking]);

  if (!thinking.trim()) return null;

  // Live phase: keep the newest provider-supplied reasoning visible as it grows.
  if (!done) {
    return (
      <div className="mb-4 text-sm text-ink-muted">
        <div role="status" className="mb-2 flex items-center gap-2">
          <Icon name="psychology" className="animate-pulse text-base text-ink-muted" />
          <span>{t("thinkingReasoning")}</span>
        </div>
        <div
          ref={liveTextRef}
          className="scrollbar-slim max-h-52 overflow-y-auto whitespace-pre-wrap break-words pl-6 leading-relaxed"
        >
          {thinking}
          <span aria-hidden className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-ink-muted/60 align-text-bottom" />
        </div>
      </div>
    );
  }

  // Collapsed phase: a muted inline text toggle (no box), collapsed by default.
  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="-ml-1 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium text-ink-muted transition hover:text-ink"
      >
        <Icon name="psychology" className="text-sm" />
        <span>{t("reasoningProcess")}</span>
        <Icon name="expand_more" className={`text-sm transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="scrollbar-slim mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap break-words pl-1 text-sm leading-relaxed text-ink-muted">
          {thinking}
        </div>
      )}
    </div>
  );
}
