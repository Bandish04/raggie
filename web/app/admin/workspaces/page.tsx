// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import CreateWorkspacePanel from "@/components/admin/create-workspace-panel";
import { Icon } from "@/components/ui/icon";
import WorkspaceFlagToggle from "@/components/admin/workspace-personalization-toggle";
import WorkspaceWidgetOrigins from "@/components/admin/workspace-widget-origins";
import {
  getWorkspaceSettings,
  listOrgWorkspaces,
  listTeams,
  me,
  type TeamRow,
  type WorkspaceRow,
} from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function WorkspacesPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");

  const t = await getTranslations("admin");
  let workspaces: WorkspaceRow[] = [];
  let teams: TeamRow[] = [];
  if (user.org_id) {
    [workspaces, teams] = await Promise.all([
      listOrgWorkspaces(token, user.org_id),
      listTeams(token, user.org_id),
    ]);
  }
  const teamName = new Map(teams.map((tm) => [tm.id, tm.name]));
  // memory_available is the global MEMORY_ENABLED switch; any workspace's
  // settings report it. Unknown (no workspace / error) leaves the toggle usable.
  const memoryAvailable = workspaces[0]
    ? ((await getWorkspaceSettings(token, workspaces[0].id))?.memory_available ?? true)
    : true;

  return (
    <AdminShell
      active="workspaces"
      email={user.email}
      platformAdmin={isPlatformAdmin(user)}
      title={t("workspacesTitle")}
      subtitle={t("workspacesSubtitle")}
    >
      <CreateWorkspacePanel teams={teams} />

      <div className="card mt-5 overflow-hidden p-0">
        {workspaces.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-ink-muted">{t("noWorkspaces")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-muted">
                <th className="px-5 py-3 font-semibold">{t("workspaceName")}</th>
                <th className="px-5 py-3 font-semibold">{t("colType")}</th>
                <th className="px-5 py-3 font-semibold">{t("colTeam")}</th>
                <th className="px-5 py-3 font-semibold">{t("personalization")}</th>
                <th className="px-5 py-3 font-semibold">{t("webSearch")}</th>
                <th className="px-5 py-3 font-semibold">{t("memory")}</th>
                <th className="px-5 py-3 font-semibold">{t("widgetOrigins")}</th>
              </tr>
            </thead>
            <tbody>
              {workspaces.map((w) => (
                <tr key={w.id} className="border-b border-border/50 last:border-0 hover:bg-surface-2/50">
                  <td className="px-5 py-3.5 font-medium">{w.name}</td>
                  <td className="px-5 py-3.5">
                    <span className="rounded-full bg-surface-2 px-2.5 py-1 text-xs text-ink-muted">
                      {w.type === "EXTERNAL" ? t("typeExternal") : t("typeInternal")}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-ink-muted">
                    {w.team_id ? (teamName.get(w.team_id) ?? "—") : "—"}
                  </td>
                  <td className="px-5 py-3.5">
                    <WorkspaceFlagToggle
                      workspaceId={w.id}
                      field="personalization_enabled"
                      enabled={Boolean(w.personalization_enabled)}
                      title={t("personalization")}
                    />
                  </td>
                  <td className="px-5 py-3.5">
                    <WorkspaceFlagToggle
                      workspaceId={w.id}
                      field="web_search_enabled"
                      enabled={Boolean(w.web_search_enabled)}
                      title={t("webSearch")}
                    />
                  </td>
                  <td className="px-5 py-3.5">
                    <WorkspaceFlagToggle
                      workspaceId={w.id}
                      field="memory_enabled"
                      enabled={Boolean(w.memory_enabled)}
                      disabled={!memoryAvailable}
                      title={memoryAvailable ? t("memory") : t("memoryUnavailable")}
                    />
                  </td>
                  <td className="px-5 py-3.5">
                    {w.type === "EXTERNAL" ? (
                      <WorkspaceWidgetOrigins
                        workspaceId={w.id}
                        workspaceName={w.name}
                        origins={w.cors_allowed_origins ?? []}
                      />
                    ) : (
                      <span className="text-ink-muted" title={t("widgetOriginsInternal")}>
                        —
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="mt-3 flex items-start gap-2 text-sm text-ink-muted">
        <Icon name="info" size={18} className="mt-0.5 shrink-0" />
        <span>
          {t("memoryHelp")}
          {memoryAvailable ? null : <> {t("memoryUnavailable")}</>}
        </span>
      </p>
    </AdminShell>
  );
}
