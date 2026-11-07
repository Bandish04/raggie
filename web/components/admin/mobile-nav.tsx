// SPDX-License-Identifier: Apache-2.0

"use client";

import Link from "next/link";
import { useState } from "react";

import { BrandLogo, BrandName } from "@/components/branding-provider";
import { Drawer } from "@/components/ui/drawer";
import { Icon } from "@/components/ui/icon";

export type MobileNavItem = { key: string; href: string; icon: string; label: string };

/**
 * Mobile-only navigation: a hamburger trigger in the header that opens the
 * sidebar inside a slide-in Drawer. Hidden on md+ where the static sidebar
 * shows. `signOut` is the server action <form> rendered by the parent shell.
 */
export default function MobileNav({
  items,
  active,
  email,
  signOut,
  menuLabel,
}: {
  items: MobileNavItem[];
  active: string;
  email: string;
  signOut: React.ReactNode;
  menuLabel: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="md:hidden">
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={menuLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="grid h-10 w-10 place-items-center rounded-full border border-border bg-surface-2 text-ink transition hover:bg-surface-3"
      >
        <Icon name="menu" size={22} />
      </button>

      <Drawer open={open} onClose={() => setOpen(false)} side="left">
        <div className="flex h-full flex-col p-3">
          <div className="mb-2 flex items-center justify-between px-2 py-3">
            <Link
              href="/dashboard"
              onClick={() => setOpen(false)}
              className="flex items-center gap-3"
            >
              <BrandLogo size={36} />
              <div className="leading-tight">
                <div className="font-display text-[17px] font-bold tracking-tight">
                  <BrandName />
                </div>
                <div className="text-xs text-ink-muted">Admin</div>
              </div>
            </Link>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close"
              className="grid h-9 w-9 place-items-center rounded-full text-ink-muted transition hover:bg-surface-2 hover:text-ink"
            >
              <Icon name="close" size={20} />
            </button>
          </div>

          <nav className="flex-1 min-h-0 space-y-1 overflow-y-auto scrollbar-slim">
            {items.map((item) => {
              const on = item.key === active;
              return (
                <Link
                  key={item.key}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  aria-current={on ? "page" : undefined}
                  className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition ${
                    on ? "bg-surface-3 text-ink" : "text-ink-muted hover:bg-surface-3/60 hover:text-ink"
                  }`}
                >
                  <Icon name={item.icon} />
                  {item.label}
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
        </div>
      </Drawer>
    </div>
  );
}
