// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import UsageTable from "@/components/admin/usage-table";
import { me, usageByUser } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

/**
 * Token usage by user (#7) — "who burns the most tokens". WORKSPACE_ADMIN+.
 * Sorted by total tokens desc so the heaviest consumer is at the top.
 */
export default async function UsagePage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  // WORKSPACE_ADMIN+ (backend also enforces). Keep STAFF out.
  if (user.role === "STAFF") redirect("/dashboard");

  const t = await getTranslations("admin");
  const rows = await usageByUser(token);
  const sorted = [...rows].sort((a, b) => b.total_tokens - a.total_tokens);

  return (
    <AdminShell active="usage" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("usageTitle")} subtitle={t("usageSubtitle")}>
      <UsageTable rows={sorted} />
    </AdminShell>
  );
}
