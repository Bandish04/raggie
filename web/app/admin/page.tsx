// SPDX-License-Identifier: Apache-2.0

import { getLocale, getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import { analytics, me } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

function StatCard({ icon, label, value, tint }: { icon: string; label: string; value: string | number; tint: string }) {
  return (
    <div className="card card-hover flex items-center gap-4 p-5">
      <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${tint}`}>
        <span className="material-symbols-outlined">{icon}</span>
      </span>
      <div className="min-w-0">
        <div className="font-display text-2xl font-bold leading-none">{value}</div>
        <div className="mt-1 truncate text-xs text-ink-muted">{label}</div>
      </div>
    </div>
  );
}

export default async function AdminDashboard() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");

  const t = await getTranslations("admin");
  const numberFormat = new Intl.NumberFormat(await getLocale());
  const fmt = (n: number) => numberFormat.format(n);
  const a = await analytics(token);

  const docs = a?.documents ?? { total: 0, pending: 0, processing: 0, success: 0, failed: 0 };
  const activity = a?.activity ?? [];
  const peak = Math.max(1, ...activity.map((p) => p.messages));

  const docBars: { label: string; n: number; color: string }[] = [
    { label: t("statusSUCCESS"), n: docs.success, color: "bg-success" },
    { label: t("statusPROCESSING"), n: docs.processing, color: "bg-accent" },
    { label: t("statusPENDING"), n: docs.pending, color: "bg-ink-muted" },
    { label: t("statusFAILED"), n: docs.failed, color: "bg-danger" },
  ];

  return (
    <AdminShell active="dashboard" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("dashboard")} subtitle={t("overview")}>
      {/* Stat cards */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <StatCard icon="workspaces" label={t("workspaces")} value={fmt(a?.workspaces ?? 0)} tint="bg-brand/10 text-brand" />
        <StatCard icon="description" label={t("documents")} value={fmt(docs.total)} tint="bg-accent/10 text-accent" />
        <StatCard icon="forum" label={t("conversations")} value={fmt(a?.conversations ?? 0)} tint="bg-brand/10 text-brand" />
        <StatCard icon="chat" label={t("messages")} value={fmt(a?.messages ?? 0)} tint="bg-accent/10 text-accent" />
        <StatCard icon="toll" label={t("tokensUsed")} value={fmt(a?.tokens_used ?? 0)} tint="bg-brand/10 text-brand" />
        <StatCard icon="flag" label={t("flagged")} value={fmt(a?.flagged ?? 0)} tint="bg-danger/10 text-danger" />
      </section>

      {/* Charts */}
      <section className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Document volume */}
        <div className="card card-hover p-6">
          <h2 className="font-display text-sm font-semibold text-ink-muted">{t("docVolume")}</h2>
          <div className="mt-5 space-y-3.5">
            {docBars.map((b) => (
              <div key={b.label} className="flex items-center gap-3">
                <span className="w-20 shrink-0 text-xs text-ink-muted">{b.label}</span>
                <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={`h-full rounded-full ${b.color} transition-all duration-500`}
                    style={{ width: `${docs.total ? Math.max(b.n > 0 ? 4 : 0, (b.n / docs.total) * 100) : 0}%` }}
                  />
                </div>
                <span className="w-8 shrink-0 text-right text-xs font-medium tabular-nums">{b.n}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 7-day activity */}
        <div className="card card-hover p-6">
          <h2 className="font-display text-sm font-semibold text-ink-muted">{t("activity")}</h2>
          {activity.length === 0 ? (
            <p className="mt-6 text-sm text-ink-muted">{t("noData")}</p>
          ) : (
            <div className="relative mt-5 h-40">
              {/* faint gridlines behind the bars */}
              <div className="pointer-events-none absolute inset-x-0 top-0 flex h-[calc(100%-1.5rem)] flex-col justify-between">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="border-t border-border/60" />
                ))}
              </div>
              <div className="relative flex h-full items-end justify-between gap-2">
                {activity.map((p) => (
                  <div key={p.date} className="group flex flex-1 flex-col items-center gap-2">
                    <div className="flex w-full flex-1 items-end">
                      <div
                        className="relative w-full rounded-t-md bg-gradient-to-t from-brand/55 to-brand transition-all duration-500 hover:from-brand/70"
                        style={{ height: `${Math.max(4, (p.messages / peak) * 100)}%` }}
                      >
                        <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[10px] font-semibold tabular-nums text-ink opacity-0 transition group-hover:opacity-100">
                          {p.messages}
                        </span>
                      </div>
                    </div>
                    <span className="text-[10px] text-ink-muted">{p.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </AdminShell>
  );
}
