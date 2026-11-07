// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import UpdatesClient from "@/components/admin/updates-client";
import { getUpdateStatus, me } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function UpdatesPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  // Platform-wide; platform admin only (the control plane answers 403 to an
  // org SUPER_ADMIN too).
  if (!isPlatformAdmin(user)) redirect("/dashboard");

  const status = await getUpdateStatus(token);
  const t = await getTranslations("admin");

  return (
    <AdminShell active="updates" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("updatesTitle")} subtitle={t("updatesSubtitle")}>
      <UpdatesClient status={status} />
    </AdminShell>
  );
}
