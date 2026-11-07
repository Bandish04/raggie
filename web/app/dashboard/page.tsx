// SPDX-License-Identifier: Apache-2.0

import { getLocale, getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { signOutAction } from "@/app/actions/auth";
import { BrandLogo, BrandName } from "@/components/branding-provider";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Icon } from "@/components/ui/icon";
import { analytics, me } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import { ui } from "@/lib/ui";

type QuickCard = { href: string; icon: string; title: string; sub: string; adminOnly?: boolean };

export default async function DashboardPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");

  const t = await getTranslations();
  const isAdmin = user.role !== "STAFF";
  const a = isAdmin ? await analytics(token) : null;
  const numberFormat = new Intl.NumberFormat(await getLocale());
  const fmt = (n: number) => numberFormat.format(n);

  const stats = a
    ? [
        { icon: "workspaces", label: t("admin.workspaces"), value: a.workspaces },
        { icon: "description", label: t("admin.documents"), value: a.documents.total },
        { icon: "forum", label: t("admin.conversations"), value: a.conversations },
        { icon: "chat", label: t("admin.messages"), value: a.messages },
      ]
    : [];

  const cards: QuickCard[] = [
    { href: "/chat", icon: "forum", title: t("chat.title"), sub: t("chat.greetingSub") },
    {
      href: "/admin/knowledge-base",
      icon: "description",
      title: t("nav.knowledgeBase"),
      sub: t("onboarding.step2Desc"),
    },
    { href: "/admin/organization", icon: "groups", title: t("admin.organizationNav"), sub: t("admin.organizationSubtitle"), adminOnly: true },
    { href: "/admin", icon: "insights", title: t("admin.dashboard"), sub: t("admin.overview"), adminOnly: true },
  ].filter((c) => !c.adminOnly || isAdmin);

  const greeting = t("chat.greeting").replace("👋", "").trim();
  const roleLabel = user.role.replace("_", " ").toLowerCase();

  return (
    <main className="relative mx-auto min-h-screen w-full max-w-5xl px-6 py-8">
      <header className="flex items-center justify-between">
        <span className="flex items-center gap-2.5 font-display text-lg font-semibold">
          <BrandLogo size={32} />
          <BrandName />
        </span>
        <div className="flex items-center gap-2">
          <Link
            href="/account"
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-medium text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="settings" size={20} />
            <span className="hidden sm:inline">{t("nav.account")}</span>
          </Link>
          <form action={signOutAction}>
            <button
              type="submit"
              className="rounded-full px-3 py-2 text-sm font-medium text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
            >
              {t("common.signOut")}
            </button>
          </form>
        </div>
      </header>

      {/* Greeting */}
      <section className="mt-12 sm:mt-14">
        <p className="text-xs font-semibold uppercase tracking-wider text-brand">
          {t("dashboard.signedInAs")}
        </p>
        <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
          {greeting}
        </h1>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge tone="neutral">
            <Icon name="person" size={16} />
            {user.email}
          </Badge>
          <Badge tone="brand" dot>
            {roleLabel}
          </Badge>
        </div>
        <p className="mt-4 max-w-md text-[15px] leading-relaxed text-ink-muted">
          {t("dashboard.homeSub")}
        </p>

        <div className="mt-7 flex flex-wrap gap-3">
          <Link href="/chat" className={`${ui.btnPrimary} px-6 py-3`}>
            <Icon name="forum" size={18} />
            {t("dashboard.startChat")}
          </Link>
          <Link href="/admin/knowledge-base" className={`${ui.btnGhost} px-6 py-3`}>
            <Icon name="upload_file" size={18} />
            {t("dashboard.uploadDocs")}
          </Link>
        </div>
      </section>

      {/* Stats (admins) */}
      {stats.length > 0 && (
        <section className="mt-14">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-ink-muted">
            {t("dashboard.atAGlance")}
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {stats.map((s) => (
              <Card key={s.label} className="p-5">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-surface-2 text-ink-muted">
                  <Icon name={s.icon} size={18} />
                </span>
                <div className="mt-4 font-display text-2xl font-semibold leading-none tabular-nums">
                  {fmt(s.value)}
                </div>
                <div className="mt-1.5 text-sm text-ink-muted">{s.label}</div>
              </Card>
            ))}
          </div>
        </section>
      )}

      {/* Quick access */}
      <section className="mt-14 pb-16">
        <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-ink-muted">
          {t("dashboard.quickAccess")}
        </h2>
        <nav className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {cards.map((c) => (
            <Link
              key={c.href}
              href={c.href}
              className="card card-hover group flex items-center gap-4 p-5"
            >
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-surface-2 text-ink-muted transition-colors group-hover:bg-brand/10 group-hover:text-brand">
                <Icon name={c.icon} size={22} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold text-ink">{c.title}</span>
                <span className="mt-0.5 block truncate text-sm text-ink-muted">{c.sub}</span>
              </span>
              <Icon
                name="arrow_forward"
                size={20}
                className="text-ink-muted transition-transform group-hover:translate-x-0.5 group-hover:text-brand"
              />
            </Link>
          ))}
        </nav>
      </section>
    </main>
  );
}
