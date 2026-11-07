// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import KnowledgeBaseClient from "@/components/admin/knowledge-base-client";
import {
  listFolders,
  listMyWorkspaces,
  me,
  type DocumentFolder,
} from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function KnowledgeBasePage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");

  const t = await getTranslations("admin");
  const workspaces = await listMyWorkspaces(token);

  // Seed folders for the first workspace; the client refetches folders +
  // documents whenever the workspace or current folder changes.
  const firstWs = workspaces[0]?.id ?? "";
  const folders: DocumentFolder[] = firstWs ? await listFolders(token, firstWs) : [];

  return (
    <AdminShell active="kb" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("kbTitle")} subtitle={t("kbSubtitle")}>
      <KnowledgeBaseClient
        workspaces={workspaces}
        initialFolders={folders}
        canRetryFailed={isPlatformAdmin(user)}
      />
    </AdminShell>
  );
}
