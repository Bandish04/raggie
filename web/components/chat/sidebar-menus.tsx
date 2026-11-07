// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState, useTransition } from "react";

import { deleteMySkillAction } from "@/app/chat/skill-actions";
import type { AvailableIntegration, ModelsConfig, Skill } from "@/lib/api";

import { initials } from "@/components/chat/chat-model";
import { Icon } from "@/components/chat/chat-ui";
import { PersonalSkillModal } from "@/components/chat/personal-skill-modal";
/* The sidebar "Skills" entry (ChatGPT-style), sitting right under "New chat". A
   button that toggles a calm inline panel listing the org's enabled skills;
   clicking one activates it (same effect as picking from "/"). Anyone can create
   a personal skill (+ edit/delete their own inline). Admins also get a "Yönet"
   link to the org builder. Accessible: aria-expanded on the trigger, Escape +
   outside-pointer close, focus returns to the trigger. */
export function SidebarSkillsMenu({
  skills,
  isAdmin,
  models,
  activeSkillId,
  onPick,
}: {
  skills: Skill[];
  isAdmin: boolean;
  models: ModelsConfig;
  activeSkillId: string | null;
  onPick: (skill: Skill) => void;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  const [, startDelete] = useTransition();
  // Personal-skill modal: closed, or open for create (null) / edit (a skill).
  const [modal, setModal] = useState<{ open: boolean; editing: Skill | null }>({
    open: false,
    editing: null,
  });

  function removeMine(s: Skill) {
    if (!window.confirm(t("skillDeleteConfirm", { name: s.name }))) return;
    startDelete(async () => {
      await deleteMySkillAction(s.id);
      router.refresh();
    });
  }

  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

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
    <div ref={rootRef} className="relative">
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
        className="flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-ink-muted transition-colors hover:bg-surface-3/60 hover:text-ink"
      >
        <Icon name="bolt" />
        <span className="min-w-0 flex-1 truncate text-left text-sm">{t("skills")}</span>
        <Icon name="expand_more" className={`text-base transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          id={panelId}
          role="menu"
          aria-label={t("skills")}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          className="mt-1 overflow-hidden rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-soft)]"
        >
          {skills.length === 0 ? (
            <p className="px-3 py-2 text-xs leading-relaxed text-ink-muted">{t("skillsEmpty")}</p>
          ) : (
            <ul className="scrollbar-slim max-h-64 space-y-0.5 overflow-y-auto">
              {skills.map((s) => {
                const isActive = s.id === activeSkillId;
                const isMine = s.visibility === "personal";
                return (
                  <li
                    key={s.id}
                    className={`group flex items-center gap-1 rounded-xl pr-1 transition ${
                      isActive ? "bg-surface-2" : "hover:bg-surface-2"
                    }`}
                  >
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        onPick(s);
                        close(false);
                      }}
                      className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl px-2.5 py-2 text-left outline-none focus-visible:bg-surface-2"
                    >
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-ink-muted">
                        <Icon name={s.icon?.trim() || "bolt"} className="text-sm" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className="truncate text-sm font-medium text-ink">{s.name}</span>
                          {isMine && (
                            <span className="shrink-0 rounded-full bg-surface-2 px-1.5 py-px text-[10px] font-medium text-ink-muted">
                              {t("skillPersonal")}
                            </span>
                          )}
                        </span>
                        <span className="block truncate font-mono text-[11px] text-ink-muted">/{s.slug}</span>
                      </span>
                      {isActive && <Icon name="check" className="shrink-0 text-base text-ink-muted" />}
                    </button>
                    {isMine && (
                      <span className="flex shrink-0 items-center gap-0.5">
                        <button
                          type="button"
                          title={t("skillEditMine")}
                          aria-label={t("skillEditMine")}
                          onClick={() => setModal({ open: true, editing: s })}
                          className="grid h-6 w-6 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-3 hover:text-ink"
                        >
                          <Icon name="edit" className="text-sm" />
                        </button>
                        <button
                          type="button"
                          title={t("skillDeleteMine")}
                          aria-label={t("skillDeleteMine")}
                          onClick={() => removeMine(s)}
                          className="grid h-6 w-6 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-3 hover:text-danger"
                        >
                          <Icon name="delete" className="text-sm" />
                        </button>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            role="menuitem"
            onClick={() => setModal({ open: true, editing: null })}
            className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm text-ink-muted outline-none transition hover:bg-surface-2 hover:text-ink focus-visible:bg-surface-2"
          >
            <Icon name="add" className="text-base" />
            {t("skillCreate")}
          </button>
          {isAdmin && (
            <a
              href="/admin/skills"
              className="flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-ink-muted outline-none transition hover:bg-surface-2 hover:text-ink focus-visible:bg-surface-2"
            >
              <Icon name="tune" className="text-base" />
              {t("manageSkills")}
            </a>
          )}
        </div>
      )}

      {modal.open && (
        <PersonalSkillModal
          key={modal.editing?.id ?? "new-personal-skill"}
          open={modal.open}
          onClose={() => setModal({ open: false, editing: null })}
          editing={modal.editing}
          models={models}
        />
      )}
    </div>
  );
}

/* The sidebar "Araçlar" (Tools) entry, sitting beneath Skills. A calm inline
   panel listing the org's connected MCP integrations (icon + name + a small
   connected dot) with a single per-turn "Use tools" toggle. When on, the chat
   request seeds `mcp_tools` so the agent can call those tools this turn. The
   toggle is opt-in (default off) and integration-level (no per-tool checkboxes
   yet). Accessible: aria-expanded on the trigger, Escape + outside-pointer
   close, focus returns to the trigger. Mirrors SidebarSkillsMenu. */
export function SidebarToolsMenu({
  tools,
  toolsMode,
  onToggle,
}: {
  tools: AvailableIntegration[];
  toolsMode: boolean;
  onToggle: () => void;
}) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

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

  const hasTools = tools.length > 0;

  return (
    <div ref={rootRef} className="relative">
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
        className="flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-ink-muted transition-colors hover:bg-surface-3/60 hover:text-ink"
      >
        <Icon name="construction" />
        <span className="min-w-0 flex-1 truncate text-left text-sm">{t("toolsMenu")}</span>
        {/* A quiet dot mirrors the active state in the collapsed trigger. */}
        {toolsMode && hasTools && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />}
        <Icon name="expand_more" className={`text-base transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          id={panelId}
          role="menu"
          aria-label={t("toolsMenu")}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          className="mt-1 overflow-hidden rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-soft)]"
        >
          {!hasTools ? (
            <p className="px-3 py-2 text-xs leading-relaxed text-ink-muted">{t("toolsEmpty")}</p>
          ) : (
            <>
              {/* Per-turn "Use tools" toggle — drives the toolsMode boolean. */}
              <button
                type="button"
                role="menuitemcheckbox"
                aria-checked={toolsMode}
                onClick={() => onToggle()}
                className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left outline-none transition hover:bg-surface-2 focus-visible:bg-surface-2"
              >
                <span
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition ${
                    toolsMode ? "bg-brand" : "bg-surface-3"
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition ${
                      toolsMode ? "translate-x-[18px]" : "translate-x-[3px]"
                    }`}
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink">{t("toolsUse")}</span>
                  <span className="block text-[11px] text-ink-muted">{t("toolsUseHint")}</span>
                </span>
              </button>
              <div className="my-1 h-px bg-border" />
              <ul className="scrollbar-slim max-h-64 space-y-0.5 overflow-y-auto">
                {tools.map((tool) => (
                  <li
                    key={tool.provider}
                    className="flex items-center gap-2.5 rounded-xl px-2.5 py-2"
                  >
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-ink-muted">
                      <Icon name={tool.icon?.trim() || "extension"} className="text-sm" />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
                      {tool.display_name || tool.provider}
                    </span>
                    {/* Small connected dot — the integration is live for the org. */}
                    <span
                      className="h-1.5 w-1.5 shrink-0 rounded-full bg-success"
                      title={t("toolsConnected")}
                      aria-label={t("toolsConnected")}
                    />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export type AccountMenuItem = {
  key: string;
  label: string;
  icon?: string;
  danger?: boolean;
  onSelect: () => void;
};

/* The account block anchored at the BOTTOM of the sidebar (ChatGPT/Claude
   pattern): an avatar (initials) + the user's name as a full-width button that
   opens a menu UPWARD (so it never spills below the viewport). Mirrors the shared
   DropdownMenu's a11y — WAI-ARIA "menu" disclosure with click-outside + Escape to
   close, focus returns to the trigger, ArrowUp/Down/Home/End roving focus — but
   positions itself above the trigger and renders an avatar+name trigger. */
export function AccountMenu({
  name,
  email,
  items,
  ariaLabel,
}: {
  name?: string | null;
  email: string;
  items: AccountMenuItem[];
  ariaLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const close = useCallback((focusTrigger = true) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  // Close on outside pointer (mirrors DropdownMenu / Select).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // Move focus to the first item when the menu opens (DOM sync only).
  useEffect(() => {
    if (open) menuRef.current?.querySelector<HTMLElement>("[role='menuitem']")?.focus();
  }, [open]);

  function focusItem(idx: number) {
    const els = menuRef.current?.querySelectorAll<HTMLElement>("[role='menuitem']");
    if (!els || els.length === 0) return;
    els[(idx + els.length) % els.length]?.focus();
  }
  function currentIndex(): number {
    const els = menuRef.current?.querySelectorAll<HTMLElement>("[role='menuitem']");
    if (!els) return -1;
    return Array.from(els).indexOf(document.activeElement as HTMLElement);
  }
  function onMenuKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        focusItem(currentIndex() + 1);
        break;
      case "ArrowUp":
        e.preventDefault();
        focusItem(currentIndex() - 1);
        break;
      case "Home":
        e.preventDefault();
        focusItem(0);
        break;
      case "End":
        e.preventDefault();
        focusItem(-1);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        setOpen(false);
        break;
    }
  }

  const label = (name && name.trim()) || email || ariaLabel;

  return (
    <div ref={rootRef} className="relative">
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
        title={label}
        className="flex w-full items-center gap-3 rounded-2xl px-2 py-2 text-left outline-none transition-colors hover:bg-surface-3/60 focus-visible:bg-surface-3/60"
      >
        <span
          aria-hidden
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-border bg-surface-2 text-sm font-semibold text-ink"
        >
          {initials(name, email)}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{label}</span>
        <span className="sr-only">{ariaLabel}</span>
        <Icon name="unfold_more" className="shrink-0 text-base text-ink-muted" />
      </button>

      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={ariaLabel}
          onKeyDown={onMenuKeyDown}
          className="absolute bottom-full left-0 right-0 z-50 mb-2 origin-bottom animate-[selectPop_0.14s_cubic-bezier(0.16,1,0.3,1)] overflow-hidden rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-lift)]"
        >
          {items.map((it) => (
            <button
              key={it.key}
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                close(false);
                it.onSelect();
              }}
              className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm outline-none transition focus-visible:bg-surface-2 ${
                it.danger
                  ? "text-danger hover:bg-danger/10 focus-visible:bg-danger/10"
                  : "text-ink hover:bg-surface-2"
              }`}
            >
              {it.icon && (
                <Icon
                  name={it.icon}
                  className={`text-lg ${it.danger ? "text-danger" : "text-ink-muted"}`}
                />
              )}
              <span className="min-w-0 flex-1 truncate">{it.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
