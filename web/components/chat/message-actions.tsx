// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";

import { CopyButton, Icon } from "@/components/chat/chat-ui";
/* Footer actions under each assistant answer: copy, 👍/👎, + (last only) regenerate. */
export function MessageActions({
  content,
  messageId,
  feedback,
  onFeedback,
  showRegenerate,
  onRegenerate,
}: {
  content: string;
  messageId?: string;
  feedback?: "up" | "down";
  onFeedback: (rating: "up" | "down") => void;
  showRegenerate: boolean;
  onRegenerate: () => void;
}) {
  const t = useTranslations("chat");
  return (
    <div className="mt-3 flex items-center gap-0.5">
      <CopyButton getText={() => content} label={t("copyAnswer")} />
      {messageId && (
        <>
          <button
            type="button"
            onClick={() => onFeedback("up")}
            aria-label={t("feedbackUp")}
            title={t("feedbackUp")}
            aria-pressed={feedback === "up"}
            className={`grid h-8 w-8 place-items-center rounded-lg transition ${
              feedback === "up" ? "bg-success/10 text-success" : "text-ink-muted hover:bg-surface-2 hover:text-ink"
            }`}
          >
            <Icon name="thumb_up" fill={feedback === "up"} className="text-base" />
          </button>
          <button
            type="button"
            onClick={() => onFeedback("down")}
            aria-label={t("feedbackDown")}
            title={t("feedbackDown")}
            aria-pressed={feedback === "down"}
            className={`grid h-8 w-8 place-items-center rounded-lg transition ${
              feedback === "down" ? "bg-danger/10 text-danger" : "text-ink-muted hover:bg-surface-2 hover:text-ink"
            }`}
          >
            <Icon name="thumb_down" fill={feedback === "down"} className="text-base" />
          </button>
        </>
      )}
      {showRegenerate && (
        <>
          <span className="mx-1 h-4 w-px bg-border" />
          <button
            type="button"
            onClick={onRegenerate}
            aria-label={t("regenerate")}
            title={t("regenerate")}
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="refresh" className="text-base" />
          </button>
        </>
      )}
    </div>
  );
}
