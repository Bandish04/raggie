// SPDX-License-Identifier: Apache-2.0

"use client";

// A minimal, accessible dropdown menu in the "Sakin & Ferah" style — the
// Claude/ChatGPT-style avatar menu. A trigger you render (renderTrigger) opens a
// floating menu of items (links + actions). Implements the WAI-ARIA "menu"
// disclosure pattern: click-outside + Escape to close, focus returns to the
// trigger, ArrowUp/Down/Home/End roving focus across items.
//
// The menu is PORTALED to <body> and positioned with `fixed` viewport coords
// derived from the trigger, so it is never clipped by an ancestor's
// `overflow:hidden` nor trapped beneath a later sibling card (e.g. the Knowledge
// Base grid tiles, whose tile + card both clip). It flips above the trigger when
// it would overflow the viewport bottom, and re-positions on scroll/resize.
// Zero runtime deps beyond react-dom's portal.

import {
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

export type DropdownItem = {
  key: string;
  label: string;
  icon?: string; // Material Symbols name
  href?: string; // renders an <a>; mutually exclusive with onSelect
  onSelect?: () => void; // renders a <button>
  danger?: boolean; // tints the item (e.g. sign out)
};

type DropdownMenuProps = {
  items: DropdownItem[];
  ariaLabel: string;
  align?: "start" | "end"; // which edge the menu aligns to (default "end")
  // Render-prop trigger so callers control the avatar/button look. The supplied
  // props MUST be spread onto a focusable element (button) for a11y wiring.
  renderTrigger: (props: {
    ref: React.Ref<HTMLButtonElement>;
    onClick: () => void;
    "aria-haspopup": "menu";
    "aria-expanded": boolean;
    "aria-controls"?: string;
    "aria-label": string;
  }) => ReactNode;
};

type MenuPos = { top: number; left: number };

export default function DropdownMenu({
  items,
  ariaLabel,
  align = "end",
  renderTrigger,
}: DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  // null until measured — the menu stays hidden for that first frame so it
  // never flashes at the top-left corner.
  const [pos, setPos] = useState<MenuPos | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const baseId = useId();
  const menuId = `${baseId}-menu`;

  const openMenu = useCallback(() => {
    setPos(null);
    setOpen(true);
  }, []);

  const close = useCallback((focusTrigger = true) => {
    setOpen(false);
    setPos(null);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  // Position the portaled menu under (or above, if it would overflow) the
  // trigger. Recomputed on open, scroll, and resize.
  useEffect(() => {
    if (!open) return;
    const place = () => {
      const t = triggerRef.current;
      if (!t) return;
      const r = t.getBoundingClientRect();
      const m = menuRef.current;
      const mh = m?.offsetHeight ?? 200;
      const mw = m?.offsetWidth ?? 224;
      const GAP = 8;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      // Flip above when there isn't room below but there is above.
      const flipUp = r.bottom + GAP + mh > vh && r.top - GAP - mh > 8;
      const top = flipUp ? r.top - GAP - mh : r.bottom + GAP;
      let left = align === "end" ? r.right - mw : r.left;
      left = Math.max(8, Math.min(left, vw - mw - 8));
      setPos({ top: Math.max(8, top), left });
    };
    place();
    // Re-measure once the menu has its real dimensions (icons/fonts settled).
    const raf = requestAnimationFrame(place);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, align]);

  // Close on outside pointer. The menu lives in a body portal (outside rootRef),
  // so an interaction inside it must NOT count as "outside".
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (rootRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      close(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [close, open]);

  // Move focus to the first item once the menu is open AND placed (a
  // visibility:hidden element can't take focus, so wait for `pos`).
  useEffect(() => {
    if (open && pos) {
      const first = menuRef.current?.querySelector<HTMLElement>("[role='menuitem']");
      first?.focus();
    }
  }, [open, pos]);

  function focusItem(idx: number) {
    const els = menuRef.current?.querySelectorAll<HTMLElement>("[role='menuitem']");
    if (!els || els.length === 0) return;
    const i = (idx + els.length) % els.length;
    els[i]?.focus();
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
        // Let focus leave naturally but close the menu.
        close(false);
        break;
    }
  }

  const menu = (
    <div
      ref={menuRef}
      id={menuId}
      role="menu"
      aria-label={ariaLabel}
      onKeyDown={onMenuKeyDown}
      style={{
        position: "fixed",
        top: pos?.top ?? 0,
        left: pos?.left ?? 0,
        visibility: pos ? "visible" : "hidden",
      }}
      className="z-50 min-w-[14rem] origin-top animate-[selectPop_0.14s_cubic-bezier(0.16,1,0.3,1)] overflow-hidden rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-lift)]"
    >
      {items.map((it) => {
        const cls = `flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm outline-none transition focus-visible:bg-surface-2 ${
          it.danger
            ? "text-danger hover:bg-danger/10 focus-visible:bg-danger/10"
            : "text-ink hover:bg-surface-2"
        }`;
        const inner = (
          <>
            {it.icon && (
              <span
                aria-hidden
                className={`material-symbols-outlined text-lg ${it.danger ? "text-danger" : "text-ink-muted"}`}
              >
                {it.icon}
              </span>
            )}
            <span className="min-w-0 flex-1 truncate">{it.label}</span>
          </>
        );
        if (it.href) {
          return (
            <a
              key={it.key}
              href={it.href}
              role="menuitem"
              tabIndex={-1}
              className={cls}
              onClick={() => close(false)}
            >
              {inner}
            </a>
          );
        }
        return (
          <button
            key={it.key}
            type="button"
            role="menuitem"
            tabIndex={-1}
            className={cls}
            onClick={() => {
              close(false);
              it.onSelect?.();
            }}
          >
            {inner}
          </button>
        );
      })}
    </div>
  );

  return (
    <div ref={rootRef} className="relative">
      {renderTrigger({
        ref: triggerRef,
        onClick: () => (open ? close(false) : openMenu()),
        "aria-haspopup": "menu",
        "aria-expanded": open,
        "aria-controls": open ? menuId : undefined,
        // Icon-only triggers get their name from the menu label.
        "aria-label": ariaLabel,
      })}

      {open && typeof document !== "undefined"
        ? createPortal(menu, document.body)
        : null}
    </div>
  );
}
