// SPDX-License-Identifier: Apache-2.0

"use client";

import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Column, DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import type { UserTokenUsage } from "@/lib/api";

const rowKey = (r: UserTokenUsage) => r.user_id ?? "anonymous";

/**
 * Calm "who burns the most tokens" table (#7). Rows arrive pre-sorted by tokens
 * desc from the server. The top spender gets a subtle filled bar + badge so the
 * heaviest consumer is obvious at a glance. The anonymous widget row comes back
 * as { user_id: null, email: "anonymous" } and is labelled clearly.
 */
export default function UsageTable({ rows }: { rows: UserTokenUsage[] }) {
  const t = useTranslations("admin");
  const numberFormat = new Intl.NumberFormat(useLocale());
  const fmt = (n: number) => numberFormat.format(n);

  const isAnonymous = (r: UserTokenUsage) => r.user_id === null || r.email === "anonymous";
  const userLabel = (r: UserTokenUsage) =>
    isAnonymous(r) ? t("usageAnonymous") : r.full_name || r.email;

  // Bars are relative to the heaviest consumer so the scale reads instantly.
  // `DataTable` cells don't receive an index, so derive the single top row by key.
  const peak = Math.max(1, ...rows.map((r) => r.total_tokens));
  const topKey = rows.length > 1 && rows[0].total_tokens > 0 ? rowKey(rows[0]) : null;

  const columns: Column<UserTokenUsage>[] = [
    {
      key: "user",
      header: t("usageColUser"),
      cell: (r) => (
        <div className="flex items-center gap-2">
          <span className="font-medium text-ink">{userLabel(r)}</span>
          {rowKey(r) === topKey && <Badge tone="brand">{t("usageTopSpender")}</Badge>}
        </div>
      ),
    },
    {
      key: "email",
      header: t("usageColEmail"),
      cell: (r) =>
        isAnonymous(r) ? (
          <span className="text-ink-muted">—</span>
        ) : (
          <span className="text-ink-muted">{r.email}</span>
        ),
    },
    {
      key: "messages",
      header: t("usageColMessages"),
      align: "right",
      cell: (r) => <span className="tabular-nums">{fmt(r.message_count)}</span>,
    },
    {
      key: "tokens",
      header: t("usageColTokens"),
      align: "right",
      cell: (r) => {
        const top = rowKey(r) === topKey;
        return (
          <div className="flex items-center justify-end gap-3">
            <div className="hidden h-1.5 w-28 overflow-hidden rounded-full bg-surface-2 sm:block">
              <div
                className={`h-full rounded-full transition-all duration-500 ${top ? "bg-brand" : "bg-brand/40"}`}
                style={{
                  width: `${Math.max(r.total_tokens > 0 ? 4 : 0, (r.total_tokens / peak) * 100)}%`,
                }}
              />
            </div>
            <span className={`tabular-nums ${top ? "font-semibold text-ink" : ""}`}>
              {fmt(r.total_tokens)}
            </span>
          </div>
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={rowKey}
      empty={
        <EmptyState icon="monitoring" title={t("usageEmpty")} description={t("usageEmptyHint")} />
      }
    />
  );
}
