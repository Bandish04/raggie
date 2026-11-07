// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import OrganizationTabs, { type OrgTab } from "@/components/admin/organization-tabs";
import AdminShell from "@/components/admin/shell";
import { EmptyState } from "@/components/ui/empty-state";
import {
  getOrgChart,
  listDepartments,
  listLocations,
  listOrgUsers,
  listTeams,
  me,
} from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

const TABS: OrgTab[] = ["people", "teams", "directory", "org-chart"];

function parseTab(raw: string | string[] | undefined): OrgTab {
  const v = Array.isArray(raw) ? raw[0] : raw;
  return TABS.includes(v as OrgTab) ? (v as OrgTab) : "people";
}

/**
 * Consolidated Organization admin surface (#13). Replaces the four former
 * top-level entries (People, Teams, Directory, Org chart) with one tabbed page.
 * Fetches everything those pages fetched, then hands the data to a client tab
 * container. Deep-linkable via `?tab=people|teams|directory|org-chart`.
 */
export default async function OrganizationPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string | string[] }>;
}) {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  // Defense in depth: the control plane also enforces this; keep STAFF out.
  if (user.role === "STAFF") redirect("/dashboard");

  const t = await getTranslations("admin");
  const tab = parseTab((await searchParams).tab);

  // SUPER_ADMIN may not belong to an org → show a calm empty state, don't crash.
  if (!user.org_id) {
    return (
      <AdminShell
        active="organization"
        email={user.email}
        platformAdmin={isPlatformAdmin(user)}
        title={t("organizationTitle")}
        subtitle={t("organizationSubtitle")}
      >
        <EmptyState icon="groups" title={t("dirNoOrg")} description={t("dirNoOrgHint")} />
      </AdminShell>
    );
  }

  const [users, departments, locations, teams, orgChart] = await Promise.all([
    listOrgUsers(token, user.org_id),
    listDepartments(token, user.org_id),
    listLocations(token, user.org_id),
    listTeams(token, user.org_id),
    getOrgChart(token, user.org_id),
  ]);

  return (
    <AdminShell
      active="organization"
      email={user.email}
      platformAdmin={isPlatformAdmin(user)}
      title={t("organizationTitle")}
      subtitle={t("organizationSubtitle")}
    >
      <OrganizationTabs
        initialTab={tab}
        users={users}
        departments={departments}
        locations={locations}
        teams={teams}
        orgChart={orgChart}
        canManageSuperAdmin={user.role === "SUPER_ADMIN"}
        canManagePlatformAdmin={isPlatformAdmin(user)}
      />
    </AdminShell>
  );
}
