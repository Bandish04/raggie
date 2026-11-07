// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { copyToClipboard } from "@/lib/clipboard";

// Read-only command box with copy — the operator runs it on the host (the web app
// never executes anything on the host).
export default function UpdateCommand({ command }: { command: string }) {
  const tc = useTranslations("common");
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (await copyToClipboard(command)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    }
  }
  return (
    <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 p-2 pl-4">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre text-xs text-ink">{command}</code>
      <button
        type="button"
        onClick={copy}
        className="shrink-0 rounded-lg bg-ink px-3 py-1.5 text-xs font-semibold text-bg transition hover:opacity-90"
      >
        {copied ? tc("copied") : tc("copy")}
      </button>
    </div>
  );
}
