// SPDX-License-Identifier: Apache-2.0

"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { SafeMarkdown } from "@/components/chat/answer-markdown";

type AdminConv = {
  id: string;
  title: string;
  user_email: string;
  user_id: string;
  workspace_id: string;
  workspace_name: string;
  evaluation_score: number;
  is_flagged: boolean;
  created_at: string;
};
type Msg = { role: "user" | "assistant"; content: string; sources?: string };

type Source = { filename?: string; document_id?: string; score?: number };

function parseSources(raw?: string): Source[] {
  if (!raw) return [];
  try {
    const a = JSON.parse(raw);
    return Array.isArray(a) ? (a as Source[]) : [];
  } catch {
    return [];
  }
}

export default function ConversationsClient() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const [convs, setConvs] = useState<AdminConv[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [thread, setThread] = useState<Msg[] | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);

  useEffect(() => {
    let on = true;
    (async () => {
      try {
        const res = await fetch("/api/admin/conversations?limit=100", { cache: "no-store" });
        if (on && res.ok) setConvs((await res.json()) as AdminConv[]);
      } catch {
        /* ignore */
      } finally {
        if (on) setLoading(false);
      }
    })();
    return () => {
      on = false;
    };
  }, []);

  async function open(id: string) {
    setActiveId(id);
    setThread(null);
    setThreadLoading(true);
    try {
      const res = await fetch(`/api/admin/conversations/${id}/messages`, { cache: "no-store" });
      setThread(res.ok ? ((await res.json()) as Msg[]) : []);
    } catch {
      setThread([]);
    } finally {
      setThreadLoading(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,360px)_1fr]">
      {/* List */}
      <div className="card max-h-[70vh] overflow-y-auto">
        {loading ? (
          <p className="p-6 text-sm text-ink-muted">…</p>
        ) : convs.length === 0 ? (
          <p className="p-6 text-sm text-ink-muted">{t("conversationsEmpty")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {convs.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => void open(c.id)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition hover:bg-surface-2/50 ${
                    activeId === c.id ? "bg-surface-2" : ""
                  }`}
                >
                  <span className="truncate text-sm font-medium text-ink">
                    {c.title || t("conversationsUntitled")}
                  </span>
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
                    <span className="inline-flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">person</span>
                      {c.user_email || t("conversationsAnon")}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">workspaces</span>
                      {c.workspace_name}
                    </span>
                    {c.is_flagged && (
                      <span className="inline-flex items-center rounded-full bg-danger/10 px-1.5 py-0.5 text-[10px] font-medium text-danger">
                        {t("flagged")} · {c.evaluation_score.toFixed(2)}
                      </span>
                    )}
                  </span>
                  <span className="text-[11px] text-ink-muted/70">
                    {new Date(c.created_at).toLocaleString(locale)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Thread */}
      <div className="card max-h-[70vh] min-h-[20rem] overflow-y-auto p-6">
        {!activeId ? (
          <p className="grid h-full place-items-center text-sm text-ink-muted">
            {t("conversationsSelect")}
          </p>
        ) : threadLoading ? (
          <p className="text-sm text-ink-muted">…</p>
        ) : thread && thread.length > 0 ? (
          <div className="space-y-6">
            {thread.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl bg-surface-2 px-5 py-2.5 text-[15px] leading-relaxed">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex gap-3">
                  <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand/10">
                    <span className="material-symbols-outlined fill text-base text-brand">pets</span>
                  </span>
                  <div className="min-w-0 flex-1">
                    {/* Widget-visitor turns are untrusted: the chat's safe renderer
                        (no remote <img>, safe hrefs) so opening a conversation
                        cannot make the admin's browser fetch a visitor's URL. */}
                    <div className="text-[15px] leading-7 text-ink">
                      <SafeMarkdown content={m.content} />
                    </div>
                    {parseSources(m.sources).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {parseSources(m.sources).map((s, j) => (
                          <span
                            key={j}
                            className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-2 px-2 py-0.5 text-[11px] text-ink-muted"
                          >
                            <span className="material-symbols-outlined text-[13px]">description</span>
                            {s.filename ?? s.document_id}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>
        ) : (
          <p className="text-sm text-ink-muted">{t("conversationsThreadEmpty")}</p>
        )}
      </div>
    </div>
  );
}
