// SPDX-License-Identifier: Apache-2.0

import { useTranslations } from "next-intl";

import type { DocumentRow } from "@/lib/api";
import { documentFailure } from "@/lib/document-errors";

// Why a FAILED document failed, localized from its error_code/error_params
// (unknown codes: a generic line plus the English error_message as detail).
// `inline` wraps up to two lines (grid tiles); `compact` is one truncated line
// with the full text as a tooltip (list rows, tables).
export default function DocumentFailureReason({
  doc,
  variant = "inline",
  className = "",
}: {
  doc: Pick<DocumentRow, "status" | "error_code" | "error_params" | "error_message">;
  variant?: "inline" | "compact";
  className?: string;
}) {
  const t = useTranslations("admin");
  if (doc.status !== "FAILED") return null;
  const failure = documentFailure(doc);
  const message = t(failure.key, failure.values);
  const detail = failure.detail ? `${t("docErrorDetailsLabel")}: ${failure.detail}` : null;
  const full = detail ? `${message} — ${detail}` : message;

  if (variant === "compact") {
    return (
      <span className={`block truncate text-xs text-danger ${className}`} title={full} data-testid="doc-failure">
        {full}
      </span>
    );
  }
  return (
    <div className={`text-xs ${className}`} title={full} data-testid="doc-failure">
      <p className="line-clamp-2 text-danger">{message}</p>
      {detail ? <p className="mt-0.5 line-clamp-2 text-ink-muted">{detail}</p> : null}
    </div>
  );
}
