// SPDX-License-Identifier: Apache-2.0

// Shared class strings so every screen speaks the same design language —
// Apple-style: pill buttons, filled System-Blue primary, hairline inputs.
export const ui = {
  btnPrimary:
    "inline-flex items-center justify-center gap-2 rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-brand-contrast transition-colors hover:bg-brand-strong active:scale-[0.98] disabled:opacity-40 disabled:active:scale-100",
  btnGhost:
    "inline-flex items-center justify-center gap-2 rounded-full border border-border bg-surface-2 px-5 py-2.5 text-sm font-medium text-ink transition-colors hover:bg-surface-3 active:scale-[0.98]",
  // 40px (h-10) control height — shared by Input, Select (md), and pill buttons
  // so labels/inputs/selects/buttons sit on one baseline in flex rows.
  input:
    "h-10 w-full rounded-xl border border-border bg-surface px-3.5 text-sm text-ink placeholder:text-ink-muted/60 outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/15",
  label: "text-sm font-medium text-ink",
  card: "card",
  // iOS-style grouped inset form: one rounded container, rows split by hairlines.
  fieldGroup: "divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface",
  fieldRow:
    "w-full bg-transparent px-4 py-3.5 text-[15px] text-ink placeholder:text-ink-muted/60 outline-none transition focus:bg-surface-2/70",
} as const;
