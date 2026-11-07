// SPDX-License-Identifier: Apache-2.0

"use client";

import * as React from "react";
import { Icon } from "./icon";

type Tab = { value: string; label: string; icon?: string };

type TabsProps = {
  tabs: Tab[];
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  className?: string;
};

/** Quiet pill tab switcher. Controlled (value) or uncontrolled (defaultValue). */
export function Tabs({ tabs, value, defaultValue, onValueChange, className = "" }: TabsProps) {
  const [internal, setInternal] = React.useState(defaultValue ?? tabs[0]?.value);
  const active = value ?? internal;

  function select(next: string) {
    if (value === undefined) setInternal(next);
    onValueChange?.(next);
  }

  return (
    <div
      role="tablist"
      className={`inline-flex items-center gap-1 rounded-full border border-border bg-surface p-1 ${className}`}
    >
      {tabs.map((tab) => {
        const on = tab.value === active;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => select(tab.value)}
            className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition ${
              on ? "bg-ink text-bg" : "text-ink-muted hover:text-ink"
            }`}
          >
            {tab.icon ? <Icon name={tab.icon} size={18} /> : null}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
