// SPDX-License-Identifier: Apache-2.0

"use client";

// The in-app notifications inbox: a bell button (with an unread-count badge) in
// the chat top bar that opens a calm popover listing notifications newest-first.
// Each row shows title, the body (a task result — truncated with expand), a
// relative time, and read state (unread = a subtle dot + tint). Clicking an
// unread one marks it read; a "mark all read" action and per-item delete sit at
// the panel header/rows. After any action → router.refresh(). Accessible: a
// labelled trigger (aria-haspopup/expanded), Escape + outside-pointer close, and
// focus returns to the trigger. Matches the composer popovers' look.

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState, useTransition } from "react";

import {
  deleteNotifAction,
  markAllNotifReadAction,
  markNotifReadAction,
} from "@/app/chat/task-actions";
import type { Notification } from "@/lib/api";

function Icon({ name, className = "", fill = false }: { name: string; className?: string; fill?: boolean }) {
  return (
    <span aria-hidden className={`material-symbols-outlined ${fill ? "fill" : ""} ${className}`}>
      {name}
    </span>
  );
}

// Compact relative time ("3 dk", "2 sa", "5 gün") via Intl.RelativeTimeFormat,
// localized by the active locale (the document lang next-intl sets). Falls back
// to "now" for sub-minute deltas. Past-only (notifications are always in the past).
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffSec = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(diffSec);
  const lang = typeof document !== "undefined" ? document.documentElement.lang || undefined : undefined;
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto", style: "narrow" });
  if (abs < 60) return rtf.format(0, "minute");
  const mins = Math.round(diffSec / 60);
  if (Math.abs(mins) < 60) return rtf.format(mins, "minute");
  const hours = Math.round(diffSec / 3600);
  if (Math.abs(hours) < 24) return rtf.format(hours, "hour");
  const days = Math.round(diffSec / 86400);
  return rtf.format(days, "day");
}

// How many characters of the body to show before offering "show all".
const BODY_TRUNCATE = 220;

/* A single notification row: title, relative time, a delete button, and the body
   (truncated with a calm expand toggle). Unread rows carry a leading brand dot and
   a subtle tint; clicking the row marks it read. */
function NotifRow({
  notif,
  busy,
  onMarkRead,
  onDelete,
}: {
  notif: Notification;
  busy: boolean;
  onMarkRead: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("chat");
  const [expanded, setExpanded] = useState(false);
  const longBody = notif.body.length > BODY_TRUNCATE;
  const shown = expanded || !longBody ? notif.body : `${notif.body.slice(0, BODY_TRUNCATE).trimEnd()}…`;

  return (
    <li
      className={`group rounded-xl p-2.5 transition ${
        notif.is_read ? "hover:bg-surface-2" : "bg-brand/5 hover:bg-brand/10"
      }`}
    >
      <div className="flex items-start gap-2">
        {/* Unread dot (reserves width even when read, so titles stay aligned). */}
        <span className="mt-1.5 grid h-2 w-2 shrink-0 place-items-center">
          {!notif.is_read && <span className="h-2 w-2 rounded-full bg-brand" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <button
              type="button"
              onClick={onMarkRead}
              disabled={notif.is_read || busy}
              title={notif.is_read ? undefined : t("notifMarkRead")}
              className="min-w-0 flex-1 text-left outline-none disabled:cursor-default"
            >
              <span className={`block truncate text-sm ${notif.is_read ? "font-medium text-ink" : "font-semibold text-ink"}`}>
                {notif.title}
              </span>
            </button>
            <span className="shrink-0 whitespace-nowrap pt-0.5 text-[11px] text-ink-muted/80">
              {relativeTime(notif.created_at)}
            </span>
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              aria-label={t("notifDelete")}
              title={t("notifDelete")}
              className="grid h-5 w-5 shrink-0 place-items-center rounded-md text-ink-muted/0 transition hover:bg-surface-3 hover:text-danger focus-visible:text-ink-muted group-hover:text-ink-muted disabled:opacity-50"
            >
              <Icon name="close" className="text-sm" />
            </button>
          </div>
          {notif.body && (
            <p className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-relaxed text-ink-muted">
              {shown}
            </p>
          )}
          {longBody && (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-brand transition hover:text-brand-strong"
            >
              {expanded ? t("notifCollapse") : t("notifExpand")}
              <Icon name="expand_more" className={`text-sm transition-transform ${expanded ? "rotate-180" : ""}`} />
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

export default function NotificationsInbox({
  items,
  unread,
}: {
  items: Notification[];
  unread: number;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  const [, startMutate] = useTransition();
  const [open, setOpen] = useState(false);
  // The notification whose mark-read/delete is in flight (disables its controls).
  const [busyId, setBusyId] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  const close = useCallback((focusTrigger = true) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  // Close on outside pointer (mirrors the composer popovers / Select).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  function markRead(id: string) {
    setBusyId(id);
    startMutate(async () => {
      await markNotifReadAction(id);
      setBusyId(null);
      router.refresh();
    });
  }

  function remove(id: string) {
    setBusyId(id);
    startMutate(async () => {
      await deleteNotifAction(id);
      setBusyId(null);
      router.refresh();
    });
  }

  function markAll() {
    if (unread === 0 || markingAll) return;
    setMarkingAll(true);
    startMutate(async () => {
      await markAllNotifReadAction();
      setMarkingAll(false);
      router.refresh();
    });
  }

  const badge = unread > 9 ? "9+" : String(unread);

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.preventDefault();
            close();
          }
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={unread > 0 ? `${t("inboxOpen")} (${t("inboxUnread", { count: unread })})` : t("inboxOpen")}
        title={t("inbox")}
        className={`relative grid h-9 w-9 place-items-center rounded-full transition ${
          open ? "bg-surface-2 text-ink" : "text-ink-muted hover:bg-surface-2 hover:text-ink"
        }`}
      >
        <Icon name="notifications" className="text-xl" fill={unread > 0} />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid min-w-[16px] place-items-center rounded-full bg-brand px-1 text-[10px] font-semibold leading-4 text-brand-contrast">
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div
          id={panelId}
          role="menu"
          aria-label={t("inbox")}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          className="absolute right-0 top-full z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] origin-top animate-[selectPop_0.14s_cubic-bezier(0.16,1,0.3,1)] overflow-hidden rounded-2xl border border-border bg-surface shadow-[var(--shadow-lift)]"
        >
          {/* Header: title + unread count + "mark all read". */}
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
            <span className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Icon name="inbox" className="text-base text-ink-muted" />
              {t("inbox")}
              {unread > 0 && (
                <span className="rounded-full bg-brand/10 px-1.5 py-px text-[11px] font-medium text-brand-strong">
                  {unread}
                </span>
              )}
            </span>
            {unread > 0 && (
              <button
                type="button"
                onClick={markAll}
                disabled={markingAll}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-ink-muted outline-none transition hover:bg-surface-2 hover:text-ink focus-visible:bg-surface-2 disabled:opacity-50"
              >
                <Icon
                  name={markingAll ? "progress_activity" : "done_all"}
                  className={`text-sm ${markingAll ? "animate-spin" : ""}`}
                />
                {t("markAllRead")}
              </button>
            )}
          </div>

          {items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
              <span className="grid h-11 w-11 place-items-center rounded-2xl bg-surface-2 text-ink-muted">
                <Icon name="inbox" className="text-2xl" />
              </span>
              <p className="text-sm font-medium text-ink">{t("inboxEmpty")}</p>
              <p className="max-w-[15rem] text-xs text-ink-muted">{t("inboxEmptyHint")}</p>
            </div>
          ) : (
            <ul className="scrollbar-slim max-h-[60vh] space-y-0.5 overflow-y-auto p-1.5">
              {items.map((n) => (
                <NotifRow
                  key={n.id}
                  notif={n}
                  busy={busyId === n.id}
                  onMarkRead={() => markRead(n.id)}
                  onDelete={() => remove(n.id)}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
