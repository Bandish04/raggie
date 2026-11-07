// SPDX-License-Identifier: Apache-2.0

"use client";

// Visual Material Symbols picker. Replaces the free-text "icon" input in the
// skill modals: a trigger button shows the current glyph + a label; clicking
// opens a calm popover with a search box and a scrollable grid of curated
// icons. Picking one sets the icon-name string and closes. Single source of
// truth for both the admin and personal skill modals.
//
// A11y: button + popover, aria-haspopup/expanded on the trigger, role="listbox"
// + role="option" on the grid, Escape + outside-pointer close with focus
// returning to the trigger.

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { Icon } from "@/components/ui/icon";

// Curated set — common skill use-cases, so users never have to know the raw
// Material Symbols names. Order roughly groups by theme (summarize/format,
// communication, knowledge, action, people/time, organize, data, domain).
export const CURATED_ICONS: string[] = [
  "summarize",
  "format_list_bulleted",
  "checklist",
  "mail",
  "school",
  "translate",
  "compare_arrows",
  "edit_note",
  "search",
  "lightbulb",
  "psychology",
  "bolt",
  "auto_awesome",
  "description",
  "article",
  "analytics",
  "table_chart",
  "calculate",
  "code",
  "terminal",
  "gavel",
  "balance",
  "support_agent",
  "campaign",
  "fact_check",
  "quiz",
  "help",
  "build",
  "work",
  "business_center",
  "group",
  "person",
  "event",
  "calendar_month",
  "schedule",
  "flag",
  "star",
  "bookmark",
  "label",
  "category",
  "folder",
  "insights",
  "trending_up",
  "query_stats",
  "notes",
  "format_quote",
  "spellcheck",
  "grading",
  "smart_toy",
  "draw",
  "language",
  "public",
  "science",
  "medical_services",
  "receipt_long",
  "payments",
  "shopping_cart",
  "engineering",
];

export default function IconPicker({
  value,
  onChange,
  ariaLabel,
  searchPlaceholder,
}: {
  value: string;
  onChange: (name: string) => void;
  ariaLabel: string;
  searchPlaceholder: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const selected = value.trim() || "bolt";

  const close = useCallback((focusTrigger = true) => {
    setOpen(false);
    setQuery("");
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  // Close on outside pointer (mirrors Select / composer popovers).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // Focus the search box when the popover opens.
  useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return CURATED_ICONS;
    return CURATED_ICONS.filter((n) => n.replace(/_/g, " ").includes(q) || n.includes(q));
  }, [query]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? close(false) : setOpen(true))}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.preventDefault();
            close();
          }
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={ariaLabel}
        className="flex w-full items-center gap-2.5 rounded-xl border border-border bg-surface px-3 py-2 text-left outline-none transition hover:bg-surface-2 focus-visible:border-brand focus-visible:ring-4 focus-visible:ring-brand/15"
      >
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand">
          <Icon name={selected} size={20} />
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink">{selected}</span>
        <Icon
          name="expand_more"
          size={18}
          className={`shrink-0 text-ink-muted transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          className="absolute left-0 top-full z-40 mt-1.5 w-full origin-top animate-[selectPop_0.14s_cubic-bezier(0.16,1,0.3,1)] overflow-hidden rounded-2xl border border-border bg-surface p-2 shadow-[var(--shadow-lift)]"
        >
          <div className="flex items-center gap-2 rounded-xl border border-border bg-surface px-2.5 py-1.5">
            <Icon name="search" size={18} className="shrink-0 text-ink-muted" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={searchPlaceholder}
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-muted/60"
            />
          </div>

          <ul
            id={listId}
            role="listbox"
            aria-label={ariaLabel}
            className="scrollbar-slim mt-2 grid max-h-56 grid-cols-7 gap-1 overflow-y-auto p-0.5 sm:grid-cols-8"
          >
            {filtered.map((name) => {
              const isSel = name === selected;
              return (
                <li key={name} role="option" aria-selected={isSel}>
                  <button
                    type="button"
                    onClick={() => {
                      onChange(name);
                      close();
                    }}
                    title={name}
                    aria-label={name}
                    className={`grid aspect-square w-full place-items-center rounded-xl outline-none transition focus-visible:ring-2 focus-visible:ring-brand/30 ${
                      isSel ? "bg-brand/10 text-brand" : "text-ink-muted hover:bg-surface-2 hover:text-ink"
                    }`}
                  >
                    <Icon name={name} size={20} />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
