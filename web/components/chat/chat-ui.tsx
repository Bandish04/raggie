// SPDX-License-Identifier: Apache-2.0

"use client";

import { type ReactNode, useState } from "react";

import { copyToClipboard } from "@/lib/clipboard";
export function Icon({ name, className = "", fill = false }: { name: string; className?: string; fill?: boolean }) {
  return (
    <span aria-hidden className={`material-symbols-outlined ${fill ? "fill" : ""} ${className}`}>
      {name}
    </span>
  );
}

/* Small copy-to-clipboard button that swaps to a check for ~1.5s. */
export function CopyButton({ getText, label }: { getText: () => string; label: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    // copyToClipboard falls back to execCommand("copy") on plain-HTTP origins
    // where the async Clipboard API is unavailable (on-prem LAN deployments).
    const ok = await copyToClipboard(getText());
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      title={label}
      className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-2 hover:text-ink"
    >
      <Icon name={copied ? "check" : "content_copy"} className={`text-base ${copied ? "text-success" : ""}`} />
    </button>
  );
}

/* Pull plain text out of a rendered markdown node tree, so the code-block copy
   button can grab the source without a DOM ref (survives streaming re-renders). */
export function nodeText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (typeof node === "object" && "props" in node) {
    return nodeText((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}

/* Code block: monospace card on surface-2 with an always-discoverable copy
   button (appears on hover/focus). Reads its own rendered text. */
export function CodeBlock({ children, label }: { children?: ReactNode; label: string }) {
  const raw = nodeText(children).replace(/\n$/, "");
  return (
    <div className="group relative my-4 first:mt-0 last:mb-0">
      <div className="absolute right-2 top-2 opacity-0 transition focus-within:opacity-100 group-hover:opacity-100">
        <CopyButton getText={() => raw} label={label} />
      </div>
      <pre className="overflow-x-auto rounded-2xl border border-border bg-surface-2 p-4 font-mono text-[0.82rem] leading-relaxed text-ink">
        {children}
      </pre>
    </div>
  );
}
