// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { signOutAction } from "@/app/actions/auth";
import MobileNav from "@/components/admin/mobile-nav";
import { BrandLogo, BrandName } from "@/components/branding-provider";
import { PLATFORM_ONLY_NAV } from "@/lib/permissions";

type NavKey =
  | "dashboard"
  | "usage"
  | "organization"
  | "workspaces"
  | "kb"
  | "marketplace"
  | "conversations"
  | "flagged"
  | "audit"
  | "qdrant"
  | "ai"
  | "skills"
  | "branding"
  | "updates"
  | "team";

const NAV: { key: NavKey; href: string; icon: string; label: keyof Messages }[] = [
  { key: "dashboard", href: "/admin", icon: "dashboard", label: "dashboard" },
  { key: "usage", href: "/admin/usage", icon: "monitoring", label: "usageNav" },
  { key: "organization", href: "/admin/organization", icon: "groups", label: "organizationNav" },
  { key: "workspaces", href: "/admin/workspaces", icon: "workspaces", label: "workspacesNav" },
  { key: "kb", href: "/admin/knowledge-base", icon: "description", label: "knowledgeBase" },
  { key: "marketplace", href: "/admin/marketplace", icon: "storefront", label: "mktNav" },
  { key: "conversations", href: "/admin/conversations", icon: "forum", label: "conversationsNav" },
  { key: "flagged", href: "/admin/flagged", icon: "flag", label: "flagged" },
  { key: "audit", href: "/admin/audit", icon: "receipt_long", label: "auditNav" },
  { key: "qdrant", href: "/admin/qdrant", icon: "scatter_plot", label: "qdrantNav" },
  { key: "ai", href: "/admin/ai", icon: "neurology", label: "aiNav" },
  { key: "skills", href: "/admin/skills", icon: "bolt", label: "skillsNav" },
  { key: "branding", href: "/admin/branding", icon: "palette", label: "brandingNav" },
  { key: "updates", href: "/admin/updates", icon: "system_update_alt", label: "updatesNav" },
];

type Messages = {
  dashboard: string;
  usageNav: string;
  organizationNav: string;
  workspacesNav: string;
  knowledgeBase: string;
  mktNav: string;
  conversationsNav: string;
  flagged: string;
  auditNav: string;
  qdrantNav: string;
  aiNav: string;
  skillsNav: string;
  skills: string;
  brandingNav: string;
  updatesNav: string;
  invite: string;
};

function Icon({ name, className = "" }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

export default async function AdminShell({
  active,
  email,
  platformAdmin = false,
  title,
  subtitle,
  children,
}: {
  active: NavKey;
  email: string;
  // Platform-wide sections (branding, AI config, updates) are only listed for
  // platform admins — the control plane answers 403 to everyone else.
  platformAdmin?: boolean;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  const t = await getTranslations("admin");
  const tc = await getTranslations("common");
  const nav = platformAdmin ? NAV : NAV.filter((n) => !PLATFORM_ONLY_NAV.has(n.key));
  const current = NAV.find((n) => n.key === active);

  // The sign-out control is identical in the desktop sidebar and the mobile
  // drawer, so build it once and reuse it in both places.
  const signOut = (
    <form action={signOutAction}>
      <button
        type="submit"
        className="flex w-full items-center gap-3 rounded-2xl px-4 py-2.5 text-sm text-ink-muted transition hover:bg-surface-3/60 hover:text-ink"
      >
        <Icon name="logout" />
        {tc("signOut")}
      </button>
    </form>
  );

  const navItems = nav.map((n) => ({
    key: n.key,
    href: n.href,
    icon: n.icon,
    label: t(n.label),
  }));

  return (
    <div className="flex min-h-screen w-full bg-bg text-ink">
      {/* Sidebar (desktop) */}
      <aside className="hidden w-[280px] shrink-0 flex-col border-r border-border/50 bg-surface-2/70 p-3 backdrop-blur-xl md:sticky md:top-0 md:flex md:h-screen">
        <Link href="/dashboard" className="mb-2 flex items-center gap-3 px-2 py-4">
          <BrandLogo size={40} />
          <div className="leading-tight">
            <div className="font-display text-[18px] font-bold tracking-tight">
              <BrandName />
            </div>
            <div className="text-xs text-ink-muted">Admin</div>
          </div>
        </Link>

        <nav className="flex-1 min-h-0 space-y-1 overflow-y-auto scrollbar-slim">
          {nav.map((item) => {
            const on = item.key === active;
            return (
              <Link
                key={item.key}
                href={item.href}
                aria-current={on ? "page" : undefined}
                className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition-all active:translate-x-1 ${
                  on
                    ? "bg-surface-3 text-ink"
                    : "text-ink-muted hover:bg-surface-3/60 hover:text-ink"
                }`}
              >
                <Icon name={item.icon} />
                {t(item.label)}
              </Link>
            );
          })}
        </nav>

        <div className="space-y-2 border-t border-border/50 pt-3">
          <div className="truncate px-4 text-xs text-ink-muted" title={email}>
            {email}
          </div>
          {signOut}
        </div>
      </aside>

      {/* Main */}
      <main className="min-w-0 flex-1">
        {/* Mobile top bar: menu trigger + brand. Hidden on md+ where the sidebar shows. */}
        <div className="flex items-center gap-3 px-6 pt-6 sm:px-10 md:hidden">
          <MobileNav
            items={navItems}
            active={active}
            email={email}
            signOut={signOut}
            menuLabel={tc("menu")}
          />
          <Link href="/dashboard" className="flex items-center gap-2">
            <BrandLogo size={28} />
            <span className="font-display text-base font-bold tracking-tight">
              <BrandName />
            </span>
          </Link>
        </div>
        <header className="px-6 pb-10 pt-6 sm:px-10 sm:pb-14 md:pt-4">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand">
            {current ? t(current.label) : "Raggie"}
          </p>
          <h1 className="mt-3 font-display text-5xl font-semibold leading-[1.02] sm:text-6xl">
            {title}
          </h1>
          {subtitle && <p className="mt-4 max-w-xl text-lg text-ink-muted">{subtitle}</p>}
        </header>
        <div className="px-6 pb-16 sm:px-10">{children}</div>
      </main>
    </div>
  );
}
