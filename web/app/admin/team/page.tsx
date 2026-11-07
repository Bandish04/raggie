// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import InvitePanel from "@/components/admin/invite-panel";
import {
  listDepartments,
  listInvites,
  listLocations,
  listOrgUsers,
  listOrgWorkspaces,
  listTeams,
  me,
} from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function TeamPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");

  const t = await getTranslations("admin");
  const orgId = user.org_id;
  const [teams, workspaces, invites, users, departments, locations] = orgId
    ? await Promise.all([
        listTeams(token, orgId),
        listOrgWorkspaces(token, orgId),
        listInvites(token),
        listOrgUsers(token, orgId),
        listDepartments(token, orgId),
        listLocations(token, orgId),
      ])
    : [[], [], [], [], [], []];

  return (
    <AdminShell active="team" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("teamTitle")} subtitle={t("teamSubtitle")}>
      <InvitePanel
        teams={teams}
        workspaces={workspaces}
        invites={invites}
        users={users}
        departments={departments}
        locations={locations}
      />
    </AdminShell>
  );
}
