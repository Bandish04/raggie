// SPDX-License-Identifier: Apache-2.0

"use client";

// Accessible, design-system-consistent dropdown that replaces every bare native
// <select> in the app. Implements the WAI-ARIA "listbox" disclosure pattern:
// a button trigger that opens a focusable listbox with full keyboard support
// (Arrow/Home/End/Enter/Escape + typeahead). A hidden <input name> mirrors the
// value so server-action <form>s keep working unchanged. Zero dependencies.

import { useEffect, useId, useMemo, useRef, useState } from "react";

export type SelectOption = {
  value: string;
  label: string;
  icon?: string; // Material Symbols name
  disabled?: boolean;
};

type SelectProps = {
  options: SelectOption[];
  value?: string; // controlled
  defaultValue?: string; // uncontrolled
  onValueChange?: (value: string) => void;
  name?: string; // emits a hidden input for forms
  placeholder?: string;
  size?: "sm" | "md";
  ariaLabel?: string;
  className?: string; // applied to the root wrapper (sizing)
  disabled?: boolean;
  required?: boolean;
  id?: string;
};

export default function Select({
  options,
  value,
  defaultValue,
  onValueChange,
  name,
  placeholder = "Seç…",
  size = "md",
  ariaLabel,
  className = "",
  disabled = false,
  required = false,
  id,
}: SelectProps) {
  const isControlled = value !== undefined;
  const [internal, setInternal] = useState(defaultValue ?? "");
  const current = isControlled ? (value as string) : internal;

  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const typeahead = useRef<{ q: string; timer: ReturnType<typeof setTimeout> | null }>({
    q: "",
    timer: null,
  });

  const baseId = useId();
  const listId = `${baseId}-list`;
  const optId = (i: number) => `${baseId}-opt-${i}`;

  const selected = useMemo(() => options.find((o) => o.value === current), [options, current]);
  const firstEnabled = () => options.findIndex((o) => !o.disabled);

  // Close on outside pointer.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // Move focus into the listbox when it opens (DOM sync only — no setState here).
  useEffect(() => {
    if (open) listRef.current?.focus();
  }, [open]);

  // Keep the highlighted option scrolled into view.
  useEffect(() => {
    if (open && highlight >= 0) {
      document.getElementById(optId(highlight))?.scrollIntoView({ block: "nearest" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlight, open]);

  function openList() {
    if (disabled) return;
    const idx = options.findIndex((o) => o.value === current);
    setHighlight(idx >= 0 ? idx : firstEnabled());
    setOpen(true);
  }

  function closeList(focusTrigger = true) {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }

  function commit(i: number) {
    const opt = options[i];
    if (!opt || opt.disabled) return;
    if (!isControlled) setInternal(opt.value);
    onValueChange?.(opt.value);
    closeList();
  }

  function move(dir: 1 | -1) {
    setHighlight((h) => {
      let i = h;
      for (let step = 0; step < options.length; step++) {
        i = (i + dir + options.length) % options.length;
        if (!options[i]?.disabled) return i;
      }
      return h;
    });
  }

  function onListKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        move(1);
        break;
      case "ArrowUp":
        e.preventDefault();
        move(-1);
        break;
      case "Home":
        e.preventDefault();
        setHighlight(firstEnabled());
        break;
      case "End":
        e.preventDefault();
        for (let i = options.length - 1; i >= 0; i--)
          if (!options[i].disabled) {
            setHighlight(i);
            break;
          }
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        commit(highlight);
        break;
      case "Escape":
        e.preventDefault();
        closeList();
        break;
      case "Tab":
        closeList(false);
        break;
      default:
        // Typeahead: jump to the next option whose label starts with the typed run.
        // A timer (not a timestamp) resets the buffer, keeping the handler pure.
        if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) {
          const ta = typeahead.current;
          ta.q += e.key;
          if (ta.timer) clearTimeout(ta.timer);
          ta.timer = setTimeout(() => {
            ta.q = "";
            ta.timer = null;
          }, 600);
          const q = ta.q.toLowerCase();
          const start = highlight < 0 ? 0 : highlight;
          for (let k = 1; k <= options.length; k++) {
            const i = (start + k) % options.length;
            const o = options[i];
            if (!o.disabled && o.label.toLowerCase().startsWith(q)) {
              setHighlight(i);
              break;
            }
          }
        }
    }
  }

  function onTriggerKeyDown(e: React.KeyboardEvent) {
    if (open) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openList();
    }
  }

  const trigger =
    size === "sm"
      ? "inline-flex h-8 items-center gap-1.5 rounded-full border border-border bg-surface px-3 text-sm"
      : "flex h-10 w-full items-center justify-between gap-2 rounded-xl border border-border bg-surface px-3.5 text-sm";

  const rootW = size === "sm" ? "inline-block" : "w-full";

  return (
    <div ref={rootRef} className={`relative ${rootW} ${className}`}>
      {name && <input type="hidden" name={name} value={current} required={required} />}

      <button
        ref={triggerRef}
        type="button"
        id={id}
        disabled={disabled}
        onClick={() => (open ? closeList(false) : openList())}
        onKeyDown={onTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        // Name = label + the visible value (WCAG 2.5.3, label in name).
        aria-labelledby={ariaLabel ? `${baseId}-label ${baseId}-value` : undefined}
        className={`${trigger} text-ink outline-none transition focus-visible:border-brand focus-visible:ring-4 focus-visible:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-50`}
      >
        {ariaLabel ? (
          <span id={`${baseId}-label`} className="sr-only">
            {ariaLabel}
          </span>
        ) : null}
        <span className={`flex min-w-0 items-center gap-2 ${selected ? "" : "text-ink-muted"}`}>
          {selected?.icon && (
            <span className="material-symbols-outlined text-base text-ink-muted" aria-hidden>
              {selected.icon}
            </span>
          )}
          <span id={`${baseId}-value`} className="truncate">
            {selected ? selected.label : placeholder}
          </span>
        </span>
        <span
          className={`material-symbols-outlined shrink-0 text-lg text-ink-muted transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        >
          expand_more
        </span>
      </button>

      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          tabIndex={-1}
          aria-activedescendant={highlight >= 0 ? optId(highlight) : undefined}
          onKeyDown={onListKeyDown}
          onBlur={(e) => {
            if (!rootRef.current?.contains(e.relatedTarget as Node)) setOpen(false);
          }}
          className="absolute z-50 mt-1.5 max-h-72 w-full min-w-[11rem] origin-top animate-[selectPop_0.14s_cubic-bezier(0.16,1,0.3,1)] overflow-auto rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-lift)] outline-none"
        >
          {options.map((o, i) => {
            const isSel = o.value === current;
            const isHi = i === highlight;
            return (
              <li
                key={o.value}
                id={optId(i)}
                role="option"
                aria-selected={isSel}
                aria-disabled={o.disabled || undefined}
                onMouseEnter={() => !o.disabled && setHighlight(i)}
                onClick={() => commit(i)}
                className={`flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink ${
                  isHi ? "bg-surface-2" : ""
                } ${o.disabled ? "cursor-not-allowed opacity-40" : ""}`}
              >
                {o.icon && (
                  <span className="material-symbols-outlined text-base text-ink-muted">{o.icon}</span>
                )}
                <span className="min-w-0 flex-1 truncate">{o.label}</span>
                {isSel && (
                  <span className="material-symbols-outlined text-lg text-brand" aria-hidden>
                    check
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
