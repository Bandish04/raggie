// SPDX-License-Identifier: Apache-2.0

import * as React from "react";

type Tone = "neutral" | "brand" | "success" | "warning" | "danger";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-muted",
  brand: "bg-brand/10 text-brand",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-danger/10 text-danger",
};

type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  tone?: Tone;
  dot?: boolean;
};

/** Quiet status / category chip. One consistent pill across the whole product. */
export function Badge({ tone = "neutral", dot = false, className = "", children, ...props }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${tones[tone]} ${className}`}
      {...props}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

/** Maps a document/job status to a tone, so status pills look the same everywhere. */
export const STATUS_TONE: Record<string, Tone> = {
  PENDING: "warning",
  PROCESSING: "brand",
  SUCCESS: "success",
  READY: "success",
  ARCHIVED: "neutral",
  FAILED: "danger",
  CONNECTED: "success",
  ERROR: "danger",
  DISCONNECTED: "neutral",
  SYNCING: "brand",
};
