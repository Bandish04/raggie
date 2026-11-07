// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { ToolStep } from "@/components/chat/chat-model";
import { Icon } from "@/components/chat/chat-ui";
/* A single tool-step row: a status icon (spinner while running, check on done,
   error on failure) + the tool name. Calm/borderless — a quiet text row, not a
   chip, matching DeepQueryRow. */
export function ToolStepRow({ step }: { step: ToolStep }) {
  const t = useTranslations("chat");
  const icon =
    step.status === "running" ? "sync" : step.status === "error" ? "error" : "check_circle";
  const label =
    step.status === "running"
      ? t("toolRunning", { name: step.name })
      : step.status === "error"
        ? t("toolError", { name: step.name })
        : t("toolDone", { name: step.name });
  return (
    <div className="flex items-start gap-2 py-0.5 text-xs leading-snug text-ink-muted">
      <Icon
        name={icon}
        className={`mt-px shrink-0 text-sm ${
          step.status === "running"
            ? "animate-spin text-ink-muted/70"
            : step.status === "error"
              ? "text-danger"
              : "text-ink-muted/70"
        }`}
      />
      <span className="min-w-0 break-words">{label}</span>
    </div>
  );
}

/* The agentic tool-use panel: a calm, borderless disclosure listing the MCP tool
   calls made this turn (one ToolStepRow each). Mirrors DeepResearchPanel —
   muted, compact, collapsed by default once the answer streams. While any step
   is still running, it stays expanded so progress is visible. Renders nothing
   without steps. */
export function ToolStepsPanel({ steps }: { steps: ToolStep[] }) {
  const t = useTranslations("chat");
  const running = steps.some((s) => s.status === "running");
  const [open, setOpen] = useState(false);
  if (steps.length === 0) return null;

  // Active phase: a quiet borderless status header + the live step rows.
  if (running) {
    return (
      <div role="status" className="mb-1">
        <div className="flex items-center gap-2 text-sm text-ink-muted">
          <Icon name="construction" className="animate-pulse text-base text-ink-muted" />
          <span>{t("toolsRunning")}</span>
        </div>
        <div className="mt-1.5 pl-0.5">
          {steps.map((s) => (
            <ToolStepRow key={s.id} step={s} />
          ))}
        </div>
      </div>
    );
  }

  // Recap phase (answer streaming/done): a muted inline toggle, collapsed.
  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="-ml-1 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium text-ink-muted transition hover:text-ink"
      >
        <Icon name="construction" className="text-sm" />
        <span>
          {t("toolsUsed")} · {steps.length}
        </span>
        <Icon name="expand_more" className={`text-sm transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2 pl-1">
          {steps.map((s) => (
            <ToolStepRow key={s.id} step={s} />
          ))}
        </div>
      )}
    </div>
  );
}
