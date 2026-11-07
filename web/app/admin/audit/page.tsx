// SPDX-License-Identifier: Apache-2.0

import { getLocale, getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import { listAudit, me } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function AuditPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  // Audit log is SUPER_ADMIN-only (the backend enforces this too).
  if (user.role !== "SUPER_ADMIN") redirect("/dashboard");

  const t = await getTranslations("admin");
  const locale = await getLocale();
  const entries = await listAudit(token);

  return (
    <AdminShell active="audit" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("auditTitle")} subtitle={t("auditSubtitle")}>
      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        {entries.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-ink-muted">{t("auditEmpty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-muted">
                <th className="px-5 py-3 font-semibold">{t("auditAction")}</th>
                <th className="px-5 py-3 font-semibold">{t("auditTarget")}</th>
                <th className="px-5 py-3 font-semibold">{t("auditActor")}</th>
                <th className="px-5 py-3 font-semibold">{t("colWhen")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr
                  key={i}
                  className="border-b border-border/50 last:border-0 hover:bg-surface-2/50"
                >
                  <td className="px-5 py-3.5">
                    <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-ink">
                      {e.action}
                    </code>
                  </td>
                  <td className="max-w-xs truncate px-5 py-3.5 text-ink-muted">{e.target ?? "—"}</td>
                  <td className="max-w-[12rem] truncate px-5 py-3.5 text-ink-muted">
                    {e.actor ?? "—"}
                  </td>
                  <td className="px-5 py-3.5 text-ink-muted">
                    {new Date(e.created_at).toLocaleString(locale)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </AdminShell>
  );
}
