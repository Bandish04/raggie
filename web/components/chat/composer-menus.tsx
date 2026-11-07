// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import type { Skill } from "@/lib/api";

import type { ReasoningEffort } from "@/components/chat/chat-model";
import { Icon } from "@/components/chat/chat-ui";
/* The composer "+" menu (ChatGPT-style): a left button that opens a calm popover
   holding attach + the web/deep tools + reasoning effort, keeping the input row
   itself minimal ([+] [textarea] [send]). Built as a popover consistent with the
   composer's other popovers (rounded-2xl, shadow-lift, selectPop) but with proper
   menu a11y: aria-haspopup/expanded on the trigger, role="menu" on the panel,
   Escape + outside-pointer close, and focus returning to the trigger on close.

   `webMode`/`deepMode` are mutually exclusive (toggling one clears the other) and
   render with a check when active. Reasoning effort is an inline 3-way segmented
   control so the choice is one tap, never buried in a submenu. */
export function ComposerToolsMenu({
  visionEnabled,
  onAttach,
  webMode,
  deepMode,
  onToggleWeb,
  onToggleDeep,
  effort,
  onChangeEffort,
}: {
  visionEnabled: boolean;
  onAttach: () => void;
  webMode: boolean;
  deepMode: boolean;
  onToggleWeb: () => void;
  onToggleDeep: () => void;
  effort: ReasoningEffort;
  onChangeEffort: (e: ReasoningEffort) => void;
}) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  const close = useCallback((focusTrigger = true) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  // Close on outside pointer (mirrors Select / DropdownMenu).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  const effortOptions: { value: ReasoningEffort; label: string }[] = [
    { value: "low", label: t("effortLow") },
    { value: "medium", label: t("effortMedium") },
    { value: "high", label: t("effortHigh") },
  ];

  // A tool row: icon + label, with a trailing check when active. Toggling keeps
  // the menu open so the active/mutually-exclusive state is visible immediately.
  const toolRow = (active: boolean, onClick: () => void, icon: string, label: string) => (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={active}
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm outline-none transition focus-visible:bg-surface-2 ${
        active ? "bg-brand/10 text-brand-strong" : "text-ink hover:bg-surface-2"
      }`}
    >
      <Icon name={icon} fill={active} className={`text-lg ${active ? "text-brand-strong" : "text-ink-muted"}`} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {active && <Icon name="check" className="text-lg text-brand" />}
    </button>
  );

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
        aria-controls={open ? menuId : undefined}
        aria-label={t("addMenu")}
        title={t("addMenu")}
        className={`grid h-9 w-9 place-items-center rounded-full transition ${
          open ? "bg-surface-2 text-ink" : "text-ink-muted hover:bg-surface-2 hover:text-ink"
        }`}
      >
        <Icon name="add" className="text-xl" />
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={t("addMenu")}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          className="absolute bottom-full left-0 z-30 mb-2 w-64 origin-bottom animate-[selectPop_0.14s_cubic-bezier(0.16,1,0.3,1)] overflow-hidden rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-lift)]"
        >
          {visionEnabled && (
            <>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  close(false);
                  onAttach();
                }}
                className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm text-ink outline-none transition hover:bg-surface-2 focus-visible:bg-surface-2"
              >
                <Icon name="image" className="text-lg text-ink-muted" />
                <span className="min-w-0 flex-1 truncate">{t("attachImage")}</span>
              </button>
              <div className="my-1 h-px bg-border" />
            </>
          )}

          {/* Tools group: web & deep research (mutually exclusive, checked active). */}
          <p className="px-3 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
            {t("tools")}
          </p>
          {toolRow(webMode, onToggleWeb, "language", t("webMode"))}
          {toolRow(deepMode, onToggleDeep, "travel_explore", t("deepMode"))}

          {/* Reasoning effort: inline segmented control (one tap, brain icon). */}
          <div className="my-1 h-px bg-border" />
          <p className="flex items-center gap-1.5 px-3 pb-1.5 pt-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
            <Icon name="psychology" className="text-sm text-ink-muted opacity-100" />
            {t("effort")}
          </p>
          <div
            role="radiogroup"
            aria-label={t("effort")}
            className="mx-1.5 mb-1 flex gap-0.5 rounded-xl bg-surface-2 p-0.5"
          >
            {effortOptions.map((o) => {
              const active = effort === o.value;
              return (
                <button
                  key={o.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => onChangeEffort(o.value)}
                  className={`flex-1 rounded-lg px-2 py-1.5 text-xs font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-brand/30 ${
                    active ? "bg-surface text-ink shadow-soft" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  {o.label}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* The model picker, living compactly on the RIGHT of the composer input row (per
   the PO) — a small `neurology` trigger that opens an UPWARD listbox of allowed
   models. Built as a listbox for a11y (aria-haspopup/expanded, role="listbox" +
   role="option", aria-selected, Escape + outside-pointer close, focus returns to
   the trigger), consistent with the composer's other popovers. Only rendered by
   the caller when there are allowed models to choose. */
export function ComposerModelPicker({
  models,
  value,
  onChange,
  label,
  aliases,
}: {
  models: string[];
  value: string;
  onChange: (model: string) => void;
  label: string;
  // Display aliases (model id -> friendly name). Affects only the shown label;
  // the value sent to the backend stays the raw model id.
  aliases?: Record<string, string>;
}) {
  const displayName = (id: string) => aliases?.[id] ?? id;
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listId = useId();

  const close = useCallback((focusTrigger = true) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

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
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`${label}: ${displayName(value)}`}
        title={`${label}: ${displayName(value)}`}
        className={`flex h-9 max-w-[40vw] items-center gap-1 rounded-full px-2.5 text-xs font-medium outline-none transition sm:max-w-[12rem] ${
          open ? "text-ink" : "text-ink-muted hover:text-ink"
        }`}
      >
        <span className="min-w-0 truncate">{displayName(value)}</span>
        <Icon name="expand_more" className={`shrink-0 text-sm transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          className="scrollbar-slim absolute bottom-full right-0 z-30 mb-2 max-h-72 w-56 origin-bottom animate-[selectPop_0.14s_cubic-bezier(0.16,1,0.3,1)] overflow-auto rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-lift)]"
        >
          {models.map((m) => {
            const isSel = m === value;
            return (
              <li
                key={m}
                role="option"
                aria-selected={isSel}
                onClick={() => {
                  onChange(m);
                  close();
                }}
                className={`flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink transition hover:bg-surface-2 ${
                  isSel ? "bg-surface-2" : ""
                }`}
              >
                <Icon name="neurology" className="shrink-0 text-base text-ink-muted" />
                <span className="min-w-0 flex-1 truncate">{displayName(m)}</span>
                {isSel && <Icon name="check" className="shrink-0 text-lg text-brand" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* The "/command" skill picker: a calm popover anchored above the composer, shown
   while the input begins with "/". Filters the org's enabled skills by slug+name
   on the text typed after the slash, with full keyboard support (Up/Down to move,
   Enter to choose, Escape to dismiss). Picking a skill activates it and clears the
   "/…" text. Built as a listbox for a11y (aria-activedescendant + role="option"),
   consistent with the composer's other popovers (rounded-2xl, shadow-lift). */
export function SkillPicker({
  skills,
  query,
  onPick,
  onDismiss,
  registerKeydown,
}: {
  skills: Skill[];
  query: string;
  onPick: (skill: Skill) => void;
  onDismiss: () => void;
  // The composer textarea keeps focus, so it forwards arrow/enter/escape here via
  // this imperative handle (set to null when the picker is closed).
  registerKeydown: (handler: ((e: React.KeyboardEvent) => boolean) | null) => void;
}) {
  const t = useTranslations("chat");
  const baseId = useId();
  const [highlight, setHighlight] = useState(0);

  const q = query.toLowerCase();
  const filtered = q
    ? skills.filter(
        (s) => s.slug.toLowerCase().includes(q) || s.name.toLowerCase().includes(q),
      )
    : skills;

  // Clamp at read time so the highlight stays valid as the filtered set shrinks
  // under the user's typing — no clamping effect (avoids cascading renders).
  const active = filtered.length ? Math.min(highlight, filtered.length - 1) : 0;

  // Bridge the textarea's keydown to listbox navigation. Returning true tells the
  // composer we handled the key (so it prevents default / stops sending).
  useEffect(() => {
    registerKeydown((e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        setHighlight((h) => (filtered.length ? (Math.min(h, filtered.length - 1) + 1) % filtered.length : 0));
        return true;
      }
      if (e.key === "ArrowUp") {
        setHighlight((h) =>
          filtered.length
            ? (Math.min(h, filtered.length - 1) - 1 + filtered.length) % filtered.length
            : 0,
        );
        return true;
      }
      if (e.key === "Enter") {
        const s = filtered[active];
        if (s) onPick(s);
        return true;
      }
      if (e.key === "Escape") {
        onDismiss();
        return true;
      }
      return false;
    });
    return () => registerKeydown(null);
  }, [filtered, active, onPick, onDismiss, registerKeydown]);

  const optId = (i: number) => `${baseId}-opt-${i}`;

  return (
    <div className="absolute bottom-full left-0 right-0 z-30 mb-2">
      <div className="mx-auto w-full max-w-3xl px-1">
        <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-[var(--shadow-lift)]">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
            <Icon name="bolt" className="text-sm text-brand" />
            {t("skillPicker")}
          </div>
          {filtered.length === 0 ? (
            <p className="px-3 py-3 text-sm text-ink-muted">{t("skillsEmpty")}</p>
          ) : (
            <ul
              role="listbox"
              aria-label={t("skillPicker")}
              aria-activedescendant={optId(active)}
              className="scrollbar-slim max-h-64 overflow-y-auto p-1.5"
            >
              {filtered.map((s, i) => {
                const isHi = i === active;
                return (
                  <li
                    key={s.id}
                    id={optId(i)}
                    role="option"
                    aria-selected={isHi}
                    onMouseEnter={() => setHighlight(i)}
                    onMouseDown={(e) => {
                      // Keep textarea focus; commit on click without a blur first.
                      e.preventDefault();
                      onPick(s);
                    }}
                    className={`flex cursor-pointer items-center gap-2.5 rounded-xl px-2.5 py-2 ${
                      isHi ? "bg-surface-2" : ""
                    }`}
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand/10 text-brand">
                      <Icon name={s.icon?.trim() || "bolt"} className="text-base" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-ink">{s.name}</span>
                        <span className="shrink-0 font-mono text-xs text-brand">/{s.slug}</span>
                      </span>
                      {s.description && (
                        <span className="mt-0.5 block truncate text-xs text-ink-muted">
                          {s.description}
                        </span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
