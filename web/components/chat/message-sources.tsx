// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { safeLinkHref } from "@/lib/security/url";

import { pageOrigin, type Source } from "@/components/chat/chat-model";
import { Icon } from "@/components/chat/chat-ui";
export function hostFromUrl(url?: string): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/* Collapsible sources, rendered as a quiet muted toggle line ("Kaynaklar · N")
   over a light list — not a loud card. Web sources show a letter avatar + domain and
   link out; doc sources show a document icon, title and a score with an
   expandable snippet. Anchor ids let inline [n] citations scroll to the match. */
export function MessageSources({ sources, messageId }: { sources: Source[]; messageId: string }) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="-ml-1 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium text-ink-muted transition hover:text-ink"
      >
        <Icon name="menu_book" className="text-sm" />
        <span>
          {t("sources")} · {sources.length}
        </span>
        <Icon name="expand_more" className={`text-sm transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
          {sources.map((s, j) => {
            const host = s.type === "web" ? hostFromUrl(s.url) : null;
            const title = s.title || s.filename || s.document_id || `${t("sources")} ${j + 1}`;
            const anchorId = `src-${messageId}-${j + 1}`;
            const cardCls =
              "block scroll-mt-24 rounded-xl bg-surface-2/50 p-2.5 text-left transition hover:bg-surface-2";

            if (s.type === "web") {
              return (
                <a
                  key={j}
                  id={anchorId}
                  href={safeLinkHref(s.url, pageOrigin()) ?? undefined}
                  target="_blank"
                  rel="noreferrer"
                  className={cardCls}
                >
                  <div className="flex items-center gap-2">
                    {host ? (
                      // First-letter avatar instead of a third-party favicon
                      // service: fetching favicons would send every cited
                      // domain (i.e. what users research) to an outside host.
                      <span
                        aria-hidden
                        className="grid h-4 w-4 shrink-0 place-items-center rounded bg-brand/10 text-[10px] font-semibold uppercase leading-none text-brand"
                      >
                        {host.charAt(0)}
                      </span>
                    ) : (
                      <Icon name="public" className="shrink-0 text-base text-brand" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink">{title}</span>
                    <Icon name="open_in_new" className="shrink-0 text-sm text-ink-muted" />
                  </div>
                  {host && <span className="mt-1 block truncate text-[11px] text-brand">{host}</span>}
                  {(s.query || s.read_status) && (
                    <span className="mt-1 block truncate text-[11px] text-ink-muted">
                      {[s.read_status === "ok" ? "read" : s.read_status, s.query].filter(Boolean).join(" · ")}
                    </span>
                  )}
                </a>
              );
            }

            const isOpen = expanded === j;
            return (
              <div key={j} id={anchorId} className={cardCls}>
                <button
                  type="button"
                  onClick={() => setExpanded((e) => (e === j ? null : j))}
                  aria-expanded={isOpen}
                  className="flex w-full items-center gap-2 text-left"
                >
                  <Icon name="description" className="shrink-0 text-base text-ink-muted" />
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink">{title}</span>
                  {typeof s.score === "number" && (
                    <span className="shrink-0 text-[11px] font-medium text-ink-muted">
                      {(s.score * 100).toFixed(0)}%
                    </span>
                  )}
                  {s.text && (
                    <Icon
                      name="expand_more"
                      className={`shrink-0 text-base text-ink-muted transition-transform ${isOpen ? "rotate-180" : ""}`}
                    />
                  )}
                </button>
                {isOpen && s.text && (
                  <p className="mt-2 text-xs leading-relaxed text-ink-muted">{s.text}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
