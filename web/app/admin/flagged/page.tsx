// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import { listFlagged, listMyWorkspaces, me } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function FlaggedPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");

  const t = await getTranslations("admin");
  const [rows, workspaces] = await Promise.all([listFlagged(token), listMyWorkspaces(token)]);
  const nameById = new Map(workspaces.map((w) => [w.id, w.name]));

  return (
    <AdminShell active="flagged" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("flaggedTitle")} subtitle={t("flaggedSubtitle")}>
      <div className="card overflow-hidden p-0">
        {rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-20 text-center">
            <span className="material-symbols-outlined text-4xl text-success/70">verified</span>
            <p className="text-sm text-ink-muted">{t("flaggedEmpty")}</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-muted">
                <th className="px-5 py-3 font-semibold">{t("colQuestion")}</th>
                <th className="px-5 py-3 font-semibold">{t("colWorkspace")}</th>
                <th className="px-5 py-3 font-semibold">{t("colScore")}</th>
                <th className="px-5 py-3 font-semibold">{t("colAdded")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-b border-border/50 last:border-0 hover:bg-surface-2/50">
                  <td className="max-w-[420px] truncate px-5 py-3.5 font-medium">
                    <span className="material-symbols-outlined mr-2 align-middle text-base text-danger">flag</span>
                    {c.preview ?? "—"}
                  </td>
                  <td className="px-5 py-3.5 text-ink-muted">{nameById.get(c.workspace_id) ?? "—"}</td>
                  <td className="px-5 py-3.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="inline-flex items-center rounded-full bg-danger/10 px-2.5 py-1 text-xs font-medium tabular-nums text-danger">
                        {c.evaluation_score.toFixed(2)}
                      </span>
                      {c.faithfulness_score !== null && (
                        <span className="text-[11px] tabular-nums text-ink-muted">
                          {t("scoreFaithfulness")} {c.faithfulness_score.toFixed(2)}
                        </span>
                      )}
                      {c.citation_validity_score !== null && (
                        <span className="text-[11px] tabular-nums text-ink-muted">
                          {t("scoreCitationValidity")} {c.citation_validity_score.toFixed(2)}
                        </span>
                      )}
                      {c.citation_coverage_score !== null && (
                        <span className="text-[11px] tabular-nums text-ink-muted">
                          {t("scoreCitationCoverage")} {c.citation_coverage_score.toFixed(2)}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-ink-muted">{c.created_at.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </AdminShell>
  );
}
