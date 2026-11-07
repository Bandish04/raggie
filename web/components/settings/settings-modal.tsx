// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "@/components/ui/icon";
import type { MemoryItem, ModelsConfig, ProfileResponse } from "@/lib/api";

import AccountSettings, { SETTINGS_TABS, type SettingsTab } from "./account-settings";

type SettingsModalProps = {
  open: boolean;
  onClose: () => void;
  // Which tab to land on when the modal opens (e.g. "preferences" from the menu).
  initialTab?: SettingsTab;
  // Same data <AccountSettings> needs — sourced from the chat page's server fetch.
  profile: ProfileResponse | null;
  email: string;
  memory?: MemoryItem[];
  models: ModelsConfig;
};

/**
 * ChatGPT/Claude-style settings dialog, opened over the chat from the profile
 * dropdown. Mounts the dialog body only while `open` so its inner state (the
 * active tab) initializes fresh from `initialTab` on every open — no
 * setState-in-effect needed.
 */
export default function SettingsModal({ open, ...rest }: SettingsModalProps) {
  if (!open || typeof document === "undefined") return null;
  return createPortal(<SettingsDialog {...rest} />, document.body);
}

/**
 * The dialog itself (rendered only while open). A wide modal with a LEFT tab rail
 * (Profil · Güvenlik · Tercihler · Hafıza, each with an icon) and the selected
 * section on the right; on mobile the rail becomes a horizontal scroller above a
 * full-screen sheet.
 *
 * Accessible: scroll lock, ESC + outside-click close, a focus trap that keeps Tab
 * within the dialog, focus moves in on open, and focus returns to the trigger on
 * close. Renders <AccountSettings variant="modal"> for the active tab; after a
 * successful mutation that component calls router.refresh(), the chat page
 * refetches, and fresh data flows back in.
 */
function SettingsDialog({
  onClose,
  initialTab = "profile",
  profile,
  email,
  memory = [],
  models,
}: Omit<SettingsModalProps, "open">) {
  const t = useTranslations("chat");
  const ta = useTranslations("account");
  // Lazy initial value — set once on mount (this component remounts each open).
  const [tab, setTab] = useState<SettingsTab>(initialTab);
  const dialogRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // What was focused before the dialog mounted, so we can restore it on unmount.
  const restoreFocusRef = useRef<HTMLElement | null>(
    typeof document !== "undefined" ? (document.activeElement as HTMLElement | null) : null,
  );

  // Scroll lock + ESC to close; move focus into the dialog on mount and return
  // it to the trigger on unmount. One effect for the whole open lifecycle.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Defer so the portal node is laid out before we focus into it.
    const raf = requestAnimationFrame(() => {
      const first = dialogRef.current?.querySelector<HTMLElement>(
        "[data-autofocus], button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
      );
      first?.focus();
    });

    const toRestore = restoreFocusRef.current;
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      cancelAnimationFrame(raf);
      toRestore?.focus?.();
    };
  }, [onClose]);

  // Scroll the body back to the top whenever the active tab changes so each
  // section starts at its heading rather than mid-scroll from the last one.
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [tab]);

  // Keep Tab focus within the dialog (simple two-edge focus trap).
  const onKeyDownTrap = useCallback((e: React.KeyboardEvent) => {
    if (e.key !== "Tab") return;
    const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
      "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
    );
    if (!focusables || focusables.length === 0) return;
    const list = Array.from(focusables).filter((el) => el.offsetParent !== null);
    if (list.length === 0) return;
    const first = list[0];
    const last = list[list.length - 1];
    const active = document.activeElement as HTMLElement;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-center p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <div
        className="absolute inset-0 animate-fade-up bg-ink/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={dialogRef}
        onKeyDown={onKeyDownTrap}
        className="relative flex h-full w-full animate-fade-up flex-col overflow-hidden border-border bg-surface shadow-lift sm:h-[min(40rem,90vh)] sm:max-w-3xl sm:rounded-3xl sm:border"
      >
        {/* Header: title + close. Sits above the two-pane body. */}
        <div className="flex shrink-0 items-center justify-between gap-4 border-b border-border px-5 py-4 sm:px-6">
          <h2 id={titleId} className="font-display text-lg font-semibold tracking-tight text-ink">
            {t("settings")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("settingsClose")}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-ink-muted transition hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
          {/* Tab rail: a vertical list on desktop, a horizontal scroller on mobile. */}
          <nav
            aria-label={ta("sectionsNav")}
            className="scrollbar-slim flex shrink-0 gap-1 overflow-x-auto border-b border-border p-2 sm:w-56 sm:flex-col sm:overflow-x-visible sm:overflow-y-auto sm:border-b-0 sm:border-r sm:p-3"
          >
            {SETTINGS_TABS.map((item) => {
              const active = tab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={active ? "page" : undefined}
                  onClick={() => setTab(item.id)}
                  className={`flex shrink-0 items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-brand/30 sm:w-full ${
                    active
                      ? "bg-brand/10 text-brand-strong"
                      : "text-ink-muted hover:bg-surface-2 hover:text-ink"
                  }`}
                >
                  <Icon
                    name={item.icon}
                    size={20}
                    fill={active}
                    className={active ? "text-brand-strong" : "text-ink-muted"}
                  />
                  <span className="truncate">{ta(item.labelKey)}</span>
                </button>
              );
            })}
          </nav>

          {/* Active section, scrollable independently of the rail. */}
          <div ref={bodyRef} className="scrollbar-slim min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-7">
            <AccountSettings
              variant="modal"
              activeTab={tab}
              profile={profile}
              email={email}
              memory={memory}
              models={models}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
