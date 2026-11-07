// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import MarketplaceClient from "@/components/admin/marketplace-client";
import AdminShell from "@/components/admin/shell";
import {
  listIntegrationProviders,
  listIntegrations,
  listOrgWorkspaces,
  me,
  type WorkspaceRow,
} from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function MarketplacePage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  if (user.role === "STAFF") redirect("/dashboard");

  let workspaces: WorkspaceRow[] = [];
  if (user.org_id) workspaces = await listOrgWorkspaces(token, user.org_id);
  const [providers, integrations] = await Promise.all([
    listIntegrationProviders(token),
    listIntegrations(token),
  ]);
  const t = await getTranslations("admin");

  return (
    <AdminShell
      active="marketplace"
      email={user.email}
      platformAdmin={isPlatformAdmin(user)}
      title={t("mktTitle")}
      subtitle={t("mktSubtitle")}
    >
      <MarketplaceClient
        providers={providers}
        integrations={integrations}
        workspaces={workspaces}
        platformAdmin={isPlatformAdmin(user)}
      />
    </AdminShell>
  );
}
