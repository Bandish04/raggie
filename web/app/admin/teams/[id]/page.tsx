// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AddMemberPanel from "@/components/admin/add-member-panel";
import AdminShell from "@/components/admin/shell";
import CreateWorkspacePanel from "@/components/admin/create-workspace-panel";
import DocumentFailureReason from "@/components/admin/document-failure-reason";
import InvitePanel from "@/components/admin/invite-panel";
import MemberTable from "@/components/admin/member-table";
import UploadControl from "@/components/admin/upload-control";
import {
  getTeam,
  listOrgUsers,
  listTeamDocuments,
  listTeamMembers,
  listTeamWorkspaces,
  me,
  type DocumentStatus,
} from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

const BADGE: Record<DocumentStatus, string> = {
  SUCCESS: "bg-success/10 text-success",
  PROCESSING: "bg-accent/10 text-accent",
  PENDING: "bg-surface-2 text-ink-muted",
  FAILED: "bg-danger/10 text-danger",
  ARCHIVED: "bg-surface-2 text-ink-muted",
};

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default async function TeamDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  if (!user.org_id) redirect("/admin/organization?tab=teams");

  const team = await getTeam(token, user.org_id, id);
  if (!team) redirect("/admin/organization?tab=teams");

  const t = await getTranslations("admin");
  const [workspaces, members, documents, users] = await Promise.all([
    listTeamWorkspaces(token, user.org_id, id),
    listTeamMembers(token, user.org_id, id),
    listTeamDocuments(token, user.org_id, id),
    listOrgUsers(token, user.org_id),
  ]);
  const wsName = new Map(workspaces.map((w) => [w.id, w.name]));

  return (
    <AdminShell active="organization" email={user.email} platformAdmin={isPlatformAdmin(user)} title={team.name}>
      <div className="space-y-8">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        {/* Workspaces */}
        <Section title={t("workspacesSection")}>
          <CreateWorkspacePanel teams={[team]} defaultTeamId={team.id} />
          <div className="card overflow-hidden p-0">
            {workspaces.length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-ink-muted">{t("noWorkspaces")}</p>
            ) : (
              <ul className="divide-y divide-border/60">
                {workspaces.map((w) => (
                  <li key={w.id} className="flex items-center justify-between px-5 py-3 text-sm">
                    <span className="font-medium">{w.name}</span>
                    <span className="rounded-full bg-surface-2 px-2.5 py-1 text-xs text-ink-muted">
                      {w.type === "EXTERNAL" ? t("typeExternal") : t("typeInternal")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Section>

        {/* Members */}
        <Section title={t("members")}>
          <div className="card space-y-4 p-5">
            <AddMemberPanel teamId={team.id} users={users} existingIds={members.map((m) => m.id)} />
            <MemberTable teamId={team.id} members={members} />
          </div>
        </Section>
      </div>

      {/* Document pool */}
      <Section title={t("documentPool")}>
        <UploadControl workspaces={workspaces} />
        <div className="card overflow-hidden p-0">
          {documents.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-ink-muted">{t("kbEmpty")}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-muted">
                  <th className="px-5 py-3 font-semibold">{t("colFile")}</th>
                  <th className="px-5 py-3 font-semibold">{t("colWorkspace")}</th>
                  <th className="px-5 py-3 font-semibold">{t("colSize")}</th>
                  <th className="px-5 py-3 font-semibold">{t("colStatus")}</th>
                  <th className="px-5 py-3 font-semibold">{t("colAdded")}</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr key={d.id} className="border-b border-border/50 last:border-0">
                    <td className="max-w-[260px] truncate px-5 py-3 font-medium">{d.filename}</td>
                    <td className="px-5 py-3 text-ink-muted">{wsName.get(d.workspace_id) ?? "—"}</td>
                    <td className="px-5 py-3 tabular-nums text-ink-muted">{humanSize(d.file_size)}</td>
                    <td className="px-5 py-3">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${BADGE[d.status]}`}>
                        {t(`status${d.status}`)}
                      </span>
                      <DocumentFailureReason doc={d} variant="compact" className="mt-1 max-w-[220px]" />
                    </td>
                    <td className="px-5 py-3 text-ink-muted">{d.created_at.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Section>

      {/* Invite to this team */}
      <Section title={t("inviteToTeam")}>
        <InvitePanel teamId={team.id} />
      </Section>
      </div>
    </AdminShell>
  );
}
