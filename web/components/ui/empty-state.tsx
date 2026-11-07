// SPDX-License-Identifier: Apache-2.0

import * as React from "react";
import { Icon } from "./icon";

type EmptyStateProps = {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
};

/** Friendly, calm empty state — used when a list/table/page has nothing yet. */
export function EmptyState({ icon, title, description, action, className = "" }: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-surface px-6 py-14 text-center ${className}`}
    >
      {icon ? (
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-surface-2 text-ink-muted">
          <Icon name={icon} size={24} />
        </span>
      ) : null}
      <h3 className="font-display text-lg font-semibold tracking-tight text-ink">{title}</h3>
      {description ? <p className="max-w-sm text-sm text-ink-muted">{description}</p> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
